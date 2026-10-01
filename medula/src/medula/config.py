"""Configuración de una instancia de Médula."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx2 as httpx

MODELOS = {
    "jev": "typesafe/jev-1.13",
    "haiku": "anthropic/claude-haiku-4.5",
    "sonnet": "anthropic/claude-sonnet-5",
    "opus": "anthropic/claude-opus-5.5",
}
# Tiempo máximo por llamada antes de pasar al siguiente decisor de la cadena.
TIMEOUTS = {"jev": 5.0, "haiku": 15.0, "sonnet": 30.0, "opus": 60.0}
# Reserva automática por decisor principal.
CADENAS = {
    "jev": ["jev", "haiku", "locks"],
    "haiku": ["haiku", "locks"],
    "sonnet": ["sonnet", "locks"],
    "locks": ["locks"],
}


@dataclass
class Config:
    db: Path
    decisor: str = "jev"
    raiz: Path | None = None  # directorio de trabajo de los agentes, para rutas relativas
    tareas_dir: Path | None = None  # tasks/TN.md
    plan: dict = field(default_factory=dict)
    pregunta: str = "choca"          # choca | direccional (experimento 2)
    regla_simbolos: bool = False     # experimento 1
    umbral_bajo: float = 0.2
    umbral_alto: float = 0.8
    umbral_aviso: float = 0.5
    espera_max: float = 60.0
    modelos: dict = field(default_factory=lambda: dict(MODELOS))
    timeouts: dict = field(default_factory=lambda: dict(TIMEOUTS))
    esfuerzo_sonnet: str | None = "low"
    coste_sonnet_por_decision: float | None = None  # medido en E-03, para el htop
    openrouter_key: str | None = field(default_factory=lambda: os.environ.get("OPENROUTER_API_KEY"))
    transport: httpx.BaseTransport | None = None  # para tests

    def __post_init__(self):
        if self.decisor not in CADENAS:
            raise ValueError(f"decisor desconocido: {self.decisor}")

    @property
    def semantico(self) -> bool:
        """Los modos semánticos tienen camino lento e interrupciones; el lock clásico no."""
        return self.decisor != "locks"

    @property
    def cadena(self) -> list[str]:
        return CADENAS[self.decisor]
