"""T2 — GET /export en CSV."""
import csv
import io

from conftest import basic, crear, otp

COLUMNAS = ["sala", "inicio", "duracion_min", "id", "usuario"]


def _export(client, usuario="alice", password=None):
    return client.get("/export", auth=basic(usuario, password), headers={"X-OTP": otp(usuario)})


def test_export_csv(client, auth):
    crear(client, auth, "2026-10-05T10:00")
    crear(client, auth, "2026-10-06T11:00", sala="Boreal")
    r = _export(client)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    filas = list(csv.reader(io.StringIO(r.text)))
    assert filas[0] == COLUMNAS
    assert len(filas) == 3
    assert {f[0] for f in filas[1:]} == {"Atlas", "Boreal"}


def test_export_sin_reservas_solo_cabecera(client):
    r = _export(client)
    assert r.status_code == 200
    assert [f for f in csv.reader(io.StringIO(r.text)) if f] == [COLUMNAS]


def test_export_sin_credenciales(client):
    assert client.get("/export").status_code == 401


def test_export_contrasena_incorrecta(client):
    assert _export(client, password="mal").status_code == 401


def test_export_valida_con_login(client, monkeypatch):
    """La validación pasa por app.auth.login, no por una comprobación propia."""
    import app.auth as auth

    llamadas = []
    original = auth.login

    def espia(*args, **kwargs):
        llamadas.append(args[0] if args else kwargs.get("username"))
        return original(*args, **kwargs)

    monkeypatch.setattr(auth, "login", espia)
    import app.routes_export as routes_export

    if hasattr(routes_export, "login"):
        monkeypatch.setattr(routes_export, "login", espia)
    assert _export(client).status_code == 200
    assert llamadas == ["alice"]
