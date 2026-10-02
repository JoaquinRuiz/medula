"""Compone mode_<X>.json de un run de los modos C-F: agentes, evaluación y lo que decidió Médula.

Las detecciones se miden contra ground_truth.yaml:
- un par de tareas se da por detectado si uno de sus agentes esperó al otro (cola)
  o recibió un aviso de él (buzón);
- un bloqueo es innecesario si un agente esperó a otro de un par que no choca.
"""
import itertools
import json
import sqlite3
import statistics
import sys
from pathlib import Path

import yaml

from mode_b_report import TASKS, agent_summary, load

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "medula" / "src"))
from medula.intencion import _recortar, solo_lectura  # noqa: E402  (solo stdlib)


def tarea_de(agente: str | None) -> str | None:
    return f"T{agente[1:]}" if agente and agente[1:].isdigit() else None


def par(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((a, b)))


def medula(db_path: Path) -> dict:
    if not db_path.exists():
        return {}
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    q = lambda sql: [dict(f) for f in c.execute(sql).fetchall()]  # noqa: E731
    dec = q("SELECT * FROM decisiones")
    cola = q("SELECT * FROM cola")
    buzon = q("SELECT * FROM buzon WHERE de IS NOT NULL AND de != 'medula'")
    c.close()

    # Avisos provocados por comandos que la regla de lectura actual considera lecturas (p. ej.
    # `find … -exec cat`, que antes contaba como escritura): se descuentan de las métricas de avisos.
    lectura = set()
    for d in dec:
        a = json.loads(d["accion"]) if d["accion"] else {}
        if d["tipo"] == "notify" and a.get("herramienta") == "Bash" and solo_lectura(a.get("objetivo", "")):
            d["_lectura"] = True
            lectura.add((d["agente"], _recortar(f"Bash {a.get('objetivo', '')}", 120)))
    descartados = [b for b in buzon if any(b["de"] == ag and f"Acaba de hacer {res}" in b["texto"] for ag, res in lectura)]
    buzon = [b for b in buzon if b not in descartados]

    rapidas = [d for d in dec if d["tipo"] in ("acquire", "notify") and d["decisor"] not in (None, "regla")]
    lat = sorted(d["latencia_ms"] for d in rapidas if d["latencia_ms"] is not None)
    # Avisos posibles = por cada escritura notificada, los otros agentes activos en ese momento.
    posibles = 0
    for d in dec:
        if d["tipo"] == "notify" and d["respuesta"] and not d.get("_lectura"):
            posibles += len((json.loads(d["respuesta"]) or {}).get("veredictos") or {})

    gt = yaml.safe_load((RAIZ / "ground_truth.yaml").read_text(encoding="utf-8"))
    reales = {par(p["a"], p["b"]) for p in gt["pairs"] if p["conflict"]}
    esperas = {par(tarea_de(r["agente"]), tarea_de(r["espera_a"])) for r in cola
               if tarea_de(r["agente"]) and tarea_de(r["espera_a"])}
    avisos = {par(tarea_de(b["para"]), tarea_de(b["de"])) for b in buzon if tarea_de(b["para"]) and tarea_de(b["de"])}
    detectados = (esperas | avisos) & reales

    return {
        "decisiones": len(dec),
        "decisiones_modelo": len(rapidas),
        "por_decisor": {k: sum(1 for d in dec if (d["decisor"] or "") == k) for k in sorted({d["decisor"] or "" for d in dec})},
        "latencia_p50_ms": statistics.median(lat) if lat else None,
        "latencia_p95_ms": lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None,
        "coste_decisiones_usd": round(sum(d["coste_usd"] or 0 for d in dec), 6),
        "escaladas_sonnet": sum(1 for d in dec if d["tipo"] == "lento" and d["decisor"] == "sonnet"
                                and d["pregunta"] != "verificacion"
                                and d.get("finish_reason") != "length"),  # un intento cortado y su reintento son una escalada
        "escaladas_opus": sum(1 for d in dec if d["tipo"] == "lento" and d["decisor"] == "opus"),
        "verificaciones_spec": sum(1 for d in dec if d["pregunta"] == "verificacion"),
        "propuestas_rechazadas_por_spec": sum(1 for d in dec if d["tipo"] == "lento"
                                              and (d["veredicto"] or "").startswith("rechazada")),
        "reservas": sum(1 for d in dec if d["reserva_de"]),
        "peticiones_duplicadas": sum(1 for d in dec if '"duplicada": true' in (d["respuesta"] or "")),
        "errores_decisor": sum(1 for d in dec if d["error"]),
        "esperas": [{"agente": r["agente"], "espera_a": r["espera_a"], "recurso": r["recurso"], "estado": r["estado"],
                     "segundos": round((r["hasta"] or r["desde"]) - r["desde"], 1)} for r in cola],
        "avisos_posibles": posibles,
        "avisos_enviados": len(buzon),
        "avisos_descartados_lectura": len(descartados),
        "notificaciones_de_lectura": sum(1 for d in dec if d.get("_lectura")),
        "pares_con_espera": sorted("-".join(p) for p in esperas),
        "pares_con_aviso": sorted("-".join(p) for p in avisos),
        "conflictos_reales": sorted("-".join(p) for p in reales),
        "conflictos_detectados": sorted("-".join(p) for p in detectados),
        "bloqueos_innecesarios": sorted("-".join(p) for p in esperas - reales),
        "avisos_innecesarios": sorted("-".join(p) for p in avisos - reales),
    }


def main(logs: Path) -> None:
    run = load(logs / "run.json") or {}
    t0 = run.get("t0")
    end = (load(logs / "end.json") or {}).get("t_end") or (load(logs / "finish.json") or {}).get("finished_at")
    agents = {t: agent_summary(load(logs / "agents" / f"{t}.meta.json"), load(logs / "agents" / f"{t}.json"))
              for t in TASKS}
    rounds = []
    for f in sorted(logs.glob("round-*.json"), key=lambda f: int(f.stem.split("-")[1])):
        r = load(f)
        if r:
            rounds.append({"tasks": r["tasks"], "wall_time_s": round(r["end"] - r["start"], 1)})
    m = medula(logs / "medula.db")
    evaluation = load(logs / "evaluation.json")
    coste_agentes = sum(a["cost_usd"] or 0 for a in agents.values())
    report = {
        "mode": run.get("mode"),
        "decisor": run.get("decisor"),
        "demo": bool(run.get("demo")),
        "run_id": run.get("run_id"),
        "model": run.get("model"),
        "effort": run.get("effort"),
        "modelo_agentes": f"{run.get('model')} · effort {run.get('effort')}",
        "proveedor_agentes": run.get("proveedor_agentes", "openrouter"),
        "claude_version": run.get("claude_version"),
        "effort_check": run.get("effort_check"),
        "umbrales": {k: run.get(k) for k in ("umbral_bajo", "umbral_alto", "umbral_aviso", "espera_max", "pregunta", "regla_simbolos")},
        "started_at": run.get("started_at"),
        "completed": (load(logs / "finish.json") or {}).get("exit_code") == 0
                     and not any(a.get("api_error") for a in agents.values()),
        "agentes_con_error_api": sorted(t for t, a in agents.items() if a.get("api_error")),
        "wall_time_s": round(end - t0, 1) if t0 and end else None,
        "base_sha": (load(logs / "base.json") or {}).get("base_sha"),
        "rounds": rounds,
        "agents": agents,
        "medula": m,
        "totals": {
            "agents_cost_usd": round(coste_agentes, 4),
            "decision_cost_usd": m.get("coste_decisiones_usd"),
            "cost_usd": round(coste_agentes + (m.get("coste_decisiones_usd") or 0), 4),
            "cost_note": "agentes: total_cost_usd de Claude Code (tarifa de Anthropic); decisiones: usage.cost de OpenRouter",
        },
        "evaluation": evaluation,
    }
    if evaluation:
        report["red_tests"] = evaluation["total"]["failed"]
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
