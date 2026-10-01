"""Modelos de la API de reservas."""
from datetime import datetime

from pydantic import BaseModel


class ReservaIn(BaseModel):
    sala: str
    fecha: datetime  # inicio de la reserva
    duracion_min: int


class Reserva(ReservaIn):
    id: int
    usuario: str
