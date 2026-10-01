"""Añade una fila a results/summary.csv a partir del JSON de un run (modo B o modos C-F).

Uso: summary.py <mode_X.json>. Si el run_id ya está en el CSV, sustituye su fila.
"""
import csv
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CSV = RAIZ / "results" / "summary.csv"
COLUMNAS = [
    "run_id", "modo", "decisor", "fecha", "completado", "tests_verdes", "tests_rojos", "conflictos_git",
    "conflictos_reales", "conflictos_detectados", "bloqueos_innecesarios", "avisos_innecesarios", "tiempo_total_s", "coste_agentes_usd",
    "coste_decisiones_usd", "coste_total_usd", "umbral_bajo", "umbral_alto", "decisiones", "escaladas_sonnet", "escaladas_opus", "reservas",
    "avisos_posibles", "avisos_enviados", "avisos_descartados_lectura", "modelo_agentes", "tiempo_fiable", "canal_entre_agentes",
]
# canal_entre_agentes: los agentes usaron ListAgents/SendMessage (hablar entre sesiones) por fuera de Médula.
# tiempo_fiable=False: la ejecución se solapó con otra y su tiempo total no entra en la tabla (sí tests y costes).


def fila(d: dict) -> dict:
    ev = d.get("evaluation") or {}
    tot = ev.get("total") or {}
    m = d.get("medula") or {}
    t = d.get("totals") or {}
    es_b = d.get("mode") == "B"
    sin_medula = d.get("mode") in ("A", "B")
    return {
        "run_id": d.get("run_id"),
        "modo": d.get("mode"),
        "decisor": "git" if es_b else d.get("decisor"),
        "fecha": d.get("started_at"),
        "completado": d.get("completed"),
        "tests_verdes": tot.get("passed"),
        "tests_rojos": tot.get("failed"),
        "conflictos_git": (d.get("merge") or {}).get("textual_conflict_count") if es_b else "",
        "conflictos_reales": 2,
        "conflictos_detectados": "" if sin_medula else len(m.get("conflictos_detectados") or []),
        "bloqueos_innecesarios": "" if sin_medula else len(m.get("bloqueos_innecesarios") or []),
        "avisos_innecesarios": "" if sin_medula else len(m.get("avisos_innecesarios") or []),
        "tiempo_total_s": d.get("wall_time_s"),
        "coste_agentes_usd": t.get("agents_cost_usd"),
        "coste_decisiones_usd": t.get("resolver_cost_usd") if es_b else t.get("decision_cost_usd"),
        "coste_total_usd": t.get("cost_usd"),
        "umbral_bajo": "" if sin_medula else (d.get("umbrales") or {}).get("umbral_bajo"),
        "umbral_alto": "" if sin_medula else (d.get("umbrales") or {}).get("umbral_alto"),
        "decisiones": "" if sin_medula else m.get("decisiones"),
        "escaladas_sonnet": "" if sin_medula else m.get("escaladas_sonnet"),
        "escaladas_opus": "" if sin_medula else m.get("escaladas_opus"),
        "reservas": "" if sin_medula else m.get("reservas"),
        "avisos_posibles": "" if sin_medula else m.get("avisos_posibles"),
        "avisos_enviados": "" if sin_medula else m.get("avisos_enviados"),
        "avisos_descartados_lectura": "" if sin_medula else m.get("avisos_descartados_lectura"),
        "modelo_agentes": d.get("d61"),
        "tiempo_fiable": True,
        "canal_entre_agentes": "",
    }


def main(ruta: str) -> None:
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    if datos.get("demo"):
        print(f"{datos.get('run_id')}: demo, fuera de summary.csv")
        return
    nueva = fila(datos)
    filas = []
    if CSV.exists():
        with CSV.open(encoding="utf-8", newline="") as f:
            filas = [r for r in csv.DictReader(f) if r.get("run_id") != nueva["run_id"]]
        for r in filas:
            r["tiempo_fiable"] = r.get("tiempo_fiable") or "True"
            r.setdefault("canal_entre_agentes", "")
    filas.append(nueva)
    CSV.parent.mkdir(parents=True, exist_ok=True)
    with CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)


if __name__ == "__main__":
    main(sys.argv[1])
