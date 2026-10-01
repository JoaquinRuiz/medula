from fastapi import APIRouter, Depends, Header, HTTPException

from app import db
from app.auth import Session, get_session
from app.models import Reserva, ReservaIn
from app.validators import ValidationError, validar_horario, validar_sala

router = APIRouter()


def sesion_actual(authorization: str | None = Header(default=None)) -> Session:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="no autenticado")
    session = get_session(authorization.removeprefix("Bearer "))
    if session is None:
        raise HTTPException(status_code=401, detail="sesion invalida")
    return session


@router.post("/reservas", status_code=201)
def crear_reserva(r: ReservaIn, session: Session = Depends(sesion_actual)) -> Reserva:
    try:
        validar_sala(r.sala)
        validar_horario(r.fecha, r.duracion_min)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return db.insertar_reserva(r, session.username)
