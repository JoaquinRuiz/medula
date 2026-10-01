"""T4 — GET /reservas?desde=AAAA-MM-DD."""
from conftest import crear


def _sembrar(client, auth):
    for inicio in ("2026-10-05T10:00", "2026-10-06T08:00", "2026-10-08T12:00"):
        assert crear(client, auth, inicio).status_code == 201


def test_filtro_desde(client, auth):
    _sembrar(client, auth)
    r = client.get("/reservas", params={"desde": "2026-10-06"})
    assert r.status_code == 200, r.text
    assert [x["inicio"][:10] for x in r.json()] == ["2026-10-06", "2026-10-08"]


def test_filtro_incluye_el_mismo_dia(client, auth):
    _sembrar(client, auth)
    r = client.get("/reservas", params={"desde": "2026-10-08"})
    assert [x["inicio"][:10] for x in r.json()] == ["2026-10-08"]


def test_filtro_formato_invalido(client):
    assert client.get("/reservas", params={"desde": "06-10-2026"}).status_code == 422


def test_sin_filtro_devuelve_todas(client, auth):
    _sembrar(client, auth)
    assert len(client.get("/reservas").json()) == 3
