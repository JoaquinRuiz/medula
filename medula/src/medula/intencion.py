"""La intención la construye Médula: la tarea asignada más lo que va a hacer la herramienta."""
from __future__ import annotations

import difflib
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

MAX_TAREA = 600
MAX_CAMBIO = 1500
MAX_COMANDO = 300
MAX_ESTADO = 60_000  # caracteres; deja margen dentro de los 32k tokens de Jev


def _recortar(texto: str, n: int) -> str:
    texto = texto or ""
    return texto if len(texto) <= n else texto[: n - 1] + "…"


def resumen_tarea(tareas_dir: Path | None, tarea: str | None) -> str:
    """Título, objetivo y alcance de tasks/TN.md, recortados."""
    if not tarea:
        return ""
    if not tareas_dir or not (tareas_dir / f"{tarea}.md").exists():
        return tarea
    lineas = (tareas_dir / f"{tarea}.md").read_text(encoding="utf-8").splitlines()
    titulo = lineas[0].lstrip("# ").strip() if lineas else tarea
    partes, seccion = [], None
    for linea in lineas[1:]:
        if linea.startswith("## "):
            seccion = linea[3:].strip().lower()
            continue
        if seccion in ("objetivo", "alcance") and linea.strip():
            partes.append(linea.strip())
    return _recortar(titulo + ". " + " ".join(partes), MAX_TAREA)


MAX_CRITERIOS = 1500


def criterios_tarea(tareas_dir: Path | None, tarea: str | None) -> str:
    """La sección «Criterios de aceptación» de tasks/TN.md (para el camino lento)."""
    if not tarea or not tareas_dir or not (tareas_dir / f"{tarea}.md").exists():
        return ""
    lineas, dentro, salida = (tareas_dir / f"{tarea}.md").read_text(encoding="utf-8").splitlines(), False, []
    for linea in lineas:
        if linea.startswith("## "):
            dentro = linea[3:].strip().lower().startswith("criterios de aceptación")
            continue
        if dentro and linea.strip():
            salida.append(linea.strip())
    return _recortar("\n".join(salida), MAX_CRITERIOS)


# --- Bash de solo lectura -------------------------------------------------------

_LECTURA = {"ls", "cat", "head", "tail", "grep", "rg", "wc", "pwd", "echo", "which", "tree", "file", "stat", "cd",
            "true", "sleep", "diff", "less", "sort", "uniq", "cut", "jq"}
_GIT_LECTURA = {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files", "blame"}


def _segmento_lectura(tokens: list[str]) -> bool:
    if not tokens:
        return True
    cmd, resto = tokens[0], tokens[1:]
    if cmd in _LECTURA:
        return True
    if cmd == "find":
        if any(t in ("-delete", "-fprint", "-fprintf", "-fls") for t in resto):
            return False
        # -exec/-execdir/-ok: lectura si lo que ejecuta es de lectura (p. ej. `find … -exec cat {} \;`).
        for i, t in enumerate(resto):
            if t in ("-exec", "-execdir", "-ok", "-okdir"):
                sub = []
                for u in resto[i + 1:]:
                    if u in (";", "\\;", "+"):
                        break
                    sub.append(u)
                if not _segmento_lectura([x for x in sub if x != "{}"]):
                    return False
        return True
    if cmd == "sed":
        return "-i" not in resto and not any(t.startswith("-i") for t in resto)
    if cmd == "git":
        sub = next((t for t in resto if not t.startswith("-")), "")
        return sub in _GIT_LECTURA
    if cmd in ("pytest",):
        return True
    if cmd == "python" and resto[:2] == ["-m", "pytest"]:
        return True
    if cmd == "uv" and resto[:1] == ["run"]:
        sub = [t for t in resto[1:] if not t.startswith("--")]
        if sub[:1] == ["pytest"] or sub[:3] == ["python", "-m", "pytest"] or sub[:2] == ["python", "-c"]:
            return True
    return False


def solo_lectura(comando: str) -> bool:
    """True si el comando de Bash no escribe nada (lista blanca). Ante la duda, False."""
    limpio = re.sub(r"\d?>&\d|\d?>\s*/dev/null", "", comando)
    if re.search(r"[<>]|\$\(|`", limpio):
        return False
    try:
        lexer = shlex.shlex(limpio, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return False
    segmento: list[str] = []
    for t in tokens:
        if t in (";", "&&", "||", "|", "&"):
            if not _segmento_lectura(segmento):
                return False
            segmento = []
        else:
            segmento.append(t)
    return _segmento_lectura(segmento)


# --- Acción --------------------------------------------------------------------

@dataclass
class Accion:
    herramienta: str
    objetivo: str
    cambio: str
    recurso: str
    escritura: bool

    def para_estado(self) -> dict:
        return {"herramienta": self.herramienta, "objetivo": self.objetivo, "cambio": self.cambio}

    def resumen(self) -> str:
        return _recortar(f"{self.herramienta} {self.objetivo}", 120)


def _relativa(ruta: str, raiz: Path | None) -> str:
    if not ruta:
        return ""
    p = Path(ruta)
    if raiz:
        try:
            return str(p.resolve().relative_to(raiz.resolve()))
        except (ValueError, OSError):
            pass
    return str(p)


def accion_de(herramienta: str, entrada: dict, raiz: Path | None) -> Accion:
    entrada = entrada or {}
    if herramienta in ("Edit", "MultiEdit"):
        ruta = _relativa(entrada.get("file_path", ""), raiz)
        if herramienta == "MultiEdit":
            cambios = [f"- {e.get('old_string', '')}\n+ {e.get('new_string', '')}" for e in entrada.get("edits", [])]
            cambio = "\n".join(cambios)
        else:
            cambio = f"- {entrada.get('old_string', '')}\n+ {entrada.get('new_string', '')}"
        return Accion(herramienta, ruta, _recortar(cambio, MAX_CAMBIO), ruta, True)
    if herramienta == "Write":
        ruta_abs = entrada.get("file_path", "")
        ruta = _relativa(ruta_abs, raiz)
        nuevo = entrada.get("content", "")
        p = Path(ruta_abs) if Path(ruta_abs).is_absolute() else (raiz or Path.cwd()) / ruta_abs
        if p.exists():
            viejo = p.read_text(encoding="utf-8", errors="replace").splitlines()
            diff = difflib.unified_diff(viejo, nuevo.splitlines(), lineterm="", n=1)
            cambio = "\n".join(list(diff)[2:])
        else:
            cambio = "(fichero nuevo)\n" + nuevo
        return Accion(herramienta, ruta, _recortar(cambio, MAX_CAMBIO), ruta, True)
    if herramienta == "Bash":
        comando = entrada.get("command", "")
        cambio = entrada.get("description") or comando
        return Accion("Bash", _recortar(comando, MAX_COMANDO), _recortar(cambio, MAX_COMANDO), "repo",
                      not solo_lectura(comando))
    return Accion(herramienta, "", _recortar(str(entrada), MAX_COMANDO), "", False)


# --- Estado para el decisor ----------------------------------------------------

def estado(agente: str, tarea: str, accion: Accion, otros: list[dict]) -> dict:
    """Misma forma que en E-03 y E-04. `otros`: [{agente, tarea, tiene, intencion}]."""
    est = {
        "solicitante": {"agente": agente, "tarea": tarea, "accion": accion.para_estado()},
        "otros_agentes": otros,
    }
    # Si no cabe, se recorta primero el historial de intenciones de los otros agentes.
    import json

    while len(json.dumps(est, ensure_ascii=False)) > MAX_ESTADO:
        mayor = max(est["otros_agentes"], key=lambda o: len(o.get("intencion", "")), default=None)
        if not mayor or len(mayor.get("intencion", "")) < 200:
            break
        mayor["intencion"] = _recortar(mayor["intencion"], len(mayor["intencion"]) // 2)
    return est


def intencion_de_lock(tarea: str, accion: Accion) -> dict:
    return {"tarea": tarea, **accion.para_estado()}


def resumen_intenciones(locks: list[dict], n: int = 4) -> str:
    """Las últimas escrituras de un agente, resumidas, para el estado de los demás."""
    partes = []
    for lk in locks[-n:]:
        i = lk["intencion"]
        partes.append(f"{i.get('herramienta')} {i.get('objetivo')}: {_recortar(i.get('cambio', ''), 300)}")
    return "\n".join(partes)
