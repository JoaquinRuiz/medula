import pytest

from app.auth import AuthError, get_session, login


def test_login_correcto_abre_sesion():
    s = login("alice", "alice-pass")
    assert s.username == "alice"
    assert get_session(s.token) == s


def test_login_incorrecto():
    with pytest.raises(AuthError):
        login("alice", "mal")
    with pytest.raises(AuthError):
        login("nadie", "alice-pass")


def test_endpoint_login(client):
    assert client.post("/login", json={"username": "bob", "password": "bob-pass"}).status_code == 200
    assert client.post("/login", json={"username": "bob", "password": "x"}).status_code == 401
