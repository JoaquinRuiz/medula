"""Haiku, Sonnet u Opus por Chat Completions de OpenRouter, con salida estructurada."""
from __future__ import annotations

import json

from .base import GUIA_CHOCA, GUIA_INVALIDA, REMEDIOS, Decisor, ErrorDecisor, Lote, OpenRouter, Veredicto, acotar

SISTEMA = (
    "Eres el decisor de Médula, un kernel que coordina agentes de código que trabajan a la vez sobre el mismo "
    "repositorio. Respondes solo con el objeto JSON que se te pide."
)


class RespuestaCortada(ErrorDecisor):
    """El modelo agotó max_tokens (finish_reason «length») antes de cerrar el JSON."""

    def __init__(self, mensaje: str, latencia: float, coste: float):
        super().__init__(mensaje)
        self.latencia, self.coste = latencia, coste


def _texto(contenido) -> str:
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        return "".join(p.get("text", "") for p in contenido if isinstance(p, dict))
    return ""


def llamar(cliente: OpenRouter, modelo: str, usuario: str, esquema: dict, nombre: str, timeout: float,
           esfuerzo: str | None = None, max_tokens: int = 2048,
           duplicar_tras: float | None = None) -> tuple[dict, float, float, dict]:
    """Una llamada con salida estructurada; si el modelo no la acepta, se pide el JSON en el prompt."""
    def cuerpo(estructurada: bool) -> dict:
        c = {"model": modelo, "max_tokens": max_tokens, "usage": {"include": True},
             "messages": [{"role": "system", "content": SISTEMA}, {"role": "user", "content": usuario}]}
        if esfuerzo:
            c["reasoning"] = {"effort": esfuerzo}
        if estructurada:
            c["response_format"] = {"type": "json_schema", "json_schema": {"name": nombre, "strict": True, "schema": esquema}}
        else:
            c["messages"][1]["content"] += "\n\nResponde solo con un JSON que cumpla este esquema:\n" + json.dumps(esquema)
        return c

    try:
        datos, latencia, coste = cliente.post("/chat/completions", cuerpo(True), timeout, duplicar_tras)
    except ErrorDecisor as e:
        if "HTTP 400" not in str(e):
            raise
        datos, latencia, coste = cliente.post("/chat/completions", cuerpo(False), timeout, duplicar_tras)
    try:
        texto = _texto(datos["choices"][0]["message"].get("content"))
    except (KeyError, IndexError) as e:
        raise ErrorDecisor(f"respuesta sin contenido: {str(datos)[:200]}") from e
    fin = datos["choices"][0].get("finish_reason")
    if fin == "length":
        uso = datos.get("usage") or {}
        raise RespuestaCortada(f"respuesta cortada por max_tokens={max_tokens} (finish_reason=length, "
                               f"{uso.get('completion_tokens', '?')} tokens de salida): {texto[:200]!r}", latencia, coste)
    ini = texto.find("{")
    if ini < 0:
        raise ErrorDecisor(f"respuesta sin JSON: {texto[:200]!r}")
    try:
        # Lee solo el primer objeto completo; el texto posterior puede estar truncado.
        respuesta, _ = json.JSONDecoder().raw_decode(texto[ini:])
        return respuesta, latencia, coste, datos
    except json.JSONDecodeError as e:
        raise ErrorDecisor(f"JSON no válido: {texto[:200]!r}") from e


def _esquema_por_agente(otros: list[str], campos: dict, requeridos: list[str]) -> dict:
    por_agente = {"type": "object", "properties": campos, "required": requeridos, "additionalProperties": False}
    return {
        "type": "object",
        "properties": {"por_agente": {"type": "object", "properties": {x: por_agente for x in otros},
                                      "required": list(otros), "additionalProperties": False}},
        "required": ["por_agente"],
        "additionalProperties": False,
    }


class LLM(Decisor):
    def __init__(self, nombre: str, cliente: OpenRouter, modelo: str, timeout: float, esfuerzo: str | None = None,
                 duplicar_tras: float | None = None):
        self.nombre, self.cliente, self.modelo, self.timeout, self.esfuerzo = nombre, cliente, modelo, timeout, esfuerzo
        self.duplicar_tras = duplicar_tras

    def _lote(self, estado, otros, pregunta, guia, campos, requeridos, clave_p, con_remedio) -> Lote:
        usuario = (
            f"{pregunta}\n\n{guia}\n\nResponde por cada agente de otros_agentes ({', '.join(otros)}).\n\n"
            f"Estado:\n{json.dumps(estado, ensure_ascii=False, indent=2)}"
        )
        esquema = _esquema_por_agente(otros, campos, requeridos)
        datos, latencia, coste, crudo = llamar(self.cliente, self.modelo, usuario, esquema, clave_p, self.timeout,
                                               self.esfuerzo, duplicar_tras=self.duplicar_tras)
        por_agente = datos.get("por_agente") or {}
        veredictos = {}
        for x in otros:
            v = por_agente.get(x)
            if not isinstance(v, dict) or clave_p not in v:
                raise ErrorDecisor(f"falta el veredicto para {x}")
            p = acotar(v[clave_p])
            remedio = v.get("remedio") if con_remedio and v.get("remedio") in REMEDIOS else ("esperar" if con_remedio else None)
            veredictos[x] = Veredicto(p=p, remedio=remedio, confianza=max(p, 1 - p), motivo=v.get("motivo"))
        return Lote(veredictos, self.nombre, self.modelo, latencia, coste, clave_p, crudo)

    def acquire(self, estado: dict, otros: list[str]) -> Lote:
        campos = {"p_choca": {"type": "number"}, "remedio": {"type": "string", "enum": list(REMEDIOS)},
                  "motivo": {"type": "string"}}
        return self._lote(estado, otros, "¿Choca la acción del solicitante con lo que está haciendo cada uno de los "
                          "otros agentes? Da la probabilidad de choque (0 a 1), el remedio si chocase y un motivo breve.",
                          GUIA_CHOCA + "\nRemedios: " + json.dumps(REMEDIOS, ensure_ascii=False),
                          campos, ["p_choca", "remedio", "motivo"], "p_choca", True)

    def invalida(self, estado: dict, otros: list[str]) -> Lote:
        campos = {"p_invalida": {"type": "number"}, "motivo": {"type": "string"}}
        return self._lote(estado, otros, "El solicitante acaba de hacer este cambio. ¿Invalida el plan de cada uno de "
                          "los otros agentes? Da la probabilidad (0 a 1) y un motivo breve.",
                          GUIA_INVALIDA, campos, ["p_invalida", "motivo"], "p_invalida", False)
