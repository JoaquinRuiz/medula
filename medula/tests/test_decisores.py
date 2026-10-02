import pytest

from medula.decisores import ErrorDecisor, cliente, construir
from medula.decisores.jev import Jev
from medula.decisores.locks import Locks

ESTADO = {
    "solicitante": {"agente": "A2", "tarea": "T2", "accion": {"herramienta": "Write", "objetivo": "app/routes_export.py",
                                                              "cambio": "login(u, p)"}},
    "otros_agentes": [{"agente": "A1", "tarea": "T1", "tiene": ["app/auth.py"], "intencion": "login(u, p, otp)"},
                      {"agente": "A3", "tarea": "T3", "tiene": ["app/models.py"], "intencion": "fecha -> inicio"}],
}


def test_jev_una_peticion_con_noul_y_choice(config, fake):
    fake.jev = lambda clave, _: ({"choca_A1": 0.93, "choca_A3": 0.04}.get(clave)
                                 if clave.startswith("choca_") else {"choice": "esperar"})
    c = config()
    lote = Jev(cliente(c), c.modelos["jev"], 5).acquire(ESTADO, ["A1", "A3"])
    assert len(fake.rutas("/systemone")) == 1
    preguntas = fake.llamadas[0]["cuerpo"]["questions"]
    assert preguntas["choca_A1"]["type"] == "noul" and preguntas["remedio_A1"]["type"] == "choice"
    assert lote.veredictos["A1"].p == 0.93 and lote.veredictos["A3"].p == 0.04
    assert lote.veredictos["A1"].remedio == "esperar" and lote.coste_usd == 0.00002


def test_jev_invalida(config, fake):
    fake.jev = lambda clave, _: 0.7 if clave == "invalida_A1" else 0.1
    c = config()
    lote = Jev(cliente(c), c.modelos["jev"], 5).invalida(ESTADO, ["A1", "A3"])
    assert lote.veredictos["A1"].p == 0.7 and lote.veredictos["A3"].p == 0.1


def test_llm_por_agente(config, fake):
    fake.llm = lambda modelo, cuerpo: {"por_agente": {"A1": {"p_choca": 0.9, "remedio": "esperar", "motivo": "firma"},
                                                      "A3": {"p_choca": 0.1, "remedio": "esperar", "motivo": "no"}}}
    c = config(decisor="haiku")
    lote = construir(c, cliente(c)).acquire(ESTADO, ["A1", "A3"])
    assert lote.decisor == "haiku" and lote.veredictos["A1"].p == 0.9 and lote.veredictos["A1"].motivo == "firma"
    rf = fake.llamadas[0]["cuerpo"]["response_format"]
    assert rf["json_schema"]["schema"]["properties"]["por_agente"]["required"] == ["A1", "A3"]


def test_locks():
    lote = Locks().acquire(ESTADO, ["A1", "A3"])
    assert lote.veredictos["A1"].p == 0 and lote.veredictos["A3"].p == 0
    mismo = {**ESTADO, "solicitante": {**ESTADO["solicitante"], "accion": {"herramienta": "Edit",
                                                                          "objetivo": "app/auth.py", "cambio": ""}}}
    assert Locks().acquire(mismo, ["A1", "A3"]).veredictos["A1"].p == 1
    bash = {**ESTADO, "solicitante": {**ESTADO["solicitante"], "accion": {"herramienta": "Bash",
                                                                         "objetivo": "ruff format .", "cambio": ""}}}
    assert all(v.p == 1 for v in Locks().acquire(bash, ["A1", "A3"]).veredictos.values())


def test_reserva_jev_a_haiku(config, fake):
    c = config()
    fake.falla.add(c.modelos["jev"])
    fake.llm = lambda modelo, cuerpo: {"por_agente": {"A1": {"p_choca": 0.9, "remedio": "esperar", "motivo": ""},
                                                      "A3": {"p_choca": 0.1, "remedio": "esperar", "motivo": ""}}}
    lote = construir(c, cliente(c)).acquire(ESTADO, ["A1", "A3"])
    assert lote.decisor == "haiku" and lote.reserva_de == ["jev"]


def test_reserva_hasta_locks_y_por_timeout(config, fake):
    c = config()
    c.timeouts["jev"] = 0.2
    fake.retraso[c.modelos["jev"]] = 0.5
    fake.falla.add(c.modelos["haiku"])
    lote = construir(c, cliente(c)).acquire(ESTADO, ["A1", "A3"])
    assert lote.decisor == "locks" and lote.reserva_de == ["jev", "haiku"]


def test_el_plazo_es_total_aunque_la_respuesta_llegue_a_goteo():
    # Cada trozo llega antes del timeout por operación de httpx, pero la respuesta entera tardaría 2,5 s.
    import time

    import httpx2 as httpx
    from medula.decisores import OpenRouter

    def goteo():
        for _ in range(50):
            time.sleep(0.05)
            yield b" "
        yield b"{}"

    c = OpenRouter("clave", httpx.MockTransport(lambda req: httpx.Response(200, content=goteo())))
    t0 = time.perf_counter()
    with pytest.raises(ErrorDecisor, match="timeout tras 0.5 s"):
        c.post("/chat/completions", {}, 0.5)
    assert time.perf_counter() - t0 < 1.0


def test_jev_respuesta_incompleta(config, fake):
    fake.jev = lambda clave, _: {"choice": "esperar"} if clave.startswith("remedio_") else "no-numero"
    c = config()
    with pytest.raises(ErrorDecisor):
        Jev(cliente(c), c.modelos["jev"], 5).acquire(ESTADO, ["A1"])


def test_jev_direccional_toma_la_mayor(config, fake):
    fake.jev = lambda clave, _: {"usa_A1": 0.8, "cambia_A1": 0.2, "usa_A3": 0.1, "cambia_A3": 0.3}.get(
        clave, {"choice": "esperar"})
    c = config()
    lote = Jev(cliente(c), c.modelos["jev"], 5, "direccional").acquire(ESTADO, ["A1", "A3"])
    preguntas = fake.llamadas[0]["cuerpo"]["questions"]
    assert {"usa_A1", "cambia_A1", "remedio_A1"} <= set(preguntas) and "choca_A1" not in preguntas
    assert lote.veredictos["A1"].p == 0.8 and lote.veredictos["A3"].p == 0.3


def test_jev_compatible(config, fake):
    fake.jev = lambda clave, _: 0.9 if clave == "compatible_A1" else 0.5
    c = config()
    lote = Jev(cliente(c), c.modelos["jev"], 5).compatible(ESTADO, {"A1": {"login"}})
    assert abs(lote.veredictos["A1"].p - 0.1) < 1e-9 and lote.decisor == "regla+jev"
