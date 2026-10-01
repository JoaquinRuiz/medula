"""Regla de símbolos compartidos (experimento 1).

Si el cambio del solicitante usa un símbolo (función, campo o endpoint) que otro agente
activo declara que está cambiando, es un choque probable, sin preguntar a ningún modelo.
Después, Jev solo decide si ese cambio es compatible (p. ej. un parámetro opcional).

- Símbolos que usa la acción: los identificadores y endpoints del código de su cambio.
- Símbolos que cambia el otro agente: los que aparecen en contexto de código en lo que
  declara (su tarea y su intención): entre comillas invertidas, seguidos de "(", tras un ".",
  con "_", en líneas "-" de un diff, en definiciones (def, class, campo:) o como endpoint.
"""
from __future__ import annotations

import keyword
import re

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_GENERICOS = {
    "self", "cls", "str", "int", "float", "bool", "bytes", "dict", "list", "set", "tuple", "none", "true", "false",
    "len", "print", "range", "open", "json", "os", "sys", "re", "app", "db", "api", "router", "get", "post", "put",
    "delete", "patch", "request", "response", "test", "tests", "assert", "pytest", "fixture", "client", "auth",
    "conn", "cur", "row", "rows", "fila", "filas", "r", "c", "f", "x", "i", "e", "p", "k", "v", "n", "t", "s",
    "py", "md", "yaml", "toml", "txt", "csv", "id", "uv", "run", "git", "the", "and", "for", "con", "por", "del",
    "los", "las", "una", "que", "sin", "fastapi", "pydantic", "sqlite3", "datetime", "date", "time", "timedelta",
    "depends", "header", "httpexception", "basemodel", "field", "optional", "any", "path", "http", "https",
}


def _limpio(nombres) -> set[str]:
    salida = set()
    for n in nombres:
        n = n.strip("`'\" ")
        if not n or keyword.iskeyword(n) or n.lower() in _GENERICOS or len(n) < 3:
            continue
        salida.add(n)
    return salida


def _endpoints(texto: str) -> set[str]:
    return {m for m in re.findall(r"(?<![\w.])/(?:[a-z][\w-]*)(?:/[\w{}-]+)*", texto) if len(m) > 2}


def usados(cambio: str) -> set[str]:
    """Todo identificador del código del cambio (el cambio es código o casi)."""
    return _limpio(re.findall(_IDENT, cambio or "")) | _endpoints(cambio or "")


def cambiados(declarado: str) -> set[str]:
    """Identificadores en contexto de código dentro de la tarea y la intención de otro agente."""
    t = declarado or ""
    nombres: set[str] = set()
    for bloque in re.findall(r"`([^`]+)`", t):
        nombres |= set(re.findall(_IDENT, bloque))
    nombres |= set(re.findall(rf"({_IDENT})\s*\(", t))                    # login(
    nombres |= set(re.findall(rf"\.({_IDENT})", t))                        # Reserva.fecha
    nombres |= {m for m in re.findall(_IDENT, t) if "_" in m.strip("_")}   # validar_sala, duracion_min
    nombres |= set(re.findall(rf"\b(?:def|class)\s+({_IDENT})", t))
    nombres |= set(re.findall(rf"^\s*[-+]?\s*({_IDENT})\s*:\s*[A-Za-z]", t, re.M))  # campo: tipo
    for linea in t.splitlines():                                           # líneas "-" de un diff
        if linea.lstrip().startswith("- "):
            nombres |= set(re.findall(_IDENT, linea))
    return _limpio(nombres) | _endpoints(t)


def compartidos(accion: dict, otro: dict) -> set[str]:
    """Símbolos que usa la acción del solicitante y que el otro agente declara que cambia."""
    declarado = f"{otro.get('tarea', '')}\n{otro.get('intencion', '')}"
    return usados(accion.get("cambio", "") + "\n" + accion.get("objetivo", "")) & cambiados(declarado)
