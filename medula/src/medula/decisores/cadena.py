"""Reserva automática: si un decisor falla o tarda demasiado, decide el siguiente de la cadena."""
from __future__ import annotations

from .base import Decisor, ErrorDecisor, Lote


class Cadena(Decisor):
    def __init__(self, decisores: list[Decisor]):
        self.decisores = decisores
        self.nombre = decisores[0].nombre
        self.ultimos_errores: list[str] = []

    def _probar(self, metodo: str, estado: dict, otros: list[str]) -> Lote:
        fallidos, errores = [], []
        for d in self.decisores:
            try:
                lote = getattr(d, metodo)(estado, otros)
            except ErrorDecisor as e:
                fallidos.append(d.nombre)
                errores.append(f"{d.nombre}: {e}")
                continue
            lote.reserva_de = fallidos
            self.ultimos_errores = errores
            return lote
        raise ErrorDecisor("todos los decisores fallaron: " + " | ".join(errores))

    def acquire(self, estado: dict, otros: list[str]) -> Lote:
        return self._probar("acquire", estado, otros)

    def invalida(self, estado: dict, otros: list[str]) -> Lote:
        return self._probar("invalida", estado, otros)
