"""Decisores intercambiables con la misma interfaz: jev, haiku, sonnet y locks."""
from __future__ import annotations

from ..config import Config
from .base import Decisor, ErrorDecisor, Lote, OpenRouter, Veredicto
from .cadena import Cadena
from .jev import Jev
from .llm import LLM
from .locks import Locks

__all__ = ["Decisor", "ErrorDecisor", "Lote", "Veredicto", "OpenRouter", "Cadena", "construir", "cliente"]


def cliente(config: Config) -> OpenRouter:
    return OpenRouter(config.openrouter_key, config.transport)


def uno(nombre: str, config: Config, or_: OpenRouter) -> Decisor:
    if nombre == "jev":
        return Jev(or_, config.modelos["jev"], config.timeouts["jev"], config.pregunta)
    if nombre == "haiku":
        return LLM("haiku", or_, config.modelos["haiku"], config.timeouts["haiku"], None,
                   config.duplicar_tras.get("haiku"))
    if nombre == "sonnet":
        return LLM("sonnet", or_, config.modelos["sonnet"], config.timeouts["sonnet"], config.esfuerzo_sonnet)
    if nombre == "locks":
        return Locks()
    raise ValueError(nombre)


def construir(config: Config, or_: OpenRouter) -> Cadena:
    return Cadena([uno(n, config, or_) for n in config.cadena])
