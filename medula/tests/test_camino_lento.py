import json

import pytest

from medula.camino_lento import resolver
from medula.decisores import cliente

ESTADO = {"solicitante": {"agente": "A2"}, "otros_agentes": [{"agente": "A1"}]}
PROPUESTA = {
    "resuelto": True, "salida": "conceder", "esperar_a": None, "primero": None,
    "instrucciones": "", "respeta_criterios": True, "criterios_en_riesgo": "",
    "motivo": 'Sin choque; texto con llaves { y } y una cita "escapada".',
}


@pytest.mark.parametrize("prefijo,sufijo", [
    ("", ""),
    ("```json\n", "\n```"),
    ("", '\nTexto sobrante {"cortado":'),
    ("", '\nTexto sobrante {"anidado": {}, "cortado":'),
    ("", '\n{"resuelto": false}'),
])
def test_camino_lento_lee_el_primer_objeto_json(config, fake, prefijo, sufijo):
    fake.llm = lambda modelo, cuerpo: prefijo + json.dumps(PROPUESTA) + sufijo
    c = config()
    salida = resolver(cliente(c), c, ESTADO, {"A1": 0.5}, "A1")
    assert salida.salida == "conceder"
    assert salida.motivo == PROPUESTA["motivo"]
    assert len(salida.pasos) == 1
    assert salida.pasos[0]["respuesta"] == PROPUESTA
    assert [p["modelo"] for p in fake.rutas("/chat/completions")] == [c.modelos["sonnet"]]


@pytest.mark.parametrize("texto", [
    "Sin JSON", '{"resuelto": true, "salida": "conceder"',
    '{"motivo": "sin terminar}',
    '{"resuelto": tru} ' + json.dumps(PROPUESTA),
])
def test_camino_lento_json_invalido_sigue_la_reserva(config, fake, texto):
    c = config()
    fake.llm = lambda modelo, cuerpo: texto if modelo == c.modelos["sonnet"] else PROPUESTA
    salida = resolver(cliente(c), c, ESTADO, {"A1": 0.5}, "A1")
    assert salida.salida == "conceder"
    assert len(salida.pasos) == 2
    assert "error" in salida.pasos[0]
    assert salida.pasos[1]["decisor"] == "opus"


def test_respuesta_cortada_reintenta_con_mas_tokens(config, fake):
    c = config()
    cortada = (json.dumps(PROPUESTA)[:60], "length")
    fake.llm = lambda modelo, cuerpo: cortada if cuerpo["max_tokens"] < 4096 else PROPUESTA
    salida = resolver(cliente(c), c, ESTADO, {"A1": 0.5}, "A1")
    assert salida.salida == "conceder"
    llamadas = fake.rutas("/chat/completions")
    assert [(x["modelo"], x["cuerpo"]["max_tokens"]) for x in llamadas] == [(c.modelos["sonnet"], 2048),
                                                                        (c.modelos["sonnet"], 4096)]
    assert [p.get("finish_reason") for p in salida.pasos] == ["length", "stop"]
    assert "cortada por max_tokens=2048" in salida.pasos[0]["error"]
    assert salida.pasos[0]["coste_usd"] == salida.pasos[1]["coste_usd"] == 0.003


def test_respuesta_cortada_dos_veces_escala_a_opus(config, fake):
    c = config()
    fake.llm = lambda modelo, cuerpo: (json.dumps(PROPUESTA)[:60], "length") if modelo == c.modelos["sonnet"] \
        else PROPUESTA
    salida = resolver(cliente(c), c, ESTADO, {"A1": 0.5}, "A1")
    assert salida.salida == "conceder"
    assert [(p["decisor"], "error" in p) for p in salida.pasos] == [("sonnet", True), ("sonnet", True),
                                                                   ("opus", False)]
    assert "max_tokens=4096" in salida.pasos[1]["error"]
