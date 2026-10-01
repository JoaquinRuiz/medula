RESERVA = {"sala": "Atlas", "fecha": "2026-10-05T10:00", "duracion_min": 60}


def test_crear_y_listar(client, auth):
    r = client.post("/reservas", json=RESERVA, headers=auth)
    assert r.status_code == 201
    creada = r.json()
    assert creada["usuario"] == "alice" and creada["sala"] == "Atlas"
    assert client.get("/reservas").json() == [creada]


def test_listado_ordenado_por_fecha(client, auth):
    client.post("/reservas", json={**RESERVA, "fecha": "2026-10-07T10:00"}, headers=auth)
    client.post("/reservas", json=RESERVA, headers=auth)
    fechas = [r["fecha"] for r in client.get("/reservas").json()]
    assert fechas == sorted(fechas)


def test_crear_sin_sesion(client):
    assert client.post("/reservas", json=RESERVA).status_code == 401
    assert client.post("/reservas", json=RESERVA, headers={"Authorization": "Bearer x"}).status_code == 401


def test_error_de_validacion_devuelve_422(client, auth):
    r = client.post("/reservas", json={**RESERVA, "sala": "Delta"}, headers=auth)
    assert r.status_code == 422
    assert r.json()["detail"]
