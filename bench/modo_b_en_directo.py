"""Modo B en directo: lanza bench/run_mode_b.sh y muestra a los agentes trabajando.

Una sola terminal: arriba un panel por tarea con lo que hace su agente
(ficheros que lee y edita, comandos, coste al terminar) y abajo el log del
script (rondas, merge y tests). Pensado para seguir el arranque de los agentes y
el merge y los tests; al terminar deja en pantalla el resumen del merge.

    uv run python bench/modo_b_en_directo.py                 # mismos argumentos que run_mode_b.sh
    uv run python bench/modo_b_en_directo.py --run-id b1
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

RAIZ = Path(__file__).resolve().parents[1]
TAREAS = [f"T{i}" for i in range(1, 7)]
EVENTOS_VISIBLES = 7


def runs_dir() -> Path:
    base = os.environ.get("MEDULA_RUNS_DIR") or os.path.join(os.environ.get("TMPDIR", "/tmp"), "medula-runs")
    return Path(base).resolve()


def titulo_tarea(t: str) -> str:
    primera = (RAIZ / "tasks" / f"{t}.md").read_text(encoding="utf-8").splitlines()[0]
    return primera.lstrip("# ").split("—", 1)[-1].strip()


def describir(item: dict) -> str | None:
    if item.get("type") == "tool_use":
        entrada = item.get("input") or {}
        detalle = (entrada.get("file_path") or entrada.get("command") or entrada.get("pattern")
                   or entrada.get("path") or entrada.get("description") or "")
        detalle = re.sub(r"/\S*?/(?:repo|ws-T\d)/", "", str(detalle)).splitlines()[0] if detalle else ""
        return f"{item.get('name')} {detalle}".strip()
    if item.get("type") == "text":
        texto = (item.get("text") or "").strip().splitlines()
        return f"› {texto[0]}" if texto else None
    return None


class Agente:
    def __init__(self, nombre: str, fichero: Path):
        self.nombre, self.fichero = nombre, fichero
        self.offset, self.eventos = 0, deque(maxlen=EVENTOS_VISIBLES)
        self.estado, self.resultado, self.inicio = "esperando", None, None
        self.herramientas = 0

    def leer(self) -> None:
        if not self.fichero.exists():
            return
        if self.estado == "esperando":
            self.estado, self.inicio = "trabajando", time.time()
        with self.fichero.open(encoding="utf-8") as f:
            f.seek(self.offset)
            for linea in f:
                if not linea.endswith("\n"):
                    break  # línea a medio escribir: se lee en la siguiente vuelta
                self.offset += len(linea.encode("utf-8"))
                try:
                    ev = json.loads(linea)
                except ValueError:
                    continue
                if ev.get("type") == "assistant":
                    for item in (ev.get("message") or {}).get("content") or []:
                        d = describir(item)
                        if d:
                            self.eventos.append(d)
                            self.herramientas += item.get("type") == "tool_use"
                elif ev.get("type") == "result":
                    self.resultado = ev
                    self.estado = "error" if ev.get("is_error") else "terminado"

    def panel(self, titulo: str) -> Panel:
        cuerpo = Text()
        for e in self.eventos:
            estilo = "dim" if e.startswith("›") else ""
            cuerpo.append(e[:70] + "\n", style=estilo)
        if self.estado == "esperando":
            cuerpo.append("esperando a su ronda…", style="dim")
        pie, borde = "", "grey50"
        if self.estado == "trabajando":
            pie, borde = f"trabajando · {int(time.time() - self.inicio)} s · {self.herramientas} acciones", "cyan"
        elif self.resultado:
            r = self.resultado
            coste = r.get("total_cost_usd")
            pie = (f"{'✓ terminado' if self.estado == 'terminado' else '✗ error'} · {r.get('num_turns', '?')} turnos"
                   + (f" · ${coste:.2f}" if isinstance(coste, (int, float)) else ""))
            borde = "green" if self.estado == "terminado" else "red"
        return Panel(cuerpo, title=f"[bold]{self.nombre}[/] · {titulo}", subtitle=pie, border_style=borde,
                     height=EVENTOS_VISIBLES + 2, title_align="left", subtitle_align="left")


def main(argv: list[str]) -> int:
    run_id = f"b-{datetime.now():%Y%m%d-%H%M%S}"
    if "--run-id" in argv:
        run_id = argv[argv.index("--run-id") + 1]
    else:
        argv = [*argv, "--run-id", run_id]
    logs = runs_dir() / run_id / "logs"
    titulos = {t: titulo_tarea(t) for t in TAREAS}
    agentes = {t: Agente(t, logs / "agents" / f"{t}.stream.jsonl") for t in TAREAS}
    log = deque(maxlen=14)
    todo_el_log: list[str] = []

    # COLUMNS ancho: pytest no recorta los motivos de los fallos en el resumen final.
    proceso = subprocess.Popen([str(RAIZ / "bench" / "run_mode_b.sh"), *argv], cwd=RAIZ, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1, env={**os.environ, "COLUMNS": "200"})

    def lector():
        for linea in proceso.stdout:
            linea = linea.rstrip("\n")
            log.append(linea)
            todo_el_log.append(linea)

    hilo = threading.Thread(target=lector, daemon=True)
    hilo.start()
    t0 = time.time()

    def pantalla():
        for a in agentes.values():
            a.leer()
        ronda = 2 if agentes["T5"].estado != "esperando" else 1
        merge = any(" merge T" in x or x.startswith("merge") for x in todo_el_log)
        fase = "merge y tests" if merge else f"ronda {ronda}"
        coste = sum((a.resultado or {}).get("total_cost_usd") or 0 for a in agentes.values())
        for f in (logs / "resolvers").glob("resolve-*.json"):  # las resoluciones de conflictos también cuentan
            try:
                coste += json.loads(f.read_text()).get("total_cost_usd") or 0
            except (ValueError, OSError):
                pass
        cabecera = Text.assemble(("Modo B", "bold"), " · cada tarea en su rama, merge al final · ",
                                 (fase, "bold cyan"), f" · {int(time.time() - t0) // 60:02d}:{int(time.time() - t0) % 60:02d}",
                                 f" · ${coste:.2f}")
        rejilla = Table.grid(expand=True, padding=(0, 1))
        for _ in range(3):
            rejilla.add_column(ratio=1)
        rejilla.add_row(*(agentes[t].panel(titulos[t]) for t in ("T1", "T2", "T3")))
        rejilla.add_row(*(agentes[t].panel(titulos[t]) for t in ("T4", "T5", "T6")))
        registro = Text("\n".join(log[-12:] if isinstance(log, list) else list(log)[-12:]))
        return Group(cabecera, rejilla, Panel(registro, title="run_mode_b.sh", border_style="grey50",
                                              title_align="left", height=14))

    consola = Console()
    with Live(pantalla(), console=consola, refresh_per_second=4, screen=False) as live:
        while proceso.poll() is None or hilo.is_alive():
            live.update(pantalla())
            time.sleep(0.25)
        live.update(pantalla())

    if proceso.returncode:
        consola.print(Panel(Text("\n".join(todo_el_log[-15:]), style="red"), border_style="red",
                            title=f"run_mode_b.sh ha fallado (código {proceso.returncode})", title_align="left"))
        return proceso.returncode

    # Resumen final: el merge y los tests, tal como los dejó el script.
    merges = [x.split("] ", 1)[-1] for x in todo_el_log if "] merge T" in x]
    tests = [x for x in todo_el_log if x.startswith("FAILED") or " passed" in x or " failed" in x]
    resumen = Text()
    for m in merges:
        resumen.append(("✓ " if "limpio" in m or "resuelto" in m else "✗ ") + m + "\n",
                       style="green" if "limpio" in m or "resuelto" in m else "red")
    resumen.append("\n")
    for x in tests:
        resumen.append(x + "\n", style="red" if x.startswith("FAILED") or "failed" in x else "green")
    consola.print(Panel(resumen, title="Merge y tests de aceptación", border_style="yellow", title_align="left"))
    return proceso.returncode or 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
