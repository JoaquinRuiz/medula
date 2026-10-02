"""Interfaz común de los decisores y cliente de OpenRouter."""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

import httpx2 as httpx

BASE = "https://openrouter.ai/api/v1"
# Hilos para las peticiones a los modelos: el que espera puede abandonar al cumplirse el plazo.
_HILOS = ThreadPoolExecutor(max_workers=32, thread_name_prefix="medula-decisor")

# La definición de «choca» es la de calibration/README.md (E-04), igual para todos los decisores.
GUIA_CHOCA = (
    "Choca si, al ejecutar ahora la acción del solicitante y completar el otro agente su intención sin "
    "coordinarse, el resultado combinado rompe algo (una llamada, un contrato, datos o tests), una de las dos "
    "tareas tiene que rehacerse, o la acción destruye o sobrescribe el trabajo del otro. Las lecturas y los "
    "comandos que no escriben nada nunca chocan. Tocar el mismo fichero no implica choque."
)
GUIA_INVALIDA = (
    "El cambio invalida el plan del otro agente si, para completar su tarea correctamente, ese agente tiene que "
    "cambiar lo que iba a hacer o lo que ya ha hecho (por ejemplo, porque usa una función, un campo o un "
    "comportamiento que el cambio acaba de modificar)."
)
REMEDIOS = {
    "esperar": "Basta con que el solicitante espere a que el otro agente termine y después se adapte.",
    "replanificar": "Hay que replanificar: cambiar el orden de las tareas o reescribir la acción.",
}


class ErrorDecisor(Exception):
    pass


@dataclass
class Veredicto:
    p: float
    remedio: str | None = None
    confianza: float | None = None
    motivo: str | None = None


@dataclass
class Lote:
    """Resultado de una petición a un decisor: un veredicto por cada otro agente."""
    veredictos: dict[str, Veredicto]
    decisor: str
    modelo: str | None
    latencia_ms: float
    coste_usd: float
    pregunta: str
    crudo: dict = field(default_factory=dict)
    reserva_de: list[str] = field(default_factory=list)


class Decisor:
    nombre = "base"

    def acquire(self, estado: dict, otros: list[str]) -> Lote:  # pragma: no cover - interfaz
        raise NotImplementedError

    def invalida(self, estado: dict, otros: list[str]) -> Lote:  # pragma: no cover - interfaz
        raise NotImplementedError


class OpenRouter:
    """Cliente mínimo: POST con tiempo máximo, latencia de extremo a extremo y coste de OpenRouter."""

    def __init__(self, clave: str | None, transport: httpx.BaseTransport | None = None):
        cabeceras = {"Authorization": f"Bearer {clave or ''}", "X-Title": "Medula"}
        self.cliente = httpx.Client(base_url=BASE, headers=cabeceras, transport=transport, timeout=60)

    def _pedir(self, ruta: str, cuerpo: dict, timeout: float, abandonada: threading.Event) -> tuple[int, bytes] | None:
        with self.cliente.stream("POST", ruta, json=cuerpo, timeout=timeout) as r:
            trozos = []
            for trozo in r.iter_bytes():
                if abandonada.is_set():  # nadie espera ya esta respuesta: se cierra la conexión
                    return None
                trozos.append(trozo)
            return r.status_code, b"".join(trozos)

    def post(self, ruta: str, cuerpo: dict, timeout: float,
             duplicar_tras: float | None = None) -> tuple[dict, float, float]:
        """`timeout` es el plazo total de la petición, no el de cada operación de httpx: una respuesta que
        llega a goteo no puede alargar la espera del agente más allá del plazo.

        Con `duplicar_tras`, si no hay respuesta en esos segundos se lanza una segunda petición idéntica y vale la
        primera que llegue bien (contra la cola larga de latencia). La perdedora se corta y su coste, que
        OpenRouter no llega a decir, se estima igual al de la ganadora; `datos["medula"]` lo deja anotado."""
        t0 = time.perf_counter()
        limite = t0 + timeout
        abandonadas: list[threading.Event] = []

        def lanzar():
            abandonadas.append(threading.Event())
            return _HILOS.submit(self._pedir, ruta, cuerpo, timeout, abandonadas[-1])

        pendientes = {lanzar()}
        if duplicar_tras and duplicar_tras < timeout and not wait(pendientes, timeout=duplicar_tras).done:
            pendientes.add(lanzar())
        duplicada = len(abandonadas) > 1
        resultado, fallo = None, None
        while pendientes and resultado is None:
            hechas, pendientes = wait(pendientes, timeout=max(0.0, limite - time.perf_counter()),
                                      return_when=FIRST_COMPLETED)
            if not hechas:
                break
            for f in hechas:
                try:
                    r = f.result()
                except httpx.HTTPError as e:
                    fallo = fallo or e
                    continue
                if r is not None and r[0] == 200:
                    resultado = r
                    break
                fallo = fallo or r  # un error HTTP: si queda la otra petición, se la espera
        for ev in abandonadas:
            ev.set()
        if resultado is None and isinstance(fallo, tuple):
            resultado = fallo
        if resultado is None:
            if fallo is None or isinstance(fallo, httpx.TimeoutException):
                raise ErrorDecisor(f"timeout tras {timeout} s" + (" (petición duplicada)" if duplicada else ""))
            raise ErrorDecisor(f"{type(fallo).__name__}: {fallo}") from fallo
        estado, contenido = resultado
        latencia = (time.perf_counter() - t0) * 1000
        texto = contenido.decode("utf-8", errors="replace")
        if estado != 200:
            raise ErrorDecisor(f"HTTP {estado}: {texto[:300]}")
        try:
            datos = json.loads(texto)
        except json.JSONDecodeError as e:
            raise ErrorDecisor(f"respuesta no JSON: {texto[:200]}") from e
        coste = float(((datos.get("usage") or {}).get("cost")) or 0.0)
        if duplicada:
            datos["medula"] = {"duplicada": True, "coste_estimado_perdedora": coste}
            coste *= 2
        return datos, latencia, coste


def acotar(p) -> float:
    try:
        return min(1.0, max(0.0, float(p)))
    except (TypeError, ValueError) as e:
        raise ErrorDecisor(f"probabilidad no válida: {p!r}") from e
