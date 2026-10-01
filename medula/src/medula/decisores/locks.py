"""Lock clásico por fichero: choca si otro agente tiene el mismo recurso (o 'repo')."""
from __future__ import annotations

import time

from .base import Decisor, Lote, Veredicto


class Locks(Decisor):
    nombre = "locks"
    modelo = None

    def acquire(self, estado: dict, otros: list[str]) -> Lote:
        t0 = time.perf_counter()
        accion = estado["solicitante"]["accion"]
        mio = "repo" if accion["herramienta"] == "Bash" else accion["objetivo"]
        tienen = {o["agente"]: set(o.get("tiene") or []) for o in estado["otros_agentes"]}
        veredictos = {}
        for x in otros:
            suyos = tienen.get(x, set())
            choca = bool(suyos) and (mio == "repo" or mio in suyos or "repo" in suyos)
            veredictos[x] = Veredicto(p=1.0 if choca else 0.0, remedio="esperar", confianza=1.0)
        return Lote(veredictos, self.nombre, None, (time.perf_counter() - t0) * 1000, 0.0, "lock")

    def invalida(self, estado: dict, otros: list[str]) -> Lote:
        return Lote({x: Veredicto(p=0.0) for x in otros}, self.nombre, None, 0.0, 0.0, "invalida")
