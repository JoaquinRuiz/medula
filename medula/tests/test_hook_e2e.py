"""El script del hook contra un servidor real (uvicorn + curl), sin coste."""
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from medula.servidor import crear_app

from .test_servidor import AUTH, EXPORT, jev_fijo

HOOK = Path(__file__).resolve().parents[1] / "hook" / "medula-hook.sh"


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ejecutar_hook(modo: str, agente: str, url: str, cuerpo: dict, tarea: str = "") -> subprocess.CompletedProcess:
    env = {**os.environ, "MEDULA_URL": url, "MEDULA_AGENTE": agente, "MEDULA_TAREA": tarea}
    return subprocess.run([str(HOOK), modo], input=json.dumps(cuerpo), capture_output=True, text=True, env=env,
                          timeout=30)


@pytest.fixture
def servidor(config):
    arrancados = []

    def arrancar(**kw):
        puerto = puerto_libre()
        app = crear_app(config(**kw))
        srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="error"))
        hilo = threading.Thread(target=srv.run, daemon=True)
        hilo.start()
        for _ in range(100):
            if srv.started:
                break
            time.sleep(0.05)
        arrancados.append(srv)
        return f"http://127.0.0.1:{puerto}", app.state.nucleo

    yield arrancar
    for srv in arrancados:
        srv.should_exit = True


def pre(herramienta, **entrada):
    return {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": herramienta, "tool_input": entrada}


def test_servidor_caido_bloquea_en_pre_y_no_en_post():
    url = f"http://127.0.0.1:{puerto_libre()}"
    r = ejecutar_hook("pre", "A1", url, pre("Edit", **AUTH))
    assert r.returncode == 2 and "Médula no responde" in r.stderr
    assert ejecutar_hook("post", "A1", url, pre("Edit", **AUTH)).returncode == 0


def test_sin_agente_bloquea():
    r = subprocess.run([str(HOOK), "pre"], input="{}", capture_output=True, text=True,
                       env={**os.environ, "MEDULA_URL": "http://x", "MEDULA_AGENTE": ""})
    assert r.returncode == 2


def test_t2_espera_a_t1_y_recibe_el_aviso(servidor, fake):
    """Dos agentes simulados: T2 quiere escribir /export mientras T1 cambia login(); T2 espera a T1."""
    fake.jev = jev_fijo({"A1": 0.95}, p_invalida={"A2": 0.9})
    url, nucleo = servidor(espera_max=10)
    assert ejecutar_hook("pre", "A1", url, pre("Bash", command="ls"), "T1").returncode == 0
    assert ejecutar_hook("pre", "A2", url, pre("Bash", command="ls"), "T2").returncode == 0

    # A1 cambia login(): se concede (A2 aún no choca con nada) y avisa a A2.
    fake.jev = jev_fijo({"A2": 0.05}, p_invalida={"A2": 0.9})
    r = ejecutar_hook("pre", "A1", url, pre("Edit", **AUTH), "T1")
    assert json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "allow"
    ejecutar_hook("post", "A1", url, pre("Edit", **AUTH), "T1")
    for h in nucleo.hilos:
        h.join()

    # A2 quiere escribir /export con login(u, p): espera dentro del hook hasta que A1 termina.
    fake.jev = jev_fijo({"A1": 0.95})
    salida = {}
    hilo = threading.Thread(target=lambda: salida.setdefault("r", ejecutar_hook("pre", "A2", url, pre("Write", **EXPORT), "T2")))
    hilo.start()
    time.sleep(0.6)
    assert nucleo.db.agente("A2")["estado"] == "esperando"
    assert ejecutar_hook("fin", "A1", url, {"hook_event_name": "SessionEnd"}).returncode == 0
    hilo.join()
    r = json.loads(salida["r"].stdout)["hookSpecificOutput"]
    assert r["permissionDecision"] == "allow"
    assert "aviso de A1" in r["additionalContext"]  # el aviso de la interrupción llega con el hook
