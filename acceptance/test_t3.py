"""T3 — renombrar fecha a inicio."""
import os
import sqlite3

from conftest import crear


def test_crear_con_inicio(client, auth):
    r = crear(client, auth, "2026-10-05T10:00")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["inicio"].startswith("2026-10-05T10:00")
    assert "fecha" not in body


def test_listado_con_inicio_ordenado(client, auth):
    crear(client, auth, "2026-10-07T10:00")
    crear(client, auth, "2026-10-05T10:00")
    lista = client.get("/reservas").json()
    assert all("inicio" in r and "fecha" not in r for r in lista)
    assert [r["inicio"] for r in lista] == sorted(r["inicio"] for r in lista)
    assert len(lista) == 2


def test_fecha_ya_no_se_acepta(client, auth):
    r = client.post(
        "/reservas",
        json={"sala": "Atlas", "fecha": "2026-10-05T10:00", "duracion_min": 60},
        headers=auth,
    )
    assert r.status_code == 422


def test_columna_renombrada(client):
    with sqlite3.connect(os.environ["MEDULA_DB_PATH"]) as conn:
        columnas = {fila[1] for fila in conn.execute("PRAGMA table_info(reservas)")}
    assert "inicio" in columnas and "fecha" not in columnas
