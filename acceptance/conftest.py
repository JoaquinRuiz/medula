"""Fixtures de aceptación.

Estos tests se evalúan siempre sobre el estado final, con las seis tareas
aplicadas, así que escriben contra el contrato final: todo lo que autentica
manda OTP y las reservas usan el campo `inicio`.
"""
import time

import pyotp
import pytest
from fastapi.testclient import TestClient

PASSWORDS = {"alice": "alice-pass", "bob": "bob-pass"}
OTP_SECRETS = {"alice": "JBSWY3DPEHPK3PXP", "bob": "KRSXG5CTMVRXEZLU"}


def otp(usuario: str = "alice") -> str:
    return pyotp.TOTP(OTP_SECRETS[usuario]).now()


def otp_invalido(usuario: str = "alice") -> str:
    """Un código que no es válido en la ventana actual (±1 paso)."""
    totp = pyotp.TOTP(OTP_SECRETS[usuario])
    ahora = time.time()
    validos = {totp.at(ahora + d) for d in (-60, -30, 0, 30, 60)}
    return next(c for c in (f"{n:06d}" for n in range(1000000)) if c not in validos)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDULA_DB_PATH", str(tmp_path / "acceptance.db"))
    from app.main import app

    with TestClient(app) as c:
        yield c


def login_token(client, usuario: str = "alice") -> str:
    r = client.post(
        "/login",
        json={"username": usuario, "password": PASSWORDS[usuario], "otp": otp(usuario)},
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def auth(client):
    return {"Authorization": f"Bearer {login_token(client)}"}


def crear(client, auth, inicio: str, sala: str = "Atlas", duracion_min: int = 60):
    return client.post(
        "/reservas",
        json={"sala": sala, "inicio": inicio, "duracion_min": duracion_min},
        headers=auth,
    )


def basic(usuario: str = "alice", password: str | None = None):
    return (usuario, PASSWORDS[usuario] if password is None else password)
