"""T5 — mensajes de validar_sala()."""
import pytest

from conftest import crear

DESCONOCIDA = "La sala «Delta» no existe. Salas disponibles: Atlas, Boreal, Cierzo."


def test_sala_vacia():
    from app.validators import ValidationError, validar_sala

    with pytest.raises(ValidationError) as e:
        validar_sala("")
    assert str(e.value) == "La sala es obligatoria."


def test_sala_desconocida():
    from app.validators import ValidationError, validar_sala

    with pytest.raises(ValidationError) as e:
        validar_sala("Delta")
    assert str(e.value) == DESCONOCIDA


def test_mensaje_llega_a_la_api(client, auth):
    r = crear(client, auth, "2026-10-05T10:00", sala="Delta")
    assert r.status_code == 422
    assert r.json()["detail"] == DESCONOCIDA
