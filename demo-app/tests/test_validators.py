from datetime import datetime

import pytest

from app.validators import ValidationError, validar_horario, validar_sala


def test_sala_valida():
    validar_sala("Boreal")


@pytest.mark.parametrize("sala,mensaje", [("", "sala requerida"), ("Delta", "sala invalida")])
def test_sala_errores(sala, mensaje):
    with pytest.raises(ValidationError, match=f"^{mensaje}$"):
        validar_sala(sala)


def test_horario_valido():
    validar_horario(datetime(2026, 10, 5, 9, 30), 90)


@pytest.mark.parametrize("duracion", [0, -30, 241])
def test_horario_duracion_invalida(duracion):
    with pytest.raises(ValidationError, match="^duracion invalida$"):
        validar_horario(datetime(2026, 10, 5, 9, 0), duracion)


def test_horario_minutos_invalidos():
    with pytest.raises(ValidationError, match="^minutos invalidos$"):
        validar_horario(datetime(2026, 10, 5, 9, 15), 60)
