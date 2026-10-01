"""Consulta pública de reservas."""
from fastapi import APIRouter

from app import db
from app.models import Reserva

router = APIRouter()


@router.get("/reservas")
def listar_reservas() -> list[Reserva]:
    return db.listar_reservas()
