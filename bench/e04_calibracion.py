#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.27",
#     "rich>=13.7",
#     "pyyaml>=6",
#     "matplotlib>=3.8",
# ]
# ///
"""E-04 · Calibración de decisores: la pregunta «¿choca?».

Pasa las parejas etiquetadas a mano (calibration/) por Jev, Haiku y Sonnet por
OpenRouter y saca:
  - acierto de Jev, Haiku y Sonnet
  - acierto de Jev cuando declara confianza >= 0,9 (y cuántas cubre)
  - falsos negativos de Jev (choques reales que deja pasar)
  - número de parejas
  gráfico de calibración       confianza declarada frente a acierto real, por tramos
  la puerta   ¿sigue el plan o se para antes de E-07?
  umbrales    acierto, cobertura y falsos negativos por umbral de confianza,
              para fijar los umbrales del kernel

    uv run --env-file .env bench/e04_calibracion.py
    uv run --env-file .env bench/e04_calibracion.py -n 10 --modelos jev   # prueba
    uv run bench/e04_calibracion.py --dry-run
    uv run bench/e04_calibracion.py --informe results/e04/<fecha-hora>     # recalcular sin llamar

Deja en results/e04/<fecha-hora>/ calls.jsonl, resumen.json, umbrales.csv,
calibracion.csv y el gráfico gráfico de calibración en claro y oscuro.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress
from rich.table import Table

from e03_decisores import (  # mismo cliente HTTP, reintentos y lectura de coste que E-03
    MODELOS,
    URL_CHAT,
    URL_SYSTEMONE,
    _describir_error,
    _texto,
    coste_de_generacion,
    enviar,
)

RAIZ = Path(__file__).resolve().parents[1]
CANDIDATAS = RAIZ / "calibration" / "candidatas.yaml"
ETIQUETAS = RAIZ / "calibration" / "etiquetas.yaml"
CLASES = ("choca", "no_choca")

# La misma definición para los tres decisores (es la de calibration/README.md).
PREGUNTA = (
    "¿Choca la acción del solicitante con lo que está haciendo el otro agente? "
    "Las lecturas y los comandos que no escriben nada nunca chocan; un comando que escribe "
    "se juzga por lo que escribe. Tocar el mismo fichero no implica choque."
)
CRITERIOS = {
    "choca": (
        "Si la acción se ejecuta ahora y el otro agente completa su intención sin coordinarse, "
        "el resultado combinado rompe algo (una llamada, un contrato, datos o tests), una de las "
        "dos tareas tiene que rehacerse, o la acción destruye o sobrescribe el trabajo del otro."
    ),
    "no_choca": (
        "Las dos cosas pueden completarse en cualquier orden y el resultado es correcto, "
        "aunque toquen el mismo fichero."
    ),
}
SISTEMA_LLM = (
    "Eres el decisor de un kernel que coordina agentes de código que trabajan a la vez sobre "
    "el mismo repositorio. Respondes solo con un objeto JSON con dos campos: decision, que es "
    "una de las opciones, y confianza, la probabilidad entre 0 y 1 de que tu decisión sea correcta."
)
ESQUEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(CLASES)},
        "confianza": {"type": "number"},
    },
    "required": ["decision", "confianza"],
    "additionalProperties": False,
}

# Tramos de confianza para gráfico de calibración. El de 0,9 se parte en dos porque es el umbral de «confianza ≥ 0,9».
TRAMOS = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 0.95), (0.95, 1.0001)]
UMBRALES = [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.99]


# --- Datos ------------------------------------------------------------------


def cargar_set(usar_propuestas: bool, consola: Console) -> list[dict]:
    pares = yaml.safe_load(CANDIDATAS.read_text(encoding="utf-8"))["pares"]
    etiquetas = {}
    if ETIQUETAS.exists():
        etiquetas = (yaml.safe_load(ETIQUETAS.read_text(encoding="utf-8")) or {}).get("etiquetas", {})
    salida, sin_etiqueta, dudosas = [], [], 0
    for p in pares:
        e = etiquetas.get(p["id"], {}).get("etiqueta")
        if e == "dudosa":
            dudosas += 1
            continue
        if e is None:
            if not usar_propuestas:
                sin_etiqueta.append(p["id"])
                continue
            e = p["propuesta"]
        origen = etiquetas[p["id"]].get("autor", "mano") if p["id"] in etiquetas else "propuesta"
        salida.append({**p, "etiqueta": e, "etiqueta_origen": origen})
    if sin_etiqueta and not usar_propuestas:
        consola.print(f"[red]{len(sin_etiqueta)} parejas sin etiquetar ({sin_etiqueta[0]}…). "
                      "Etiquétalas con bench/e04_etiquetar.py o usa --propuestas solo para probar.[/]")
        sys.exit(2)
    if dudosas:
        consola.print(f"[dim]{dudosas} parejas marcadas como dudosas quedan fuera.[/]")
    return salida


def estado_de(par: dict) -> dict:
    return {"solicitante": par["solicitante"], "otros_agentes": [par["otro"]]}


# --- Decisores --------------------------------------------------------------


def peticion(alias: str, modelo: str, estado: dict, esfuerzo: str | None, estructurada: bool,
             max_tokens: int) -> tuple[str, dict]:
    if alias == "jev":
        return URL_SYSTEMONE, {
            "model": modelo,
            "state": estado,
            "questions": {"choca": {"type": "choice", "instructions": PREGUNTA, "criteria": CRITERIOS}},
        }
    opciones = "\n".join(f"- {k}: {v}" for k, v in CRITERIOS.items())
    cuerpo = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": SISTEMA_LLM},
            {"role": "user", "content": f"{PREGUNTA}\n\nOpciones:\n{opciones}\n\n"
                                        f"Estado:\n{json.dumps(estado, ensure_ascii=False, indent=2)}"},
        ],
        "max_tokens": max_tokens,
        "usage": {"include": True},
    }
    if esfuerzo:
        cuerpo["reasoning"] = {"effort": esfuerzo}
    if estructurada:
        cuerpo["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "choca", "strict": True, "schema": ESQUEMA},
        }
    return URL_CHAT, cuerpo


def leer(alias: str, datos: dict) -> dict:
    if alias == "jev":
        r = datos["answers"]["choca"]
        uso = datos.get("usage") or {}
        return {"decision": r.get("choice"), "confianza": r.get("confidence"),
                "probabilidades": r.get("probabilities"), "coste_usd": uso.get("cost"),
                "id_generacion": datos.get("id")}
    texto = _texto(datos["choices"][0]["message"].get("content"))
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fin < 0:
        raise ValueError(f"respuesta sin JSON: {texto[:200]!r}")
    v = json.loads(texto[inicio:fin + 1])
    decision = str(v.get("decision", "")).strip().lower().replace(" ", "_") or None
    uso = datos.get("usage") or {}
    return {"decision": decision, "confianza": v.get("confianza"), "probabilidades": None,
            "coste_usd": uso.get("cost"), "id_generacion": datos.get("id")}


class Decisor:
    def __init__(self, alias, modelo, cliente, esfuerzo, max_tokens):
        self.alias, self.modelo, self.cliente = alias, modelo, cliente
        self.esfuerzo, self.max_tokens = esfuerzo, max_tokens
        self.estructurada = True

    def decidir(self, estado: dict) -> dict:
        url, cuerpo = peticion(self.alias, self.modelo, estado, self.esfuerzo, self.estructurada, self.max_tokens)
        resp, latencia, reintentos = enviar(self.cliente, url, cuerpo)
        if resp.status_code == 400 and "response_format" in cuerpo:
            self.estructurada = False
            url, cuerpo = peticion(self.alias, self.modelo, estado, self.esfuerzo, False, self.max_tokens)
            resp, latencia, reintentos = enviar(self.cliente, url, cuerpo)
        resp.raise_for_status()
        r = leer(self.alias, resp.json())
        if r["coste_usd"] is None:
            r["coste_usd"] = coste_de_generacion(self.cliente, r["id_generacion"])
        return {**r, "latencia_ms": round(latencia, 1), "reintentos": reintentos}


def ejecutar(decisores, pares, repeticiones, paralelo, salida: Path, consola: Console) -> list[dict]:
    trabajos = [(d, p, k) for d in decisores for p in pares for k in range(repeticiones)]
    registros = []
    with (salida / "calls.jsonl").open("w", encoding="utf-8") as f, \
            ThreadPoolExecutor(max_workers=paralelo) as pool, Progress(console=consola) as progreso:
        tareas = {d.alias: progreso.add_task(f"{d.alias} · {d.modelo}", total=len(pares) * repeticiones)
                  for d in decisores}

        def uno(d, p, k):
            base = {"ts": datetime.now(timezone.utc).isoformat(), "modelo_alias": d.alias, "modelo": d.modelo,
                    "par": p["id"], "repeticion": k, "etiqueta": p["etiqueta"], "categoria": p["categoria"],
                    "dificultad": p["dificultad"]}
            try:
                return {**base, **d.decidir(estado_de(p)), "error": None}
            except Exception as exc:  # se registra y cuenta como error, no para la ejecución
                return {**base, "error": _describir_error(exc)}

        futuros = [pool.submit(uno, *t) for t in trabajos]
        for fut in as_completed(futuros):
            r = fut.result()
            registros.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            progreso.advance(tareas[r["modelo_alias"]])
    for d in decisores:
        if d.alias != "jev" and not d.estructurada:
            consola.print(f"[yellow]{d.modelo} no aceptó salida estructurada; se pidió el JSON en el prompt.[/]")
    return registros


# --- Métricas ---------------------------------------------------------------


def _media(xs):
    return sum(xs) / len(xs) if xs else None


def _conf(r) -> float | None:
    c = r.get("confianza")
    return float(c) if isinstance(c, (int, float)) else None


def metricas(registros: list[dict]) -> dict:
    """Métricas por modelo. Un error o una respuesta fuera de las dos clases cuenta como fallo."""
    salida = {}
    for alias in dict.fromkeys(r["modelo_alias"] for r in registros):
        rs = [r for r in registros if r["modelo_alias"] == alias]
        validas = [r for r in rs if not r.get("error") and r.get("decision") in CLASES]
        ok = [r for r in rs if r in validas and r["decision"] == r["etiqueta"]]
        chocan = [r for r in rs if r["etiqueta"] == "choca"]
        fn = [r for r in chocan if r in validas and r["decision"] == "no_choca"]
        fp = [r for r in rs if r["etiqueta"] == "no_choca" and r in validas and r["decision"] == "choca"]
        con_conf = [r for r in validas if _conf(r) is not None]
        altas = [r for r in con_conf if _conf(r) >= 0.9]

        tramos = []
        for lo, hi in TRAMOS:
            t = [r for r in con_conf if lo <= _conf(r) < hi]
            tramos.append({
                "tramo": f"{lo:.2f}-{min(hi, 1.0):.2f}", "n": len(t),
                "confianza_media": _media([_conf(r) for r in t]),
                "acierto": _media([float(r["decision"] == r["etiqueta"]) for r in t]),
            })
        ece = sum(t["n"] / len(con_conf) * abs(t["acierto"] - t["confianza_media"])
                  for t in tramos if t["n"]) if con_conf else None

        umbrales = []
        for u in UMBRALES:
            c = [r for r in con_conf if _conf(r) >= u]
            umbrales.append({
                "umbral": u, "cubiertas": len(c), "cobertura": len(c) / len(rs) if rs else None,
                "acierto": _media([float(r["decision"] == r["etiqueta"]) for r in c]),
                "falsos_negativos": sum(r["etiqueta"] == "choca" and r["decision"] == "no_choca" for r in c),
            })

        por_categoria = {}
        for cat in dict.fromkeys(r["categoria"] for r in rs):
            c = [r for r in rs if r["categoria"] == cat]
            por_categoria[cat] = {"n": len(c), "acierto": len([r for r in c if r in ok]) / len(c)}
        por_dificultad = {}
        for dif in dict.fromkeys(r["dificultad"] for r in rs):
            c = [r for r in rs if r["dificultad"] == dif]
            por_dificultad[dif] = {"n": len(c), "acierto": len([r for r in c if r in ok]) / len(c)}

        salida[alias] = {
            "modelo": rs[0]["modelo"],
            "llamadas": len(rs),
            "errores": sum(1 for r in rs if r.get("error")),
            "no_validas": sum(1 for r in rs if not r.get("error") and r.get("decision") not in CLASES),
            "acierto": len(ok) / len(rs),
            "falsos_negativos": len(fn),
            "tasa_falsos_negativos": len(fn) / len(chocan) if chocan else None,
            "falsos_positivos": len(fp),
            "con_confianza": len(con_conf),
            "conf90_n": len(altas),
            "conf90_cobertura": len(altas) / len(rs),
            "conf90_acierto": _media([float(r["decision"] == r["etiqueta"]) for r in altas]),
            "ece": ece,
            "tramos": tramos,
            "umbrales": umbrales,
            "por_categoria": por_categoria,
            "por_dificultad": por_dificultad,
            "coste_total_usd": sum(r.get("coste_usd") or 0 for r in rs),
            "fallos": sorted({r["par"] for r in rs if r not in ok}),
        }
    return salida


def diferencia_bootstrap(registros, a: str, b: str, n: int = 2000, semilla: int = 0) -> dict | None:
    """Diferencia de acierto a - b emparejada por pareja, con intervalo del 95 % por bootstrap."""
    def por_par(alias):
        acc = {}
        for r in registros:
            if r["modelo_alias"] == alias:
                acc.setdefault(r["par"], []).append(float(not r.get("error") and r.get("decision") == r["etiqueta"]))
        return {k: sum(v) / len(v) for k, v in acc.items()}

    pa, pb = por_par(a), por_par(b)
    comunes = sorted(set(pa) & set(pb))
    if not comunes:
        return None
    difs = [pa[k] - pb[k] for k in comunes]
    rnd = random.Random(semilla)
    medias = sorted(sum(rnd.choice(difs) for _ in difs) / len(difs) for _ in range(n))
    return {"diferencia": sum(difs) / len(difs), "ic95": [medias[int(0.025 * n)], medias[int(0.975 * n) - 1]],
            "parejas": len(comunes)}


def puerta(m: dict, dif: dict | None, args) -> dict:
    motivos, notas = [], []
    jev = m.get("jev")
    if not jev:
        return {"veredicto": "sin datos", "motivos": ["No hay resultados de Jev."], "notas": []}
    if dif is not None:
        d, (lo, hi) = dif["diferencia"], dif["ic95"]
        texto = f"Jev − Haiku = {d:+.1%} (IC 95 % {lo:+.1%} a {hi:+.1%}, {dif['parejas']} parejas)"
        if d <= -args.margen_acierto:
            motivos.append(f"Jev acierta claramente menos que Haiku: {texto}.")
        else:
            notas.append(texto + ".")
    if jev["con_confianza"] == 0:
        motivos.append("Jev no devuelve confianza: no se puede calibrar.")
    else:
        if jev["ece"] is not None and jev["ece"] > args.max_ece:
            motivos.append(f"La confianza de Jev no se corresponde con su acierto: ECE {jev['ece']:.3f} > {args.max_ece}.")
        else:
            notas.append(f"ECE de Jev {jev['ece']:.3f} (máximo {args.max_ece}).")
        if jev["conf90_n"] >= args.min_n_conf90 and jev["conf90_acierto"] < args.min_acierto_conf90:
            motivos.append(f"Cuando Jev declara ≥ 0,9 acierta {jev['conf90_acierto']:.1%} "
                           f"(< {args.min_acierto_conf90:.0%}, {jev['conf90_n']} decisiones).")
        elif jev["conf90_n"] < args.min_n_conf90:
            notas.append(f"Solo {jev['conf90_n']} decisiones de Jev con confianza ≥ 0,9: el acierto con confianza ≥ 0,9 es poco fiable.")
    return {"veredicto": "PARAR" if motivos else "SIGUE", "motivos": motivos, "notas": notas}


def umbral_recomendado(jev: dict, objetivo: float) -> dict | None:
    """El umbral más bajo con el que Jev alcanza el acierto objetivo; por debajo, camino lento."""
    for u in jev["umbrales"]:
        if u["acierto"] is not None and u["acierto"] >= objetivo and u["cubiertas"] > 0:
            return {**u, "objetivo": objetivo}
    return None


def datos_clave(m: dict, n_pares: int) -> dict:
    g = lambda a, k: (m.get(a) or {}).get(k)  # noqa: E731
    return {
        "acierto de Jev": g("jev", "acierto"),
        "acierto de Haiku": g("haiku", "acierto"),
        "acierto de Sonnet": g("sonnet", "acierto"),
        "acierto de Jev con confianza ≥ 0,9": g("jev", "conf90_acierto"),
        "parejas que Jev cubre con confianza ≥ 0,9": g("jev", "conf90_cobertura"),
        "falsos negativos de Jev": g("jev", "falsos_negativos"),
        "choques reales que Jev deja pasar (%)": g("jev", "tasa_falsos_negativos"),
        "número de parejas": n_pares,
    }


# --- gráfico de calibración ------------------------------------------------------------------

# Paleta de referencia de la guía de visualización: slots 1-3 (validados todos
# contra todos en claro y oscuro), tinta, rejilla y superficie por modo.
TEMAS = {
    "claro": {"superficie": "#fcfcfb", "tinta": "#0b0b0b", "secundaria": "#52514e", "muted": "#898781",
              "rejilla": "#e1e0d9", "eje": "#c3c2b7",
              "series": {"jev": "#2a78d6", "haiku": "#eb6834", "sonnet": "#1baf7a"}},
    "oscuro": {"superficie": "#1a1a19", "tinta": "#ffffff", "secundaria": "#c3c2b7", "muted": "#898781",
               "rejilla": "#2c2c2a", "eje": "#383835",
               "series": {"jev": "#3987e5", "haiku": "#d95926", "sonnet": "#199e70"}},
}
NOMBRES = {"jev": "Jev", "haiku": "Haiku", "sonnet": "Sonnet"}


def grafico(m: dict, n_pares: int, destino: Path, tema: str, a_mano: bool, min_n: int = 3) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = TEMAS[tema]
    plt.rcParams.update({"font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"], "font.size": 12})
    fig, ax = plt.subplots(figsize=(10, 6.2), dpi=200)
    fig.patch.set_facecolor(t["superficie"])
    ax.set_facecolor(t["superficie"])

    ax.plot([0.5, 1.0], [0.5, 1.0], color=t["eje"], linewidth=1, zorder=1)
    ax.text(0.56, 0.535, "calibración perfecta", color=t["muted"], fontsize=10, ha="left", va="top")

    y_min = 0.5
    for alias in ("sonnet", "haiku", "jev"):  # Jev encima: es la serie de la historia
        if alias not in m:
            continue
        pts = [(tr["confianza_media"], tr["acierto"]) for tr in m[alias]["tramos"]
               if tr["n"] >= min_n and tr["confianza_media"] is not None and tr["confianza_media"] >= 0.5]
        if not pts:
            continue
        xs, ys = zip(*pts)
        y_min = min(y_min, *ys)
        destacado = alias == "jev"
        ax.plot(xs, ys, color=t["series"][alias], linewidth=2.5 if destacado else 2,
                solid_capstyle="round", solid_joinstyle="round", marker="o", markersize=8 if destacado else 6.5,
                markeredgecolor=t["superficie"], markeredgewidth=2, label=NOMBRES[alias], zorder=3 if destacado else 2,
                alpha=1 if destacado else 0.9)
        if destacado:
            ax.annotate("Jev", (xs[-1], ys[-1]), xytext=(10, 0), textcoords="offset points",
                        color=t["tinta"], fontsize=12, fontweight="bold", va="center")

    ax.set_xlim(0.5, 1.02)
    suelo = min(0.4, int(y_min * 10) / 10)  # que ningún tramo quede fuera por abajo
    ax.set_ylim(suelo - 0.03, 1.02)
    ax.set_xticks([0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    ax.set_yticks([v / 10 for v in range(int(round(suelo * 10)), 11)])
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.1f}".replace(".", ","))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}".replace("%", " %"))
    ax.grid(True, color=t["rejilla"], linewidth=1)
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(t["eje"])
    ax.tick_params(colors=t["muted"], length=0, labelsize=11)
    ax.set_xlabel("Confianza declarada (media del tramo)", color=t["secundaria"], labelpad=10)
    ax.set_ylabel("Acierto real", color=t["secundaria"], labelpad=10)

    fig.text(0.07, 0.95, "¿Sabe Jev cuándo acierta?", color=t["tinta"], fontsize=17, fontweight="bold")
    origen = a_mano if isinstance(a_mano, str) else ("etiquetadas a mano" if a_mano else "con etiquetas propuestas (prueba)")
    fig.text(0.07, 0.905, f"Acierto real por tramo de confianza · {n_pares} parejas {origen} · "
             f"sin tramos de menos de {min_n} decisiones", color=t["secundaria"], fontsize=11)
    leyenda = ax.legend(loc="lower right", frameon=False, labelcolor=t["secundaria"], fontsize=11)
    for linea in leyenda.get_lines():
        linea.set_markeredgecolor(t["superficie"])
    fig.subplots_adjust(left=0.1, right=0.95, top=0.85, bottom=0.12)
    fig.savefig(destino, facecolor=t["superficie"])
    plt.close(fig)


# --- Salida -----------------------------------------------------------------


def _pct(v) -> str:
    return "—" if v is None else f"{v:.1%}".replace(".", ",")


def escribir(salida: Path, registros: list[dict], pares: list[dict] | None, meta: dict, args, consola: Console) -> None:
    m = metricas(registros)
    n_pares = len({r["par"] for r in registros})
    dif = diferencia_bootstrap(registros, "jev", "haiku") if {"jev", "haiku"} <= set(m) else None
    p = puerta(m, dif, args)
    rec = umbral_recomendado(m["jev"], args.objetivo_umbral) if "jev" in m else None
    datos = datos_clave(m, n_pares)

    with (salida / "umbrales.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["modelo", "umbral", "cubiertas", "cobertura", "acierto", "falsos_negativos"])
        for alias, mm in m.items():
            for u in mm["umbrales"]:
                w.writerow([alias, u["umbral"], u["cubiertas"], u["cobertura"], u["acierto"], u["falsos_negativos"]])
    with (salida / "calibracion.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["modelo", "tramo", "n", "confianza_media", "acierto"])
        for alias, mm in m.items():
            for tr in mm["tramos"]:
                w.writerow([alias, tr["tramo"], tr["n"], tr["confianza_media"], tr["acierto"]])
    autores = meta.get("etiquetas_por_autor", {})
    if autores and set(autores) == {"mano"}:
        a_mano = True
    elif autores and "propuesta" not in autores:
        a_mano = "etiquetadas por Claude" + (f" ({autores.get('mano', 0)} revisadas a mano)" if autores.get("mano") else "")
    else:
        a_mano = False
    for tema in ("claro", "oscuro"):
        grafico(m, n_pares, salida / f"calibracion_{tema}.png", tema, a_mano)

    (salida / "resumen.json").write_text(json.dumps(
        {"meta": meta, "modelos": m, "jev_menos_haiku": dif, "puerta": p, "umbral_recomendado": rec,
         "datos": datos}, ensure_ascii=False, indent=2), encoding="utf-8")

    # Terminal
    tabla = Table(title="E-04 · ¿choca? · calibración")
    tabla.add_column("Modelo")
    for col in ("Acierto", "FN", "FP", "Err", "Conf ≥ 0,9", "Acierto ≥ 0,9", "ECE", "Fácil", "Difícil", "USD"):
        tabla.add_column(col, justify="right")
    for alias, mm in m.items():
        tabla.add_row(alias, _pct(mm["acierto"]), str(mm["falsos_negativos"]), str(mm["falsos_positivos"]),
                      str(mm["errores"] + mm["no_validas"]), _pct(mm["conf90_cobertura"]), _pct(mm["conf90_acierto"]),
                      "—" if mm["ece"] is None else f"{mm['ece']:.3f}",
                      _pct((mm["por_dificultad"].get("facil") or {}).get("acierto")),
                      _pct((mm["por_dificultad"].get("dificil") or {}).get("acierto")),
                      f"${mm['coste_total_usd']:.4f}")
    consola.print(tabla)

    cats = Table(title="Acierto por categoría")
    cats.add_column("Categoría")
    for alias in m:
        cats.add_column(alias, justify="right")
    for cat in dict.fromkeys(c for mm in m.values() for c in mm["por_categoria"]):
        cats.add_row(cat, *[_pct((mm["por_categoria"].get(cat) or {}).get("acierto")) for mm in m.values()])
    consola.print(cats)

    color = {"SIGUE": "green", "PARAR": "red"}.get(p["veredicto"], "yellow")
    lineas = [f"[bold {color}]{p['veredicto']}[/]"] + [f"• {x}" for x in p["motivos"]] + \
             [f"[dim]• {x}[/]" for x in p["notas"]]
    if rec:
        lineas.append(f"\nUmbral para el kernel: confianza ≥ {rec['umbral']} → Jev acierta {_pct(rec['acierto'])} "
                      f"y cubre {_pct(rec['cobertura'])}; el resto va al camino lento.")
    elif "jev" in m:
        lineas.append(f"\nNingún umbral lleva a Jev a {args.objetivo_umbral:.0%} de acierto.")
    consola.print(Panel("\n".join(lineas), title="Puerta de E-04", border_style=color))

    def fmt(k, v):
        if v is None:
            return "—"
        return str(v) if k in ("falsos negativos de Jev", "número de parejas") else _pct(v)
    consola.print(Panel("\n".join(f"{k}: [bold]{fmt(k, v)}[/]" for k, v in datos.items()),
                        title="Datos clave", border_style="green"))
    consola.print(f"Resultados y gráfico de calibración en [bold]{salida}[/]")


# --- CLI --------------------------------------------------------------------


def argumentos(argv):
    p = argparse.ArgumentParser(description="E-04 · calibración de decisores con la pregunta «¿choca?»")
    p.add_argument("--modelos", default="jev,haiku,sonnet")
    p.add_argument("--jev", default=MODELOS["jev"])
    p.add_argument("--haiku", default=MODELOS["haiku"])
    p.add_argument("--sonnet", default=MODELOS["sonnet"])
    p.add_argument("--esfuerzo-haiku", default="none", help="igual que en E-03 (none)")
    p.add_argument("--esfuerzo-sonnet", default="low", help="igual que en E-03 (low)")
    p.add_argument("--max-tokens", type=int, default=2048)
    p.add_argument("-n", type=int, help="usar solo las primeras n parejas (prueba)")
    p.add_argument("--repeticiones", type=int, default=1, help="llamadas por pareja y modelo (1)")
    p.add_argument("--paralelo", type=int, default=4, help="llamadas simultáneas (4)")
    p.add_argument("--propuestas", action="store_true",
                   help="usar la etiqueta propuesta donde no haya etiqueta a mano (solo para probar)")
    p.add_argument("--salida", type=Path, default=Path("results/e04"))
    p.add_argument("--informe", type=Path, help="recalcular a partir de un calls.jsonl existente, sin llamar")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--margen-acierto", type=float, default=0.05,
                   help="parar si Jev acierta esto o más por debajo de Haiku (0,05 = 5 puntos)")
    p.add_argument("--max-ece", type=float, default=0.10, help="parar si el ECE de Jev lo supera (0,10)")
    p.add_argument("--min-acierto-conf90", type=float, default=0.85,
                   help="parar si con confianza ≥ 0,9 Jev acierta menos que esto (0,85)")
    p.add_argument("--min-n-conf90", type=int, default=20, help="mínimo de decisiones ≥ 0,9 para aplicar esa regla")
    p.add_argument("--objetivo-umbral", type=float, default=0.95,
                   help="acierto que debe tener Jev por encima del umbral recomendado (0,95)")
    return p.parse_args(argv)


def main(argv=None, transport: httpx.BaseTransport | None = None) -> int:
    args = argumentos(argv)
    consola = Console()

    if args.informe:
        registros = [json.loads(x) for x in (args.informe / "calls.jsonl").read_text(encoding="utf-8").splitlines() if x]
        meta = json.loads((args.informe / "resumen.json").read_text(encoding="utf-8"))["meta"] \
            if (args.informe / "resumen.json").exists() else {}
        escribir(args.informe, registros, None, meta, args, consola)
        return 0

    pares = cargar_set(args.propuestas, consola)
    if args.n:
        pares = pares[:args.n]
    alias = [a.strip() for a in args.modelos.split(",") if a.strip()]
    modelos = {"jev": args.jev, "haiku": args.haiku, "sonnet": args.sonnet}
    esfuerzos = {"jev": None, "haiku": None if args.esfuerzo_haiku == "none" else args.esfuerzo_haiku,
                 "sonnet": None if args.esfuerzo_sonnet == "none" else args.esfuerzo_sonnet}
    balance = {c: sum(p["etiqueta"] == c for p in pares) for c in CLASES}
    consola.print(f"{len(pares)} parejas · choca {balance['choca']} · no choca {balance['no_choca']}")

    if args.dry_run:
        for a in alias:
            url, cuerpo = peticion(a, modelos[a], estado_de(pares[0]), esfuerzos[a], True, args.max_tokens)
            consola.rule(f"{a} → {url}")
            consola.print_json(json.dumps(cuerpo, ensure_ascii=False))
        return 0

    clave = os.environ.get("OPENROUTER_API_KEY")
    if not clave:
        consola.print("[red]Falta OPENROUTER_API_KEY (usa uv run --env-file .env ...).[/]")
        return 2
    salida = args.salida / datetime.now().strftime("%Y%m%d-%H%M%S")
    salida.mkdir(parents=True, exist_ok=True)
    cabeceras = {"Authorization": f"Bearer {clave}", "X-Title": "Medula E-04"}
    limites = httpx.Limits(max_connections=args.paralelo * 2)
    with httpx.Client(headers=cabeceras, timeout=120, transport=transport, limits=limites) as cliente:
        decisores = [Decisor(a, modelos[a], cliente, esfuerzos[a], args.max_tokens) for a in alias]
        registros = ejecutar(decisores, pares, args.repeticiones, args.paralelo, salida, consola)

    meta = {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "modelos": {a: modelos[a] for a in alias},
        "esfuerzos": {a: esfuerzos[a] for a in alias},
        "parejas": len(pares), "balance": balance, "repeticiones": args.repeticiones,
        "etiquetas_por_autor": {o: sum(p["etiqueta_origen"] == o for p in pares)
                                for o in dict.fromkeys(p["etiqueta_origen"] for p in pares)},
        "pregunta": PREGUNTA, "criterios": CRITERIOS,
    }
    escribir(salida, registros, pares, meta, args, consola)
    return 0


if __name__ == "__main__":
    sys.exit(main())
