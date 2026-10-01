"""T1 — segundo factor (OTP) en el login."""
import inspect

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from conftest import otp, otp_invalido


def test_login_con_otp_valido():
    from app.auth import Session, login

    s = login("alice", "alice-pass", otp("alice"))
    assert isinstance(s, Session) and s.username == "alice"


def test_login_con_otp_invalido_o_vacio():
    from app.auth import AuthError, login

    with pytest.raises(AuthError):
        login("alice", "alice-pass", otp_invalido("alice"))
    with pytest.raises(AuthError):
        login("alice", "alice-pass", "")


def test_login_sin_otp_falla():
    from app.auth import AuthError, login

    with pytest.raises((TypeError, AuthError)):
        login("alice", "alice-pass")


def test_otp_es_obligatorio_en_la_firma():
    from app.auth import login

    param = inspect.signature(login).parameters.get("otp")
    assert param is not None
    assert param.default is inspect.Parameter.empty


def test_endpoint_login_exige_otp(client):
    ok = client.post("/login", json={"username": "bob", "password": "bob-pass", "otp": otp("bob")})
    assert ok.status_code == 200 and ok.json()["token"]
    sin = client.post("/login", json={"username": "bob", "password": "bob-pass"})
    assert sin.status_code in (401, 422)
    mal = client.post("/login", json={"username": "bob", "password": "bob-pass", "otp": otp_invalido("bob")})
    assert mal.status_code == 401


def test_otp_header_reutilizable():
    from app.auth import otp_header

    assert "X-OTP" in (otp_header.__doc__ or "")
    app = FastAPI()

    @app.get("/probe")
    def probe(code: str = Depends(otp_header)):
        return {"code": code}

    c = TestClient(app)
    assert c.get("/probe", headers={"X-OTP": "123456"}).json() == {"code": "123456"}


def test_verificador_inyectable(monkeypatch):
    import app.auth as auth

    monkeypatch.setattr(auth, "verificar_otp", lambda username, code: True)
    assert auth.login("alice", "alice-pass", "cualquiera").username == "alice"
