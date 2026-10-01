"""Prioridades desde el grafo de tareas de la spec (plan.yaml).

    tareas:
      T1: {agente: A1, depende_de: []}
      T2: {agente: A2, depende_de: [T1]}   # T2 va después de T1

La cola se ordena por orden topológico, después por la prioridad que ajuste el
camino lento (reordenar) y después por orden de llegada.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def cargar(ruta: Path | None) -> dict:
    if not ruta:
        return {"tareas": {}}
    datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    datos.setdefault("tareas", {})
    return datos


def niveles(plan: dict) -> dict[str, int]:
    """Nivel topológico de cada tarea (0 = sin dependencias). Detecta ciclos."""
    tareas = plan.get("tareas") or {}
    nivel: dict[str, int] = {}
    en_curso: set[str] = set()

    def visitar(t: str) -> int:
        if t in nivel:
            return nivel[t]
        if t in en_curso:
            raise ValueError(f"ciclo en el grafo de tareas en {t}")
        en_curso.add(t)
        deps = (tareas.get(t) or {}).get("depende_de") or []
        nivel[t] = 1 + max((visitar(d) for d in deps), default=-1)
        en_curso.discard(t)
        return nivel[t]

    for t in tareas:
        visitar(t)
    return nivel


def prioridad(plan: dict, tarea: str | None, ajuste: float = 0.0) -> float:
    """Menor = antes. El nivel topológico pesa más que cualquier ajuste del camino lento."""
    return niveles(plan).get(tarea or "", 0) * 1000 + ajuste


def agente_de(plan: dict, tarea: str) -> str | None:
    return ((plan.get("tareas") or {}).get(tarea) or {}).get("agente")
