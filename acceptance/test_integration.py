"""Integración: el sistema con las seis tareas aplicadas a la vez."""
import csv
import io
from datetime import datetime

from conftest import basic, crear, otp, otp_invalido


def test_login_http_exige_otp(client):
    assert client.post("/login", json={"username": "alice", "password": "alice-pass"}).status_code in (401, 422)


def test_export_con_otp_y_campo_renombrado(client, auth):
    crear(client, auth, "2026-10-05T10:00")
    r = client.get("/export", auth=basic(), headers={"X-OTP": otp()})
    assert r.status_code == 200, r.text
    filas = list(csv.reader(io.StringIO(r.text)))
    assert filas[0] == ["sala", "inicio", "duracion_min", "id", "usuario"]
    # T2.md no fija el formato de la fecha: vale ISO con "T" o con espacio.
    assert datetime.fromisoformat(filas[1][1]) == datetime(2026, 10, 5, 10, 0)


def test_export_exige_segundo_factor(client):
    assert client.get("/export", auth=basic()).status_code == 401
    assert client.get("/export", auth=basic(), headers={"X-OTP": otp_invalido()}).status_code == 401


def test_filtro_sobre_campo_renombrado(client, auth):
    for inicio in ("2026-10-05T10:00", "2026-10-09T09:00"):
        assert crear(client, auth, inicio).status_code == 201
    r = client.get("/reservas", params={"desde": "2026-10-07"})
    assert r.status_code == 200, r.text
    lista = r.json()
    assert len(lista) == 1
    assert lista[0]["inicio"].startswith("2026-10-09") and "fecha" not in lista[0]


def test_validaciones_conviven(client, auth):
    sala = crear(client, auth, "2026-10-05T07:00", sala="Delta")
    assert sala.status_code == 422
    assert sala.json()["detail"].startswith("La sala «Delta» no existe.")
    horario = crear(client, auth, "2026-10-05T07:00")
    assert horario.json()["detail"] == "fuera de horario (8:00-20:00)"
    assert crear(client, auth, "2026-10-05T10:00").status_code == 201
