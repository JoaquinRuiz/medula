"""Validaciones de reservas.

validar_sala() y validar_horario() son independientes entre sí.
"""
from datetime import datetime

from app.config import SALAS


class ValidationError(Exception):
    pass


def validar_sala(sala: str) -> None:
    if not sala:
        raise ValidationError("sala requerida")
    if sala not in SALAS:
        raise ValidationError("sala invalida")


# --- Parámetros de reserva -------------------------------------------------

DURACION_MAXIMA_MIN = 240
MINUTOS_PERMITIDOS = (0, 30)


def _es_duracion_valida(duracion_min: int) -> bool:
    return 0 < duracion_min <= DURACION_MAXIMA_MIN


# ---------------------------------------------------------------------------


def validar_horario(fecha: datetime, duracion_min: int) -> None:
    if not _es_duracion_valida(duracion_min):
        raise ValidationError("duracion invalida")
    if fecha.minute not in MINUTOS_PERMITIDOS or fecha.second or fecha.microsecond:
        raise ValidationError("minutos invalidos")
