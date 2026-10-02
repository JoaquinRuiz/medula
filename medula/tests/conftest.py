"""OpenRouter simulado y utilidades comunes para los tests de Médula."""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx2 as httpx
import pytest

from medula.config import Config

TAREAS = Path(__file__).resolve().parents[2] / "tasks"


class FakeOpenRouter:
    """Responde como OpenRouter. Las políticas se pueden cambiar en cada test.

    - jev(clave, cuerpo) -> float | dict: valor noul, o {"choice": ...} para preguntas choice.
    - llm(modelo, cuerpo) -> dict | str | (str, finish_reason): el JSON o el texto crudo que devuelve el modelo,
      con finish_reason «stop» salvo que se indique otro (p. ej. «length»).
    - falla: modelos que responden 500; lento: segundos de retraso por modelo.
    """

    def __init__(self):
        self.jev = lambda clave, cuerpo: 0.05 if clave.startswith(("choca_", "invalida_")) else {"choice": "esperar"}
        self.llm = lambda modelo, cuerpo: {}
        self.falla: set[str] = set()
        self.retraso: dict[str, float] = {}
        self.llamadas: list[dict] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        cuerpo = json.loads(req.content)
        modelo = cuerpo.get("model", "")
        self.llamadas.append({"ruta": req.url.path, "modelo": modelo, "cuerpo": cuerpo})
        if self.retraso.get(modelo):
            time.sleep(self.retraso[modelo])
        if modelo in self.falla:
            return httpx.Response(500, json={"error": "simulado"})
        if req.url.path.endswith("/systemone"):
            respuestas = {}
            for clave, pregunta in cuerpo["questions"].items():
                r = self.jev(clave, cuerpo)
                if pregunta["type"] == "noul":
                    respuestas[clave] = {"type": "noul", "noul": r}
                else:
                    respuestas[clave] = {"type": "choice", "confidence": 0.9, **r}
            return httpx.Response(200, json={"id": "gen-jev", "model": modelo, "answers": respuestas,
                                             "usage": {"input_tokens": 300, "output_tokens": 10, "cost": 0.00002}})
        respuesta, fin = self.llm(modelo, cuerpo), "stop"
        if isinstance(respuesta, tuple):
            respuesta, fin = respuesta
        contenido = respuesta if isinstance(respuesta, str) else json.dumps(respuesta)
        return httpx.Response(200, json={"id": "gen-llm", "model": modelo,
                                         "choices": [{"message": {"content": contenido}, "finish_reason": fin}],
                                         "usage": {"cost": 0.003}})

    def rutas(self, sufijo: str) -> list[dict]:
        return [c for c in self.llamadas if c["ruta"].endswith(sufijo)]


@pytest.fixture
def fake():
    return FakeOpenRouter()


@pytest.fixture
def config(tmp_path, fake):
    def hacer(**kw) -> Config:
        base = dict(db=tmp_path / "medula.db", decisor="jev", raiz=tmp_path / "ws", tareas_dir=TAREAS,
                    espera_max=2.0, openrouter_key="sk-test", transport=httpx.MockTransport(fake))
        base.update(kw)
        (tmp_path / "ws").mkdir(exist_ok=True)
        return Config(**base)
    return hacer


def hook(herramienta: str, **entrada) -> dict:
    """Cuerpo de un hook PreToolUse/PostToolUse como el que manda Claude Code."""
    return {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": herramienta, "tool_input": entrada,
            "cwd": "/ws"}


def permitido(r: dict) -> bool:
    return r["hookSpecificOutput"]["permissionDecision"] == "allow"
