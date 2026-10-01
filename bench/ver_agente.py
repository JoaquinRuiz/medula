"""Vista de la terminal de un agente: sigue en vivo lo que hace (o repasa una ejecución terminada).

Muestra cada herramienta, lo que el agente piensa en voz alta y, sobre todo, los bloqueos de Médula
con su motivo, que es lo que el agente ve en su terminal.

    uv run python bench/ver_agente.py --run-id e08-demo T2
    uv run python bench/ver_agente.py --run-id d1 T2 --sin-seguir     # repasar una ejecución ya hecha
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text


def runs_dir() -> Path:
    return Path(os.environ.get("MEDULA_RUNS_DIR") or os.path.join(os.environ.get("TMPDIR", "/tmp"), "medula-runs")).resolve()


def corto(texto: str) -> str:
    return re.sub(r"/\S*?/(?:repo|ws-T\d)/", "", str(texto))


def pintar(ev: dict, consola: Console) -> bool:
    """Pinta un evento del stream. Devuelve True al llegar el evento final."""
    tipo = ev.get("type")
    if tipo == "assistant":
        for c in (ev.get("message") or {}).get("content") or []:
            if c.get("type") == "text" and c.get("text", "").strip():
                consola.print(Text(c["text"].strip(), style="white"))
            elif c.get("type") == "tool_use":
                e = c.get("input") or {}
                detalle = e.get("file_path") or e.get("command") or e.get("pattern") or e.get("path") or ""
                consola.print(Text.assemble(("● ", "cyan"), (c.get("name", ""), "bold cyan"), " ", corto(detalle)[:140]))
    elif tipo == "user":
        for c in (ev.get("message") or {}).get("content") or []:
            if not isinstance(c, dict) or c.get("type") != "tool_result":
                continue
            contenido = c.get("content")
            texto = contenido if isinstance(contenido, str) else " ".join(
                x.get("text", "") for x in contenido or [] if isinstance(x, dict))
            if "Médula" in texto:
                consola.print(Panel(Text(corto(texto).replace("PreToolUse:", "").strip(), style="bold"),
                                    title="Bloqueado por Médula", title_align="left", border_style="red"))
            elif c.get("is_error"):
                consola.print(Text("  ⎿ " + corto(texto)[:200], style="red"))
    elif tipo == "result":
        coste = ev.get("total_cost_usd")
        consola.print(Panel(Text(corto(ev.get("result") or "")[:600]), border_style="green", title_align="left",
                            title=f"Terminado · {ev.get('num_turns', '?')} turnos"
                                  + (f" · ${coste:.2f}" if isinstance(coste, (int, float)) else "")))
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("tarea", help="T1 … T6")
    ap.add_argument("--sin-seguir", action="store_true", help="no esperar eventos nuevos")
    a = ap.parse_args()
    fichero = runs_dir() / a.run_id / "logs" / "agents" / f"{a.tarea}.stream.jsonl"
    consola = Console()
    consola.print(Text.assemble(("Agente de ", "dim"), (a.tarea, "bold"), (f" · {a.run_id}", "dim")))
    while not fichero.exists():
        if a.sin_seguir:
            consola.print(f"[red]No existe {fichero}[/]")
            return 2
        time.sleep(0.5)
    with fichero.open(encoding="utf-8") as f:
        pendiente = ""
        while True:
            linea = f.readline()
            if not linea:
                if a.sin_seguir:
                    return 0
                time.sleep(0.3)
                continue
            pendiente += linea
            if not pendiente.endswith("\n"):
                continue
            try:
                ev = json.loads(pendiente)
            except ValueError:
                pendiente = ""
                continue
            pendiente = ""
            if pintar(ev, consola):
                return 0


if __name__ == "__main__":
    raise SystemExit(main())
