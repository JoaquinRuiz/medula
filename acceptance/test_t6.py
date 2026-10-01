"""T6 — franja 8:00-20:00 en validar_horario()."""
from datetime import datetime

import pytest

from conftest import crear

FUERA = "fuera de horario (8:00-20:00)"


@pytest.mark.parametrize("hora,minuto,duracion", [(8, 0, 60), (19, 0, 60), (12, 30, 240)])
def test_dentro_de_franja(hora, minuto, duracion):
    from app.validators import validar_horario

    validar_horario(datetime(2026, 10, 5, hora, minuto), duracion)


@pytest.mark.parametrize("hora,minuto,duracion", [(7, 30, 60), (19, 30, 60), (20, 0, 30), (6, 0, 30)])
def test_fuera_de_franja(hora, minuto, duracion):
    from app.validators import ValidationError, validar_horario

    with pytest.raises(ValidationError) as e:
        validar_horario(datetime(2026, 10, 5, hora, minuto), duracion)
    assert str(e.value) == FUERA


def test_reglas_previas_van_primero():
    from app.validators import ValidationError, validar_horario

    with pytest.raises(ValidationError) as e:
        validar_horario(datetime(2026, 10, 5, 7, 15), 60)
    assert str(e.value) == "minutos invalidos"


def test_franja_en_la_api(client, auth):
    r = crear(client, auth, "2026-10-05T07:00")
    assert r.status_code == 422
    assert r.json()["detail"] == FUERA
