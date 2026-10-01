"""Camino lento: cuando la probabilidad de choque es dudosa o el remedio es replanificar,
Sonnet propone la salida; si no lo resuelve, Opus; si tampoco, se espera (lo seguro).

Ninguna propuesta puede contradecir la spec: el prompt lleva los criterios de aceptación de las
tareas implicadas, el modelo declara si su propuesta los respeta, y las propuestas «reescribir»
(las únicas que cambian lo que un agente escribe) pasan además una verificación independiente.
Una propuesta que los incumple se rechaza como si no hubiera resuelto."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .config import Config
from .decisores.base import GUIA_CHOCA, ErrorDecisor, OpenRouter
from .decisores.llm import llamar

SALIDAS = ("conceder", "esperar", "reordenar", "reescribir")
ESQUEMA = {
    "type": "object",
    "properties": {
        "resuelto": {"type": "boolean"},
        "salida": {"type": "string", "enum": list(SALIDAS)},
        "esperar_a": {"type": ["string", "null"]},
        "primero": {"type": ["string", "null"]},
        "instrucciones": {"type": "string"},
        "respeta_criterios": {"type": "boolean"},
        "criterios_en_riesgo": {"type": "string"},
        "motivo": {"type": "string"},
    },
    "required": ["resuelto", "salida", "esperar_a", "primero", "instrucciones", "respeta_criterios",
                 "criterios_en_riesgo", "motivo"],
    "additionalProperties": False,
}
ESQUEMA_VERIFICACION = {
    "type": "object",
    "properties": {"incumple": {"type": "boolean"}, "criterio": {"type": "string"}, "motivo": {"type": "string"}},
    "required": ["incumple", "criterio", "motivo"],
    "additionalProperties": False,
}


@dataclass
class Salida:
    salida: str
    esperar_a: str | None = None
    primero: str | None = None
    instrucciones: str = ""
    motivo: str = ""
    pasos: list[dict] = field(default_factory=list)  # un registro por llamada (propuestas y verificaciones)


def _bloque_criterios(criterios: dict[str, str]) -> str:
    if not criterios:
        return ""
    partes = [f"### {quien}\n{texto}" for quien, texto in criterios.items() if texto]
    return ("Criterios de aceptación de las tareas implicadas. Ninguna propuesta puede hacer que una tarea los "
            "incumpla (por ejemplo, relajar una firma o un campo que un criterio exige). Si la única forma de "
            "evitar el choque es incumplir alguno, responde «esperar».\n\n" + "\n\n".join(partes) + "\n\n")


def _prompt(estado: dict, veredictos: dict, criterios: dict[str, str]) -> str:
    return (
        "Un decisor rápido no ha podido resolver con seguridad si la acción del solicitante choca con el trabajo "
        "de otros agentes, o cree que hace falta replanificar. Propón la salida:\n"
        "- conceder: no hay choque real; el solicitante puede seguir.\n"
        "- esperar: el solicitante debe esperar a que termine un agente (esperar_a) y adaptarse después.\n"
        "- reordenar: cambia quién va primero (primero = el agente que debe ir antes).\n"
        "- reescribir: el solicitante debe hacer su acción de otra forma; da instrucciones concretas.\n"
        "Indica en respeta_criterios si tu propuesta respeta todos los criterios de aceptación y, si alguno "
        "queda en riesgo, cuál. Si no puedes resolverlo con lo que sabes, responde resuelto=false.\n\n"
        f"{GUIA_CHOCA}\n\n"
        f"{_bloque_criterios(criterios)}"
        f"Veredictos del decisor rápido (probabilidad de choque por agente):\n"
        f"{json.dumps(veredictos, ensure_ascii=False)}\n\n"
        f"Estado:\n{json.dumps(estado, ensure_ascii=False, indent=2)}"
    )


def _verificar(cliente: OpenRouter, config: Config, instrucciones: str, solicitante: str,
               criterios: dict[str, str]) -> dict:
    """Verificación independiente de una propuesta «reescribir» frente a los criterios de aceptación."""
    usuario = (
        f"Un coordinador propone que el agente {solicitante} cambie su trabajo siguiendo estas instrucciones:\n"
        f"«{instrucciones}»\n\n"
        "¿Haría eso que alguna de las tareas incumpla alguno de sus criterios de aceptación? Sé estricto: "
        "cualquier relajación de lo que un criterio exige cuenta como incumplimiento.\n\n"
        f"{_bloque_criterios(criterios)}"
    )
    datos, latencia, coste, _ = llamar(cliente, config.modelos["sonnet"], usuario, ESQUEMA_VERIFICACION,
                                       "verificacion", config.timeouts["sonnet"], config.esfuerzo_sonnet)
    return {"decisor": "sonnet", "modelo": config.modelos["sonnet"], "verificacion": True, "latencia_ms": latencia,
            "coste_usd": coste, "respuesta": datos}


def resolver(cliente: OpenRouter, config: Config, estado: dict, veredictos: dict[str, float],
             por_defecto_esperar_a: str, criterios: dict[str, str] | None = None) -> Salida:
    criterios = criterios or {}
    otros = {o["agente"] for o in estado.get("otros_agentes", [])}
    solicitante = estado["solicitante"]["agente"]
    usuario = _prompt(estado, veredictos, criterios)
    pasos = []
    for nombre, esfuerzo in (("sonnet", config.esfuerzo_sonnet), ("opus", None)):
        modelo = config.modelos[nombre]
        paso = {"decisor": nombre, "modelo": modelo}
        try:
            datos, latencia, coste, crudo = llamar(cliente, modelo, usuario, ESQUEMA, "salida",
                                                   config.timeouts[nombre], esfuerzo)
            paso.update(latencia_ms=latencia, coste_usd=coste, respuesta=datos)
        except ErrorDecisor as e:
            paso.update(error=str(e))
            pasos.append(paso)
            continue
        pasos.append(paso)
        salida = datos.get("salida")
        valido = datos.get("resuelto") and salida in SALIDAS
        if salida == "esperar" and datos.get("esperar_a") not in otros:
            valido = False
        if salida == "reordenar" and datos.get("primero") not in otros | {solicitante}:
            valido = False
        if valido and salida != "esperar" and datos.get("respeta_criterios") is False:
            paso["rechazo"] = f"incumple criterios: {datos.get('criterios_en_riesgo')}"
            valido = False
        if valido and salida == "reescribir" and criterios:
            try:
                v = _verificar(cliente, config, datos.get("instrucciones") or "", solicitante, criterios)
                pasos.append(v)
                if v["respuesta"].get("incumple") is not False:
                    paso["rechazo"] = f"la verificación lo rechaza: {v['respuesta'].get('criterio')}"
                    valido = False
            except ErrorDecisor as e:
                pasos.append({"decisor": "sonnet", "modelo": config.modelos["sonnet"], "verificacion": True,
                              "error": str(e)})
                paso["rechazo"] = "verificación fallida"
                valido = False
        if valido:
            return Salida(salida, datos.get("esperar_a"), datos.get("primero"), datos.get("instrucciones") or "",
                          datos.get("motivo") or "", pasos)
    return Salida("esperar", por_defecto_esperar_a, None, "",
                  "El camino lento no encontró una salida que respete la spec; se espera por seguridad.", pasos)
