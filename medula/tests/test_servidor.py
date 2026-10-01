import threading
import time

import pytest

from medula import plan
from medula.servidor import Nucleo

from .conftest import hook, permitido

EXPORT = dict(file_path="app/routes_export.py", content="session = login(username, password)\n")
AUTH = dict(file_path="app/auth.py", old_string="def login(u, p)", new_string="def login(u, p, otp)")


def jev_fijo(p_choca: dict, remedio="esperar", p_invalida: dict | None = None):
    def politica(clave, cuerpo):
        if clave.startswith("choca_"):
            return p_choca.get(clave[6:], 0.05)
        if clave.startswith("invalida_"):
            return (p_invalida or {}).get(clave[9:], 0.05)
        return {"choice": remedio}
    return politica


@pytest.fixture
def nucleo(config):
    def hacer(**kw):
        n = Nucleo(config(**kw))
        n.asegurar("A1", "T1")
        n.asegurar("A2", "T2")
        return n
    return hacer


def test_lectura_se_concede_sin_decisor(nucleo, fake):
    n = nucleo()
    assert permitido(n.acquire("A2", "T2", hook("Bash", command="uv run pytest -q")))
    assert fake.llamadas == []
    assert n.db.decisiones()[0]["decisor"] == "regla"


def test_sin_otros_agentes(config, fake):
    n = Nucleo(config())
    assert permitido(n.acquire("A1", "T1", hook("Edit", **AUTH)))
    assert fake.llamadas == []


def test_p_baja_concede_y_anota_lock(nucleo, fake):
    fake.jev = jev_fijo({"A1": 0.05})
    n = nucleo()
    assert permitido(n.acquire("A2", "T2", hook("Write", **EXPORT)))
    lk = n.db.locks("A2")[0]
    assert lk["recurso"] == "app/routes_export.py" and lk["intencion"]["tarea"] == "T2"
    d = n.db.decisiones()[0]
    assert d["decisor"] == "jev" and d["veredicto"] == "conceder" and d["p_choca"] == 0.05 and d["coste_usd"] > 0


def test_p_alta_espera_hasta_que_termina_el_otro(nucleo, fake):
    fake.jev = jev_fijo({"A1": 0.95})
    n = nucleo(espera_max=5)
    assert permitido(n.acquire("A1", "T1", hook("Edit", **AUTH)))  # A1 no tiene a nadie delante... salvo A2
    threading.Timer(0.4, n.release, args=("A1",)).start()
    t0 = time.monotonic()
    r = n.acquire("A2", "T2", hook("Write", **EXPORT))
    assert permitido(r) and 0.3 < time.monotonic() - t0 < 4
    cola = n.db.cola(solo_esperando=False)
    assert cola[-1]["agente"] == "A2" and cola[-1]["espera_a"] == "A1" and cola[-1]["estado"] == "concedido"
    veredictos = [d["veredicto"] for d in reversed(n.db.decisiones())]
    assert "esperar" in veredictos and veredictos[-1] == "conceder"


def test_espera_caduca_con_motivo_y_aviso_al_terminar(nucleo, fake):
    fake.jev = jev_fijo({"A1": 0.95})
    n = nucleo(espera_max=0.3)
    n.db.anadir_lock("A1", "app/auth.py", {"tarea": "T1", "herramienta": "Edit", "objetivo": "app/auth.py",
                                           "cambio": "login(u, p, otp)"})
    r = n.acquire("A2", "T2", hook("Write", **EXPORT))
    motivo = r["hookSpecificOutput"]["permissionDecisionReason"]
    assert r["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "A1" in motivo and "Segundo factor" in motivo and "app/auth.py" in motivo and "0.95" in motivo
    assert n.db.agente("A2")["estado"] == "trabajando"
    n.release("A1")
    r = n.acquire("A2", "T2", hook("Bash", command="ls"))
    assert "A1 ha terminado" in r["hookSpecificOutput"]["additionalContext"]


def test_camino_lento_sonnet_no_resuelve_y_opus_concede(nucleo, fake, config):
    fake.jev = jev_fijo({"A1": 0.5})
    c = config()
    fake.llm = lambda modelo, cuerpo: (
        {"resuelto": False, "salida": "esperar", "esperar_a": None, "primero": None, "instrucciones": "", "motivo": "no sé"}
        if modelo == c.modelos["sonnet"] else
        {"resuelto": True, "salida": "conceder", "esperar_a": None, "primero": None, "instrucciones": "", "motivo": "falso"})
    n = nucleo()
    assert permitido(n.acquire("A2", "T2", hook("Write", **EXPORT)))
    lentos = [d for d in n.db.decisiones() if d["tipo"] == "lento"]
    assert sorted(d["decisor"] for d in lentos) == ["opus", "sonnet"]


def _es_verificacion(cuerpo):
    return (cuerpo.get("response_format") or {}).get("json_schema", {}).get("name") == "verificacion"


def test_camino_lento_por_replanificar_y_reescribir(nucleo, fake):
    fake.jev = jev_fijo({"A1": 0.95}, remedio="replanificar")
    fake.llm = lambda modelo, cuerpo: (
        {"incumple": False, "criterio": "", "motivo": ""} if _es_verificacion(cuerpo) else
        {"resuelto": True, "salida": "reescribir", "esperar_a": None, "primero": None,
         "instrucciones": "Llama a login con el OTP de la cabecera X-OTP.", "respeta_criterios": True,
         "criterios_en_riesgo": "", "motivo": ""})
    n = nucleo()
    r = n.acquire("A2", "T2", hook("Write", **EXPORT))
    assert r["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "X-OTP" in r["hookSpecificOutput"]["permissionDecisionReason"]


def test_camino_lento_falla_entero_y_se_espera(nucleo, fake, config):
    fake.jev = jev_fijo({"A1": 0.5})
    c = config()
    fake.falla |= {c.modelos["sonnet"], c.modelos["opus"]}
    n = nucleo(espera_max=0.2)
    r = n.acquire("A2", "T2", hook("Write", **EXPORT))
    assert r["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "camino lento" in r["hookSpecificOutput"]["permissionDecisionReason"]


def test_interrupciones_una_peticion_y_buzon(nucleo, fake):
    n = nucleo()
    n.asegurar("A3", "T3")
    fake.jev = jev_fijo({}, p_invalida={"A2": 0.9, "A3": 0.1})
    n.notify("A1", "T1", hook("Edit", **AUTH), sincrono=True)
    invalida = [c for c in fake.rutas("/systemone") if any(k.startswith("invalida_") for k in c["cuerpo"]["questions"])]
    assert len(invalida) == 1 and set(invalida[0]["cuerpo"]["questions"]) == {"invalida_A2", "invalida_A3"}
    buzon = n.db.buzon()
    assert [b["para"] for b in buzon] == ["A2"] and "login" in buzon[0]["texto"]
    r = n.notify("A2", "T2", hook("Bash", command="ls"))
    assert "aviso de A1" in r["hookSpecificOutput"]["additionalContext"]
    assert n.notify("A2", "T2", hook("Bash", command="ls")) == {}


def test_bash_que_escribe_lock_transitorio(nucleo, fake):
    n = nucleo(decisor="locks")
    assert permitido(n.acquire("A1", "T1", hook("Bash", command="uv run ruff format .")))
    assert n.db.locks("A1")[0]["recurso"] == "repo"
    n.notify("A1", "T1", hook("Bash", command="uv run ruff format ."))
    assert n.db.locks("A1") == []


def test_modo_locks(nucleo, fake):
    n = nucleo(decisor="locks", espera_max=0.2)
    assert permitido(n.acquire("A1", "T1", hook("Edit", **AUTH)))
    assert permitido(n.acquire("A2", "T2", hook("Write", **EXPORT)))  # distinto fichero: el lock no ve el choque
    r = n.acquire("A2", "T2", hook("Edit", **AUTH))
    assert r["hookSpecificOutput"]["permissionDecision"] == "deny"
    n.notify("A1", "T1", hook("Edit", **AUTH), sincrono=True)
    assert n.db.buzon() == [] and fake.llamadas == []


def test_espera_cruzada_no_bloquea(nucleo, fake):
    fake.jev = jev_fijo({"A1": 0.95, "A2": 0.95})
    n = nucleo(espera_max=3)
    resultados = {}
    hilo = threading.Thread(target=lambda: resultados.setdefault("A2", n.acquire("A2", "T2", hook("Write", **EXPORT))))
    hilo.start()
    time.sleep(0.3)
    t0 = time.monotonic()
    resultados["A1"] = n.acquire("A1", "T1", hook("Edit", **AUTH))
    assert permitido(resultados["A1"]) and time.monotonic() - t0 < 1
    n.release("A1")
    hilo.join()
    assert permitido(resultados["A2"])


def test_prioridad_desde_el_grafo():
    p = {"tareas": {"T1": {"depende_de": []}, "T2": {"depende_de": ["T1"]}, "T3": {"depende_de": ["T2"]}}}
    assert plan.niveles(p) == {"T1": 0, "T2": 1, "T3": 2}
    assert plan.prioridad(p, "T1") < plan.prioridad(p, "T2", ajuste=-5)
    with pytest.raises(ValueError):
        plan.niveles({"tareas": {"T1": {"depende_de": ["T2"]}, "T2": {"depende_de": ["T1"]}}})


def test_varios_esperan_y_pasan_por_prioridad(config, fake):
    fake.jev = jev_fijo({"A1": 0.95})
    grafo = {"tareas": {"T1": {}, "T2": {"depende_de": []}, "T4": {"depende_de": ["T2"]}}}
    n = Nucleo(config(plan=grafo, espera_max=5))
    for a, t in (("A1", "T1"), ("A2", "T2"), ("A4", "T4")):
        n.asegurar(a, t)
    orden = []

    def pedir(a, t):
        n.acquire(a, t, hook("Write", file_path=f"app/{a}.py", content="x"))
        orden.append(a)

    hilos = [threading.Thread(target=pedir, args=("A4", "T4")), threading.Thread(target=pedir, args=("A2", "T2"))]
    hilos[0].start()
    time.sleep(0.2)
    hilos[1].start()
    time.sleep(0.3)
    fake.jev = jev_fijo({"A1": 0.95, "A2": 0.05, "A4": 0.05})
    n.release("A1")
    for h in hilos:
        h.join()
    assert orden == ["A2", "A4"]


def test_aviso_de_write_lleva_el_diff_de_antes_de_escribir(nucleo, fake, config):
    n = nucleo()
    ruta = n.config.raiz / "app" / "models.py"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("fecha: datetime\n")
    fake.jev = jev_fijo({}, p_invalida={"A2": 0.9})
    cuerpo = {**hook("Write", file_path=str(ruta), content="inicio: datetime\n"), "tool_use_id": "t1"}
    assert permitido(n.acquire("A1", "T1", cuerpo))
    ruta.write_text("inicio: datetime\n")  # la herramienta escribe
    n.notify("A1", "T1", cuerpo, sincrono=True)
    texto = n.db.buzon()[0]["texto"]
    assert "-fecha: datetime" in texto and "+inicio: datetime" in texto


def test_regla_de_simbolos_y_compatibilidad(nucleo, fake):
    n = nucleo(regla_simbolos=True)
    n.db.anadir_lock("A1", "app/auth.py", {"tarea": "T1", "herramienta": "Edit", "objetivo": "app/auth.py",
                                           "cambio": "- def login(u, p)\n+ def login(u, p, otp)"})
    fake.jev = lambda clave, _: 0.05 if clave == "compatible_A1" else {"choice": "esperar"}  # incompatible
    r = n.acquire("A2", "T2", hook("Write", **EXPORT))
    assert r["hookSpecificOutput"]["permissionDecision"] == "deny"
    tipos = [(d["tipo"], d["decisor"]) for d in reversed(n.db.decisiones())]
    assert ("regla", "regla_simbolos") in tipos and ("acquire", "regla+jev") in tipos
    assert not any(c["cuerpo"]["questions"].get("choca_A1") for c in fake.rutas("/systemone"))



def test_camino_lento_rechaza_reescribir_que_incumple_la_spec(nucleo, fake, config):
    """El caso real: rebajar otp a opcional para no romper /export incumple el criterio 3 de T1."""
    fake.jev = jev_fijo({"A2": 0.5})
    c = config()
    prompts = []

    def llm(modelo, cuerpo):
        prompts.append(cuerpo["messages"][1]["content"])
        if _es_verificacion(cuerpo):
            return {"incumple": True, "criterio": "T1 criterio 3: otp obligatorio", "motivo": "lo hace opcional"}
        if modelo == c.modelos["sonnet"]:
            return {"resuelto": True, "salida": "reescribir", "esperar_a": None, "primero": None,
                    "instrucciones": "Define login(username, password, otp=None) para no romper /export.",
                    "respeta_criterios": True, "criterios_en_riesgo": "", "motivo": ""}
        return {"resuelto": True, "salida": "esperar", "esperar_a": "A2", "primero": None, "instrucciones": "",
                "respeta_criterios": True, "criterios_en_riesgo": "", "motivo": "esperar a que A2 termine"}
    fake.llm = llm
    n = nucleo(espera_max=0.2)
    r = n.acquire("A1", "T1", hook("Edit", **AUTH))
    assert r["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "otp=None" not in r["hookSpecificOutput"]["permissionDecisionReason"]
    assert "Criterios de aceptación" in prompts[0] and "el parámetro es obligatorio" in prompts[0]
    lentos = {(d["decisor"], d["pregunta"], d["veredicto"]) for d in n.db.decisiones() if d["tipo"] == "lento"}
    assert ("sonnet", "salida", "rechazada:reescribir") in lentos
    assert ("sonnet", "verificacion", "verificacion:incumple") in lentos
    assert ("opus", "salida", "esperar") in lentos


def test_camino_lento_rechaza_lo_que_el_modelo_declara_que_incumple(nucleo, fake, config):
    fake.jev = jev_fijo({"A1": 0.5})
    c = config()
    fake.llm = lambda modelo, cuerpo: (
        {"resuelto": True, "salida": "conceder", "esperar_a": None, "primero": None, "instrucciones": "",
         "respeta_criterios": False, "criterios_en_riesgo": "T2 criterio 1", "motivo": ""}
        if modelo == c.modelos["sonnet"] else
        {"resuelto": True, "salida": "conceder", "esperar_a": None, "primero": None, "instrucciones": "",
         "respeta_criterios": True, "criterios_en_riesgo": "", "motivo": ""})
    n = nucleo()
    assert permitido(n.acquire("A2", "T2", hook("Write", **EXPORT)))
    assert any(d["veredicto"] == "rechazada:conceder" for d in n.db.decisiones())
