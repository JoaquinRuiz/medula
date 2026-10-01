"""Autenticación: login con usuario y contraseña y sesiones en memoria."""
import secrets
from dataclasses import dataclass

from app.config import USERS


class AuthError(Exception):
    pass


@dataclass
class Session:
    token: str
    username: str


_sessions: dict[str, Session] = {}


def login(username: str, password: str) -> Session:
    """Valida las credenciales y abre una sesión. Lanza AuthError si no son válidas."""
    user = USERS.get(username)
    if user is None or not secrets.compare_digest(user["password"], password):
        raise AuthError("credenciales invalidas")
    session = Session(token=secrets.token_urlsafe(24), username=username)
    _sessions[session.token] = session
    return session


def get_session(token: str) -> Session | None:
    return _sessions.get(token)
