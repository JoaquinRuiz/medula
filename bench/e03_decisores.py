#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.27",
#     "rich>=13.7",
# ]
# ///
"""E-03 · Microbenchmark de decisores de Médula (v2).

Hace a Jev, Haiku y Sonnet, todos a través de OpenRouter, las dos preguntas del
acquire de Médula en una sola llamada: si la acción choca con el trabajo en curso de
otro agente y, por si choca, si basta con esperar o hay que replanificar. El veredicto
(conceder, esperar, conflicto o dudoso → Sonnet) lo decide el código con umbrales.

    export OPENROUTER_API_KEY=sk-or-...
    uv run e03_decisores.py                      # 200 llamadas medidas por modelo
    uv run e03_decisores.py --demo               # una llamada a Jev en caliente, presentada en pantalla
    uv run e03_decisores.py -n 20 --modelos jev  # prueba rápida
    uv run e03_decisores.py --dry-run            # muestra las peticiones sin llamar

Deja en results/e03/<fecha-hora>/ un calls.jsonl con cada llamada y un resumen.json
con los datos clave (latencia y coste por decisión de cada decisor).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import track
from rich.table import Table
from rich.text import Text

BASE = "https://openrouter.ai/api/v1"
URL_SYSTEMONE = f"{BASE}/systemone"      # API System One de OpenRouter (Jev)
URL_CHAT = f"{BASE}/chat/completions"    # Chat Completions (Haiku y Sonnet)
URL_GENERACION = f"{BASE}/generation"    # estadísticas de una generación, por si falta el coste

MODELOS = {
    "jev": "typesafe/jev-1.13",             # el decisor rápido
    "haiku": "anthropic/claude-haiku-4.5",  # comprueba el id exacto en openrouter.ai
    "sonnet": "anthropic/claude-sonnet-5",  # también el camino lento
}

# --- Las dos preguntas del acquire y la regla que las convierte en veredicto ---

PREGUNTA_CHOCA = (
    "¿Choca la acción del agente solicitante con algo que otro agente está cambiando ahora, "
    "de modo que ejecutarla ya podría romper su trabajo o el del otro agente?"
)
PREGUNTA_REMEDIO = "Si la acción choca con el trabajo de otro agente, ¿qué debería hacer el kernel?"
REMEDIOS = {
    "esperar": "Basta con que el solicitante espere a que el otro agente termine y después adapte su cambio.",
    "replanificar": "Los dos cambios son incompatibles entre sí y hay que replanificar una de las dos tareas.",
}
UMBRAL_CONCEDER = 0.2  # probabilidad de choque por debajo de la cual se concede
UMBRAL_CHOQUE = 0.8    # por encima, se espera o se replanifica; en medio, decide Sonnet
COLORES = {"conceder": "green", "esperar": "yellow", "conflicto": "red", "dudoso": "magenta"}


def veredicto(p_choca: float | None, remedio: str | None, umbral_conceder: float, umbral_choque: float) -> str:
    if p_choca is None:
        return "dudoso"
    if p_choca < umbral_conceder:
        return "conceder"
    if p_choca > umbral_choque:
        return "conflicto" if remedio == "replanificar" else "esperar"
    return "dudoso"


# --- Escenarios: estados realistas de acquire sobre la API de reservas (E-02) ---

T1 = "T1: añadir segundo factor al login; login() pasa a exigir un código OTP."
T2 = "T2: nuevo endpoint GET /export que valida las credenciales llamando a login(username, password) y devuelve las reservas en CSV."
T3 = "T3: renombrar el campo fecha de Reserva a inicio en el modelo, la base de datos y la API."
T4 = "T4: nuevo filtro GET /reservas?desde=AAAA-MM-DD sobre el campo fecha."
T5 = "T5: reescribir los mensajes de error de validar_sala() para que sean más claros."
T6 = "T6: añadir a validar_horario() la regla de que solo se reserva entre las 8:00 y las 20:00."


def _otro(agente: str, tarea: str, tiene: list[str], intencion: str) -> dict:
    return {"agente": agente, "tarea": tarea, "tiene": tiene, "intencion": intencion}


def _escenario(id_, esperado, agente, tarea, herramienta, objetivo, cambio, otros) -> dict:
    return {
        "id": id_,
        "esperado": esperado,
        "estado": {
            "solicitante": {
                "agente": agente,
                "tarea": tarea,
                "accion": {"herramienta": herramienta, "objetivo": objetivo, "cambio": cambio},
            },
            "otros_agentes": otros,
        },
    }


A1_LOGIN = _otro("A1", T1, ["app/auth.py"], "Cambiar la firma de login(username, password) a login(username, password, otp).")
A2_EXPORT = _otro("A2", T2, ["app/api/export.py"], "Autenticar /export llamando a login(username, password).")
A3_RENOMBRA = _otro("A3", T3, ["app/models.py", "app/db.py"], "Renombrar Reserva.fecha a Reserva.inicio en modelo, base de datos y API.")
A4_FILTRO = _otro("A4", T4, ["app/api/reservas.py"], "Filtrar el listado de reservas con Reserva.fecha >= desde.")
A1_MENSAJES = _otro("A1", T5, ["app/validators.py"], "Reescribir los mensajes de error de validar_sala().")

ESCENARIOS = [
    _escenario("S01", "esperar", "A2", T2, "Write", "app/api/export.py",
               "session = login(username, password)  # autentica antes de exportar",
               [A1_LOGIN, A4_FILTRO]),
    _escenario("S02", "esperar", "A4", T4, "Edit", "app/api/reservas.py",
               "query = query.filter(Reserva.fecha >= desde)",
               [A3_RENOMBRA, A1_LOGIN]),
    _escenario("S03", "conceder", "A2", T6, "Edit", "app/validators.py, función validar_horario",
               "if hora_inicio < time(8, 0) or hora_fin > time(20, 0): raise ValueError('Solo se reserva de 8:00 a 20:00')",
               [A1_MENSAJES, A3_RENOMBRA]),
    _escenario("S04", "conflicto", "A1", T1, "Edit", "app/auth.py",
               "def login(username: str, password: str, otp: str) -> Session:",
               [A2_EXPORT, A3_RENOMBRA]),
    _escenario("S05", "conflicto", "A3", T3, "Edit", "app/models.py",
               "inicio: datetime  # antes se llamaba fecha",
               [A4_FILTRO, A2_EXPORT]),
    _escenario("S06", "esperar", "A2", T2, "Edit", "app/api/export.py",
               "writer.writerow(['id', 'sala', 'fecha', 'usuario'])",
               [A3_RENOMBRA, A4_FILTRO]),
    _escenario("S07", "conceder", "A4", T4, "Bash", "uv run pytest -q",
               "Ejecutar los tests sin modificar ningún fichero.",
               [A1_LOGIN, A3_RENOMBRA]),
    _escenario("S08", "conceder", "A1", T1, "Edit", "README.md",
               "Documentar el flujo de login con código OTP.",
               [A2_EXPORT, A4_FILTRO]),
]

# --- Peticiones ---


def peticion_jev(modelo: str, estado: dict) -> dict:
    return {
        "model": modelo,
        "state": estado,
        "questions": {
            "choca": {"type": "noul", "instructions": PREGUNTA_CHOCA},
            "remedio": {"type": "choice", "instructions": PREGUNTA_REMEDIO, "criteria": REMEDIOS},
        },
    }


SISTEMA_LLM = (
    "Eres el decisor de un kernel que coordina agentes de código que trabajan a la vez sobre "
    "el mismo repositorio. Respondes solo con un objeto JSON con dos campos: choca, la "
    "probabilidad entre 0 y 1 de que la acción choque con el trabajo en curso de otro agente, "
    "y remedio, que es esperar o replanificar y solo importa si la acción choca."
)
ESQUEMA = {
    "type": "object",
    "properties": {
        "choca": {"type": "number"},
        "remedio": {"type": "string", "enum": list(REMEDIOS)},
    },
    "required": ["choca", "remedio"],
    "additionalProperties": False,
}


def peticion_llm(modelo: str, estado: dict, esfuerzo: str | None, estructurada: bool, max_tokens: int) -> dict:
    remedios = "\n".join(f"- {nombre}: {descripcion}" for nombre, descripcion in REMEDIOS.items())
    usuario = (
        f"1. {PREGUNTA_CHOCA}\n\n2. {PREGUNTA_REMEDIO}\n{remedios}\n\n"
        f"Estado:\n{json.dumps(estado, ensure_ascii=False, indent=2)}"
    )
    cuerpo = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": SISTEMA_LLM},
            {"role": "user", "content": usuario},
        ],
        "max_tokens": max_tokens,
        "usage": {"include": True},
    }
    if esfuerzo:
        cuerpo["reasoning"] = {"effort": esfuerzo}
    if estructurada:
        cuerpo["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "acquire", "strict": True, "schema": ESQUEMA},
        }
    return cuerpo


# --- Lectura de respuestas ---


def _a_float(valor) -> float | None:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def leer_jev(datos: dict) -> dict:
    respuestas = datos["answers"]
    choca = respuestas.get("choca") or {}
    remedio = respuestas.get("remedio") or {}
    uso = datos.get("usage") or {}
    return {
        "p_choca": _a_float(choca.get("noul")),
        "remedio": remedio.get("choice"),
        "remedio_confianza": remedio.get("confidence"),
        "remedio_probabilidades": remedio.get("probabilities"),
        "coste_usd": uso.get("cost"),
        "tokens_entrada": uso.get("input_tokens"),
        "tokens_salida": uso.get("output_tokens"),
        "tokens_razonamiento": None,
        "servido_por": datos.get("model"),
        "proveedor": datos.get("provider"),
        "id_generacion": datos.get("id"),
    }


def _texto(contenido) -> str:
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        return "".join(parte.get("text", "") for parte in contenido if isinstance(parte, dict))
    return ""


def leer_llm(datos: dict) -> dict:
    texto = _texto(datos["choices"][0]["message"].get("content"))
    try:
        respuesta = json.loads(texto)
    except json.JSONDecodeError:
        encontrado = re.search(r"\{.*\}", texto, re.DOTALL)
        if not encontrado:
            raise ValueError(f"respuesta sin JSON: {texto[:200]!r}")
        respuesta = json.loads(encontrado.group(0))
    uso = datos.get("usage") or {}
    detalles = uso.get("completion_tokens_details") or {}
    return {
        "p_choca": _a_float(respuesta.get("choca")),
        "remedio": str(respuesta.get("remedio", "")).strip().lower() or None,
        "remedio_confianza": None,
        "remedio_probabilidades": None,
        "coste_usd": uso.get("cost"),
        "tokens_entrada": uso.get("prompt_tokens"),
        "tokens_salida": uso.get("completion_tokens"),
        "tokens_razonamiento": detalles.get("reasoning_tokens"),
        "servido_por": datos.get("model"),
        "proveedor": datos.get("provider"),
        "id_generacion": datos.get("id"),
    }


# --- HTTP ---

REINTENTABLES = {429, 500, 502, 503, 504}


def enviar(cliente: httpx.Client, url: str, cuerpo: dict) -> tuple[httpx.Response, float, int]:
    """POST con reintentos. Devuelve la respuesta, la latencia del último intento en ms y los reintentos."""
    for intento in range(4):
        t0 = time.perf_counter()
        try:
            respuesta = cliente.post(url, json=cuerpo)
        except httpx.TransportError:
            if intento == 3:
                raise
            time.sleep(2**intento)
            continue
        latencia = (time.perf_counter() - t0) * 1000
        if respuesta.status_code in REINTENTABLES and intento < 3:
            time.sleep(2**intento)
            continue
        return respuesta, latencia, intento
    raise RuntimeError("sin respuesta tras los reintentos")


def coste_de_generacion(cliente: httpx.Client, id_generacion: str | None) -> float | None:
    """Si la respuesta no trae usage.cost, lo pide a las estadísticas de la generación."""
    if not id_generacion:
        return None
    for espera in (0.5, 1.0, 2.0):
        time.sleep(espera)
        respuesta = cliente.get(URL_GENERACION, params={"id": id_generacion})
        if respuesta.status_code == 200:
            return (respuesta.json().get("data") or {}).get("total_cost")
    return None


class Decisor:
    def __init__(self, alias: str, modelo: str, cliente: httpx.Client | None, esfuerzo: str | None = None,
                 max_tokens: int = 2048, umbrales: tuple[float, float] = (UMBRAL_CONCEDER, UMBRAL_CHOQUE)):
        self.alias, self.modelo, self.cliente = alias, modelo, cliente
        self.esfuerzo, self.max_tokens, self.umbrales = esfuerzo, max_tokens, umbrales
        self.estructurada = True  # se apaga si el modelo rechaza response_format

    def peticion(self, estado: dict) -> tuple[str, dict]:
        if self.alias == "jev":
            return URL_SYSTEMONE, peticion_jev(self.modelo, estado)
        return URL_CHAT, peticion_llm(self.modelo, estado, self.esfuerzo, self.estructurada, self.max_tokens)

    def decidir(self, estado: dict) -> dict:
        url, cuerpo = self.peticion(estado)
        respuesta, latencia, reintentos = enviar(self.cliente, url, cuerpo)
        if respuesta.status_code == 400 and "response_format" in cuerpo:
            # El modelo no acepta salida estructurada: se sigue pidiendo el JSON en el prompt.
            self.estructurada = False
            url, cuerpo = self.peticion(estado)
            respuesta, latencia, reintentos = enviar(self.cliente, url, cuerpo)
        respuesta.raise_for_status()
        datos = respuesta.json()
        leido = leer_jev(datos) if self.alias == "jev" else leer_llm(datos)
        if leido["coste_usd"] is None:
            leido["coste_usd"] = coste_de_generacion(self.cliente, leido["id_generacion"])
        return {
            **leido,
            "veredicto": veredicto(leido["p_choca"], leido["remedio"], *self.umbrales),
            "latencia_ms": round(latencia, 1),
            "reintentos": reintentos,
            "estructurada": None if self.alias == "jev" else self.estructurada,
        }


def _describir_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
    return f"{type(exc).__name__}: {exc}"


# --- Ejecución ---


def ejecutar(decisores: list[Decisor], escenarios: list[dict], n: int, calentamiento: int,
             salida: Path, consola: Console) -> list[dict]:
    registros = []
    with (salida / "calls.jsonl").open("w", encoding="utf-8") as fichero:
        for decisor in decisores:
            for i in range(calentamiento):  # no cuentan en las estadísticas
                try:
                    decisor.decidir(escenarios[i % len(escenarios)]["estado"])
                except Exception as exc:
                    consola.print(f"[yellow]Calentamiento de {decisor.alias}: {_describir_error(exc)}[/]")
            for i in track(range(n), description=f"{decisor.alias} · {decisor.modelo}", console=consola):
                escenario = escenarios[i % len(escenarios)]
                registro = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "modelo_alias": decisor.alias,
                    "modelo": decisor.modelo,
                    "escenario": escenario["id"],
                    "esperado": escenario.get("esperado"),
                }
                try:
                    registro.update(decisor.decidir(escenario["estado"]))
                    registro["error"] = None
                except Exception as exc:
                    registro["error"] = _describir_error(exc)
                registros.append(registro)
                fichero.write(json.dumps(registro, ensure_ascii=False) + "\n")
                fichero.flush()
            if decisor.alias != "jev" and not decisor.estructurada:
                consola.print(f"[yellow]{decisor.modelo} no aceptó salida estructurada; se pidió el JSON en el prompt.[/]")
    return registros


def percentil(valores: list[float], p: float) -> float | None:
    if not valores:
        return None
    ordenados = sorted(valores)
    return ordenados[max(0, math.ceil(p / 100 * len(ordenados)) - 1)]


def _media(valores: list[float]) -> float | None:
    return sum(valores) / len(valores) if valores else None


def resumir(registros: list[dict]) -> dict:
    resumen = {}
    for alias in dict.fromkeys(r["modelo_alias"] for r in registros):
        propios = [r for r in registros if r["modelo_alias"] == alias]
        correctos = [r for r in propios if not r["error"]]
        latencias = [r["latencia_ms"] for r in correctos]
        costes = [r["coste_usd"] for r in correctos if r.get("coste_usd") is not None]
        razonamiento = [r["tokens_razonamiento"] for r in correctos if r.get("tokens_razonamiento") is not None]
        decididos = [r for r in correctos if r["veredicto"] != "dudoso" and r.get("esperado")]
        chocan = [r["p_choca"] for r in correctos if r.get("esperado") in ("esperar", "conflicto") and r["p_choca"] is not None]
        no_chocan = [r["p_choca"] for r in correctos if r.get("esperado") == "conceder" and r["p_choca"] is not None]
        coste_medio = _media(costes)
        resumen[alias] = {
            "modelo": propios[0]["modelo"],
            "llamadas": len(propios),
            "errores": len(propios) - len(correctos),
            "p50_ms": percentil(latencias, 50),
            "p95_ms": percentil(latencias, 95),
            "coste_medio_usd": coste_medio,
            "coste_por_1000_usd": coste_medio * 1000 if coste_medio is not None else None,
            "llamadas_con_coste": len(costes),
            "veredictos": {v: sum(r["veredicto"] == v for r in correctos) for v in COLORES},
            "dudosos": _media([float(r["veredicto"] == "dudoso") for r in correctos]),
            "acuerdo_decididos": _media([float(r["veredicto"] == r["esperado"]) for r in decididos]),
            "p_choca_media_si_choca": _media(chocan),
            "p_choca_media_si_no_choca": _media(no_chocan),
            "tokens_razonamiento_medios": _media(razonamiento),
        }
    return resumen


def datos_clave(resumen: dict) -> dict:
    def valor(alias: str, campo: str):
        return (resumen.get(alias) or {}).get(campo)

    return {
        "latencia p50 de Jev (ms)": valor("jev", "p50_ms"),
        "latencia p95 de Jev (ms)": valor("jev", "p95_ms"),
        "coste por decisión de Jev (USD)": valor("jev", "coste_medio_usd"),
        "latencia p50 de Haiku (ms)": valor("haiku", "p50_ms"),
        "coste por decisión de Haiku (USD)": valor("haiku", "coste_medio_usd"),
        "latencia p50 de Sonnet (ms)": valor("sonnet", "p50_ms"),
        "coste por decisión de Sonnet (USD)": valor("sonnet", "coste_medio_usd"),
    }


# --- Presentación, con números a la española (3.238 ms, 0,36) ---


def es(valor: float, decimales: int = 0) -> str:
    return f"{valor:,.{decimales}f}".replace(",", "·").replace(".", ",").replace("·", ".")


def _num(valor, decimales: int = 0) -> str:
    return "—" if valor is None else es(valor, decimales)


def _usd(valor, decimales: int = 6) -> str:
    return "—" if valor is None else f"{es(valor, decimales)} $"


def _pct(valor) -> str:
    return "—" if valor is None else f"{es(valor * 100)} %"


def _barra(probabilidad: float | None, estilo: str) -> str:
    if probabilidad is None:
        return "[dim]—[/]"
    return f"[{estilo}]{'█' * max(1, round(probabilidad * 30))}[/]"


def imprimir_resumen(resumen: dict, consola: Console) -> None:
    modelos = " · ".join(f"{alias} = {r['modelo']}" for alias, r in resumen.items())
    tabla = Table(title="E-03 · Decisores por OpenRouter", caption=modelos)
    tabla.add_column("Modelo")
    for columna in ("OK/err", "p50 ms", "p95 ms", "$/decisión", "$/1.000", "Acuerdo", "Dudosos", "Razon."):
        tabla.add_column(columna, justify="right")
    for alias, r in resumen.items():
        tabla.add_row(
            alias,
            f"{r['llamadas'] - r['errores']}/{r['errores']}",
            _num(r["p50_ms"]),
            _num(r["p95_ms"]),
            _usd(r["coste_medio_usd"]),
            _usd(r["coste_por_1000_usd"], 2),
            _pct(r["acuerdo_decididos"]),
            _pct(r["dudosos"]),
            _num(r["tokens_razonamiento_medios"]),
        )
    consola.print(tabla)
    consola.print(
        "[dim]Acuerdo: veredictos decididos que coinciden con la etiqueta orientativa del escenario "
        "(la calibración de verdad es E-04). Dudosos: llamadas que irían a Sonnet por caer entre umbrales. "
        "Razon.: tokens de razonamiento medios, para comprobar que se aplicó el esfuerzo bajo.[/]"
    )


def imprimir_datos_clave(datos: dict, consola: Console) -> None:
    lineas = []
    for clave, valor in datos.items():
        if valor is None:
            texto = "—"
        elif "(ms)" in clave:
            texto = f"{es(valor)} ms"
        else:
            texto = _usd(valor)
        lineas.append(f"{clave}: [bold]{texto}[/]")
    consola.print(Panel("\n".join(lineas), title="Datos clave", border_style="green"))


def demo(decisor: Decisor, escenario: dict, calentar: bool, consola: Console) -> None:
    estado = escenario["estado"]
    solicitante = estado["solicitante"]
    accion = solicitante["accion"]
    lineas = [
        f"[bold]{solicitante['agente']}[/] quiere hacer {accion['herramienta']} en [cyan]{accion['objetivo']}[/]",
        f"[dim]{solicitante['tarea']}[/]",
        "",
    ]
    for otro in estado["otros_agentes"]:
        lineas.append(f"[bold]{otro['agente']}[/] tiene {', '.join(otro['tiene'])}: {otro['intencion']}")
    consola.print(Panel("\n".join(lineas), title="Médula · acquire", border_style="cyan"))

    en_frio = None
    if calentar:  # la primera llamada abre la conexión; Médula la mantiene abierta
        en_frio = decisor.decidir(estado)["latencia_ms"]
    consola.print("Preguntando a Jev: ¿choca? y, si choca, ¿qué hacer?…")
    r = decisor.decidir(estado)

    color = COLORES.get(r["veredicto"], "white")
    filas = Table(show_header=False, box=None, padding=(0, 1))
    filas.add_row("¿Choca?", _barra(r["p_choca"], color), _num(r["p_choca"], 2))
    for opcion, probabilidad in sorted((r["remedio_probabilidades"] or {}).items(), key=lambda par: -par[1]):
        estilo = color if opcion == r["remedio"] and r["veredicto"] in ("esperar", "conflicto") else "dim"
        filas.add_row(f"  {opcion}", _barra(probabilidad, estilo), _num(probabilidad, 2))
    umbral_conceder, umbral_choque = decisor.umbrales
    regla = Text.from_markup(
        f"[dim]Regla: choque < {es(umbral_conceder, 2)} → conceder · > {es(umbral_choque, 2)} → "
        f"esperar o replanificar · en medio → Sonnet[/]"
    )
    titulo = "DUDOSO → SONNET" if r["veredicto"] == "dudoso" else str(r["veredicto"]).upper()
    consola.print(Panel(Group(filas, Text(""), regla), title=f"[bold {color}]{titulo}[/]", border_style=color))

    frio = f"  [dim](la primera llamada, en frío: {_num(en_frio)} ms)[/]" if en_frio is not None else ""
    consola.print(
        f"Latencia [bold]{_num(r['latencia_ms'])} ms[/]{frio}  ·  coste [bold]{_usd(r['coste_usd'])}[/]"
        f"  ·  servido por {r['servido_por']}"
    )


# --- CLI ---


def _esfuerzo(valor: str) -> str | None:
    return None if valor.lower() in {"", "none", "no"} else valor


def argumentos(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="E-03 · microbenchmark de decisores de Médula por OpenRouter")
    p.add_argument("-n", type=int, default=200, help="llamadas medidas por modelo (200)")
    p.add_argument("--modelos", default="jev,haiku,sonnet", help="alias separados por comas: jev, haiku, sonnet")
    p.add_argument("--jev", default=MODELOS["jev"], help="id de Jev en OpenRouter")
    p.add_argument("--haiku", default=MODELOS["haiku"], help="id de Haiku en OpenRouter")
    p.add_argument("--sonnet", default=MODELOS["sonnet"], help="id de Sonnet en OpenRouter")
    p.add_argument("--esfuerzo-haiku", default="none", help="razonamiento de Haiku: none, low, medium, high (none)")
    p.add_argument("--esfuerzo-sonnet", default="low", help="razonamiento de Sonnet (low, el más bajo)")
    p.add_argument("--max-tokens", type=int, default=2048, help="tope de tokens de salida para Haiku y Sonnet")
    p.add_argument("--umbral-conceder", type=float, default=UMBRAL_CONCEDER, help="choque por debajo → conceder (0.2)")
    p.add_argument("--umbral-choque", type=float, default=UMBRAL_CHOQUE, help="choque por encima → esperar o replanificar (0.8)")
    p.add_argument("--calentamiento", type=int, default=3, help="llamadas previas por modelo que no cuentan (3; 0 = sin calentar)")
    p.add_argument("--escenarios", type=Path, help="JSON propio con una lista de {id, esperado, estado}")
    p.add_argument("--salida", type=Path, default=Path("results/e03"), help="carpeta de resultados")
    p.add_argument("--demo", action="store_true", help="una llamada a Jev en caliente, presentada en pantalla")
    p.add_argument("--escenario-demo", default="S01", help="escenario de la demo (S01)")
    p.add_argument("--dry-run", action="store_true", help="muestra las peticiones sin llamar a la API")
    return p.parse_args(argv)


def main(argv: list[str] | None = None, transport: httpx.BaseTransport | None = None) -> int:
    args = argumentos(argv)
    consola = Console()
    escenarios = json.loads(args.escenarios.read_text(encoding="utf-8")) if args.escenarios else ESCENARIOS
    alias = ["jev"] if args.demo else [a.strip() for a in args.modelos.split(",") if a.strip()]
    desconocidos = set(alias) - set(MODELOS)
    if desconocidos:
        consola.print(f"[red]Alias desconocidos: {', '.join(sorted(desconocidos))}[/]")
        return 2
    modelos = {"jev": args.jev, "haiku": args.haiku, "sonnet": args.sonnet}
    esfuerzos = {"jev": None, "haiku": _esfuerzo(args.esfuerzo_haiku), "sonnet": _esfuerzo(args.esfuerzo_sonnet)}
    umbrales = (args.umbral_conceder, args.umbral_choque)

    if args.dry_run:
        for a in alias:
            decisor = Decisor(a, modelos[a], None, esfuerzos[a], args.max_tokens, umbrales)
            url, cuerpo = decisor.peticion(escenarios[0]["estado"])
            consola.rule(f"{a} → {url}")
            consola.print_json(json.dumps(cuerpo, ensure_ascii=False))
        return 0

    clave = os.environ.get("OPENROUTER_API_KEY")
    if not clave:
        consola.print("[red]Falta OPENROUTER_API_KEY en el entorno.[/]")
        return 2

    cabeceras = {"Authorization": f"Bearer {clave}", "X-Title": "Medula E-03"}
    with httpx.Client(headers=cabeceras, timeout=60, transport=transport) as cliente:
        decisores = [Decisor(a, modelos[a], cliente, esfuerzos[a], args.max_tokens, umbrales) for a in alias]
        if args.demo:
            escenario = next((e for e in escenarios if e["id"] == args.escenario_demo), escenarios[0])
            demo(decisores[0], escenario, args.calentamiento > 0, consola)
            return 0
        salida = args.salida / datetime.now().strftime("%Y%m%d-%H%M%S")
        salida.mkdir(parents=True, exist_ok=True)
        registros = ejecutar(decisores, escenarios, args.n, args.calentamiento, salida, consola)

    resumen = resumir(registros)
    datos = datos_clave(resumen)
    meta = {
        "fecha_utc": datetime.now(timezone.utc).isoformat(),
        "llamadas_por_modelo": args.n,
        "calentamiento": args.calentamiento,
        "modelos": {a: modelos[a] for a in alias},
        "esfuerzos": {a: esfuerzos[a] for a in alias},
        "umbrales": {"conceder": umbrales[0], "choque": umbrales[1]},
        "max_tokens": args.max_tokens,
        "escenarios": [e["id"] for e in escenarios],
        "nota": "Latencias de extremo a extremo desde esta máquina, con el paso por OpenRouter incluido; costes en USD según OpenRouter.",
    }
    (salida / "resumen.json").write_text(
        json.dumps({"meta": meta, "modelos": resumen, "datos": datos}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    imprimir_resumen(resumen, consola)
    imprimir_datos_clave(datos, consola)
    consola.print(f"Resultados en [bold]{salida}[/]")
    return 0


if __name__ == "__main__":
    sys.exit(main())