"""E-04b · Dos experimentos para que el camino rápido acierte en cambios de firma.

Mide por separado, con Jev y las mismas 100 parejas de E-04 (etiquetas sin tocar):
  base         la pregunta noul «¿choca?» (la del kernel hasta ahora)
  regla        regla de símbolos compartidos; si dispara, Jev solo decide la compatibilidad
  direccional  dos noul por agente, «¿usa algo que cambia?» y «¿cambia algo que usa?»; p = la mayor
  haiku        Haiku con la pregunta del kernel (probabilidad de choque entre 0 y 1), sin razonamiento
  sonnet       Sonnet con la pregunta del kernel, esfuerzo low (como en el camino rápido del modo F)

y para cada variante busca los umbrales (bajo, alto) del camino rápido: el par que más decisiones
deja a Jev con al menos --objetivo de acierto en las que decide; el resto va al camino lento.

    uv run --project medula --env-file .env python bench/e04b_firma.py
    uv run --project medula python bench/e04b_firma.py --informe results/e04b/<fecha-hora>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml

from medula import simbolos
from medula.config import Config
from medula.decisores import ErrorDecisor, cliente
from medula.decisores.jev import Jev
from medula.decisores.llm import LLM

RAIZ = Path(__file__).resolve().parents[1]
VARIANTES = ("base", "regla", "direccional", "haiku", "sonnet")
FIRMA = ("firma", "firma_compatible")


def cargar() -> list[dict]:
    pares = yaml.safe_load((RAIZ / "calibration/candidatas.yaml").read_text())["pares"]
    et = yaml.safe_load((RAIZ / "calibration/etiquetas.yaml").read_text())["etiquetas"]
    return [{**p, "etiqueta": et[p["id"]]["etiqueta"]} for p in pares if et[p["id"]]["etiqueta"] != "dudosa"]


def decidir(variante: str, par: dict, jevs: dict) -> dict:
    x = par["otro"]["agente"]
    estado = {"solicitante": par["solicitante"], "otros_agentes": [par["otro"]]}
    if variante in ("haiku", "sonnet"):
        lote = jevs[variante].acquire(estado, [x])
        return {"p": lote.veredictos[x].p, "regla": [], "latencia_ms": lote.latencia_ms,
                "coste_usd": lote.coste_usd, "respuesta": lote.crudo.get("choices", [{}])[0].get("message")}
    regla = simbolos.compartidos(par["solicitante"]["accion"], par["otro"]) if variante == "regla" else set()
    if regla:
        lote = jevs["choca"].compatible(estado, {x: regla})
    else:
        lote = jevs["direccional" if variante == "direccional" else "choca"].acquire(estado, [x])
    return {"p": lote.veredictos[x].p, "regla": sorted(regla), "latencia_ms": lote.latencia_ms,
            "coste_usd": lote.coste_usd, "respuesta": lote.crudo.get("answers")}


def _medir(filas: list[dict], bajo: float, alto: float) -> dict | None:
    cubiertas = [f for f in filas if f["p"] < bajo or f["p"] > alto]
    if not cubiertas:
        return None
    return {
        "bajo": bajo, "alto": alto, "cobertura": len(cubiertas) / len(filas),
        "acierto": sum((f["p"] > alto) == (f["etiqueta"] == "choca") for f in cubiertas) / len(cubiertas),
        "falsos_negativos": sum(f["p"] < bajo and f["etiqueta"] == "choca" for f in cubiertas),
        "falsos_positivos": sum(f["p"] > alto and f["etiqueta"] == "no_choca" for f in cubiertas),
        "camino_lento": 1 - len(cubiertas) / len(filas),
    }


def umbrales(filas: list[dict], objetivo: float) -> dict | None:
    """Procedimiento común para los tres decisores (rejilla de 0,05):
    máxima cobertura del camino rápido con acierto >= objetivo en lo que decide, sin más falsos negativos
    que con los umbrales iniciales 0,2/0,8 y con como mucho un falso positivo más. Si ningún par llega al
    objetivo, el de más acierto que cumpla esas dos condiciones."""
    ref = _medir(filas, 0.2, 0.8)
    rejilla = [i / 20 for i in range(21)]
    cands = [m for b in rejilla for a in rejilla if a >= b and (m := _medir(filas, b, a))
             and m["falsos_negativos"] <= ref["falsos_negativos"] and m["falsos_positivos"] <= ref["falsos_positivos"] + 1]
    ok = [m for m in cands if m["acierto"] >= objetivo]
    if ok:
        return {**max(ok, key=lambda m: (m["cobertura"], m["acierto"])), "llega_al_objetivo": True}
    return {**max(cands, key=lambda m: (m["acierto"], m["cobertura"])), "llega_al_objetivo": False} if cands else None


def resumir(registros: list[dict], objetivo: float) -> dict:
    salida = {}
    for v in VARIANTES:
        rs = [r for r in registros if r["variante"] == v and r.get("p") is not None]
        if not rs:
            continue
        def acierto(sub):
            return sum((r["p"] > 0.5) == (r["etiqueta"] == "choca") for r in sub) / len(sub) if sub else None
        firma = [r for r in rs if r["categoria"] == "firma"]
        compat = [r for r in rs if r["categoria"] == "firma_compatible"]
        resto = [r for r in rs if r["categoria"] not in FIRMA]
        chocan = [r for r in rs if r["etiqueta"] == "choca"]
        salida[v] = {
            "decisiones": len(rs),
            "errores": sum(1 for r in registros if r["variante"] == v and r.get("p") is None),
            "acierto_0.5": acierto(rs),
            "acierto_firma": acierto(firma),
            "acierto_firma_compatible": acierto(compat),
            "acierto_resto": acierto(resto),
            "p_media_firma": sum(r["p"] for r in firma) / len(firma) if firma else None,
            "p_media_firma_compatible": sum(r["p"] for r in compat) / len(compat) if compat else None,
            "falsos_negativos_0.5": sum(r["p"] <= 0.5 for r in chocan),
            "resueltas_por_regla": sum(1 for r in rs if r.get("regla")),
            "umbrales": umbrales(rs, objetivo),
            "umbrales_actuales_0.2_0.8": {
                "camino_lento": sum(0.2 <= r["p"] <= 0.8 for r in rs) / len(rs),
                "acierto_rapido": acierto([r for r in rs if r["p"] < 0.2 or r["p"] > 0.8]),
            },
            "coste_usd": sum(r.get("coste_usd") or 0 for r in rs),
            "latencia_p50_ms": sorted(r["latencia_ms"] for r in rs)[len(rs) // 2],
        }
    return salida


def imprimir(res: dict) -> None:
    def pct(x):
        return "—" if x is None else f"{x:.0%}"
    print(f"\n{'':24}" + "".join(f"{v:>14}" for v in res))
    filas = [("Acierto (p > 0,5)", "acierto_0.5"), ("  firma (8, chocan)", "acierto_firma"),
             ("  firma compatible (5)", "acierto_firma_compatible"), ("  resto (87)", "acierto_resto"),
             ("p media en firma", "p_media_firma"), ("p media en compatible", "p_media_firma_compatible")]
    for nombre, k in filas:
        print(f"{nombre:24}" + "".join(f"{pct(r[k]) if 'acierto' in k else f'{r[k]:.2f}':>14}" for r in res.values()))
    print(f"{'Falsos negativos':24}" + "".join(f"{r['falsos_negativos_0.5']:>14}" for r in res.values()))
    print(f"{'Resueltas por la regla':24}" + "".join(f"{r['resueltas_por_regla']:>14}" for r in res.values()))
    print(f"{'Con 0,2/0,8: lento':24}" + "".join(f"{pct(r['umbrales_actuales_0.2_0.8']['camino_lento']):>14}" for r in res.values()))
    print(f"{'Con 0,2/0,8: acierto':24}" + "".join(f"{pct(r['umbrales_actuales_0.2_0.8']['acierto_rapido']):>14}" for r in res.values()))
    print("\nUmbrales validados (máxima cobertura con el acierto objetivo, sin más FN que 0,2/0,8 y como mucho un FP más):")
    for v, r in res.items():
        u = r["umbrales"]
        print(f"  {v:12} " + (f"bajo {u['bajo']:.2f} · alto {u['alto']:.2f} · el decisor decide {pct(u['cobertura'])} "
                              f"con {pct(u['acierto'])} de acierto, {u['falsos_negativos']} FN y {u['falsos_positivos']} FP"
                              f" · lento {pct(u['camino_lento'])}" if u else "sin candidatos"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeticiones", type=int, default=2)
    ap.add_argument("--paralelo", type=int, default=8)
    ap.add_argument("--objetivo", type=float, default=0.95)
    ap.add_argument("--variantes", default=",".join(VARIANTES))
    ap.add_argument("--informe", type=Path, nargs="+", help="uno o varios directorios de resultados a combinar")
    a = ap.parse_args()

    if a.informe:
        registros = [json.loads(l) for d in a.informe for l in (d / "calls.jsonl").read_text().splitlines() if l]
        res = resumir(registros, a.objetivo)
        if len(a.informe) == 1:
            (a.informe[0] / "resumen.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
        imprimir(res)
        return 0

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("Falta OPENROUTER_API_KEY (usa --env-file .env)", file=sys.stderr)
        return 2
    cfg = Config(db=Path("/dev/null"))
    or_ = cliente(cfg)
    jevs = {"choca": Jev(or_, cfg.modelos["jev"], 20, "choca"), "direccional": Jev(or_, cfg.modelos["jev"], 20, "direccional"),
            "haiku": LLM("haiku", or_, cfg.modelos["haiku"], 60, None),
            "sonnet": LLM("sonnet", or_, cfg.modelos["sonnet"], 90, cfg.esfuerzo_sonnet)}
    pares = cargar()
    variantes = [v for v in a.variantes.split(",") if v in VARIANTES]
    trabajos = [(v, p, k) for v in variantes for p in pares for k in range(a.repeticiones)]
    salida = RAIZ / "results" / "e04b" / datetime.now().strftime("%Y%m%d-%H%M%S")
    salida.mkdir(parents=True, exist_ok=True)

    def uno(t):
        v, p, k = t
        base = {"variante": v, "par": p["id"], "repeticion": k, "categoria": p["categoria"], "etiqueta": p["etiqueta"]}
        try:
            return {**base, **decidir(v, p, jevs)}
        except ErrorDecisor as e:
            return {**base, "p": None, "error": str(e)}

    registros = []
    with ThreadPoolExecutor(a.paralelo) as pool, (salida / "calls.jsonl").open("w") as f:
        for i, r in enumerate(pool.map(uno, trabajos), 1):
            registros.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            if i % 50 == 0:
                print(f"{i}/{len(trabajos)}", file=sys.stderr)
    res = resumir(registros, a.objetivo)
    res["_meta"] = {"modelo": cfg.modelos["jev"], "parejas": len(pares), "repeticiones": a.repeticiones,
                    "objetivo": a.objetivo, "fecha": datetime.now().isoformat(timespec="seconds")}
    (salida / "resumen.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
    imprimir({k: v for k, v in res.items() if not k.startswith("_")})
    print(f"\nResultados en {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
