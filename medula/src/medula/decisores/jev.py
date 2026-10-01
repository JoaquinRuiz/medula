"""Jev por la API System One de OpenRouter: noul para la probabilidad, choice para el remedio.

Todas las preguntas (dos por cada otro agente) van en una sola petición.
"""
from __future__ import annotations

from .base import GUIA_CHOCA, GUIA_INVALIDA, REMEDIOS, Decisor, ErrorDecisor, Lote, OpenRouter, Veredicto, acotar


def _noul(respuesta: dict) -> float:
    """Valor de una respuesta noul: {"type": "noul", "noul": 0.98}. Se aceptan variantes por robustez."""
    for clave in ("noul", "probability", "value", "p"):
        if clave in respuesta:
            return acotar(respuesta[clave])
    raise ErrorDecisor(f"respuesta noul sin valor: {respuesta}")


GUIA_USA = ("Por ejemplo: llama a una función, lee un campo o una columna, o consume un endpoint o un "
            "comportamiento que ese agente está modificando.")
GUIA_CAMBIA = ("Por ejemplo: modifica la firma de una función, renombra un campo o una columna, o cambia un "
               "endpoint o un comportamiento del que depende el trabajo de ese agente.")


class Jev(Decisor):
    nombre = "jev"

    def __init__(self, cliente: OpenRouter, modelo: str, timeout: float, pregunta: str = "choca"):
        """pregunta: "choca" (una noul por agente) o "direccional" (usa / cambia, dos noul por agente)."""
        self.cliente, self.modelo, self.timeout, self.pregunta = cliente, modelo, timeout, pregunta

    def _preguntar(self, estado: dict, preguntas: dict, pregunta: str) -> tuple[dict, float, float, dict]:
        cuerpo = {"model": self.modelo, "state": estado, "questions": preguntas}
        datos, latencia, coste = self.cliente.post("/systemone", cuerpo, self.timeout)
        respuestas = datos.get("answers")
        if not isinstance(respuestas, dict):
            raise ErrorDecisor(f"respuesta sin answers: {str(datos)[:200]}")
        return respuestas, latencia, coste, datos

    def acquire(self, estado: dict, otros: list[str]) -> Lote:
        preguntas = {}
        for x in otros:
            if self.pregunta == "direccional":
                preguntas[f"usa_{x}"] = {
                    "type": "noul",
                    "instructions": f"¿Usa la acción del solicitante algo que el agente {x} está cambiando? {GUIA_USA}",
                }
                preguntas[f"cambia_{x}"] = {
                    "type": "noul",
                    "instructions": f"¿Cambia la acción del solicitante algo que el agente {x} está usando? {GUIA_CAMBIA}",
                }
            else:
                preguntas[f"choca_{x}"] = {
                    "type": "noul",
                    "instructions": f"¿Choca la acción del solicitante con lo que está haciendo el agente {x}? {GUIA_CHOCA}",
                }
            preguntas[f"remedio_{x}"] = {
                "type": "choice",
                "instructions": f"Si la acción del solicitante chocase con el trabajo del agente {x}, ¿qué salida sería la adecuada?",
                "criteria": REMEDIOS,
            }
        respuestas, latencia, coste, crudo = self._preguntar(estado, preguntas, self.pregunta)
        veredictos = {}
        for x in otros:
            claves = [f"usa_{x}", f"cambia_{x}"] if self.pregunta == "direccional" else [f"choca_{x}"]
            try:
                p = max(_noul(respuestas[k]) for k in claves)  # direccional: la mayor de las dos
            except KeyError as e:
                raise ErrorDecisor(f"falta la respuesta {e}") from e
            rem = respuestas.get(f"remedio_{x}") or {}
            remedio = rem.get("choice") if rem.get("choice") in REMEDIOS else "esperar"
            veredictos[x] = Veredicto(p=p, remedio=remedio, confianza=max(p, 1 - p))
        return Lote(veredictos, self.nombre, self.modelo, latencia, coste, self.pregunta, crudo)

    def compatible(self, estado: dict, simbolos: dict[str, set[str]]) -> Lote:
        """Regla de símbolos: la acción usa símbolos que otro agente está cambiando. Jev solo decide si el
        cambio es compatible con ese uso. Devuelve p = probabilidad de choque = 1 - p(compatible)."""
        preguntas = {
            f"compatible_{x}": {
                "type": "noul",
                "instructions": (
                    f"La acción del solicitante usa {', '.join(sorted(s))}, que el agente {x} está cambiando. "
                    f"¿Es el cambio de {x} compatible con ese uso, de modo que la acción seguirá funcionando "
                    "cuando {x} termine (por ejemplo, un parámetro nuevo opcional con valor por defecto, o una "
                    "función o un campo nuevos que no tocan lo existente)?"
                ).replace("{x}", x),
            }
            for x, s in simbolos.items()
        }
        respuestas, latencia, coste, crudo = self._preguntar(estado, preguntas, "compatible")
        veredictos = {}
        for x in simbolos:
            try:
                p = 1 - _noul(respuestas[f"compatible_{x}"])
            except KeyError as e:
                raise ErrorDecisor(f"falta la respuesta compatible_{x}") from e
            veredictos[x] = Veredicto(p=p, remedio="esperar", confianza=max(p, 1 - p),
                                      motivo=f"usa {', '.join(sorted(simbolos[x]))}, que {x} está cambiando")
        return Lote(veredictos, "regla+jev", self.modelo, latencia, coste, "compatible", crudo)

    def invalida(self, estado: dict, otros: list[str]) -> Lote:
        preguntas = {
            f"invalida_{x}": {
                "type": "noul",
                "instructions": f"¿Invalida este cambio del solicitante el plan del agente {x}? {GUIA_INVALIDA}",
            }
            for x in otros
        }
        respuestas, latencia, coste, crudo = self._preguntar(estado, preguntas, "invalida")
        veredictos = {}
        for x in otros:
            try:
                p = _noul(respuestas[f"invalida_{x}"])
            except KeyError as e:
                raise ErrorDecisor(f"falta la respuesta invalida_{x}") from e
            veredictos[x] = Veredicto(p=p, confianza=max(p, 1 - p))
        return Lote(veredictos, self.nombre, self.modelo, latencia, coste, "invalida", crudo)
