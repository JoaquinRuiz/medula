"""htop de agentes: lee el SQLite de Médula y muestra agentes, locks, cola, decisiones y costes."""
from __future__ import annotations

import json
import sqlite3
import statistics
import time
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

COLOR_ESTADO = {"trabajando": "cyan", "esperando": "yellow", "terminado": "green"}
COLOR_VEREDICTO = {"conceder": "green", "esperar": "yellow", "lento": "magenta", "reescribir": "red"}


def _leer(db: Path) -> dict:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    q = lambda sql: [dict(f) for f in c.execute(sql).fetchall()]  # noqa: E731
    datos = {
        "agentes": q("SELECT * FROM agentes ORDER BY id"),
        "locks": q("SELECT * FROM locks ORDER BY desde"),
        "cola": q("SELECT * FROM cola WHERE estado = 'esperando' ORDER BY prioridad, desde"),
        "decisiones": q("SELECT * FROM decisiones ORDER BY id DESC LIMIT 12"),
        "todas": q("SELECT * FROM decisiones"),  # con o sin finish_reason (bases anteriores)
        "avisos": q("SELECT COUNT(*) AS n FROM buzon WHERE de IS NOT NULL AND de != 'medula'")[0]["n"],
    }
    c.close()
    return datos


def _hace(ts: float | None) -> str:
    if not ts:
        return ""
    s = int(time.time() - ts)
    return f"{s} s" if s < 120 else f"{s // 60} min"


def _p(valores: list[float], q: float) -> float | None:
    if not valores:
        return None
    valores = sorted(valores)
    return valores[min(len(valores) - 1, int(q * len(valores)))]


def _cola_log(log: Path | None, n: int = 6) -> Panel | None:
    if not log or not log.exists():
        return None
    lineas = log.read_text(encoding="utf-8", errors="replace").splitlines()
    lineas = [x for x in lineas if x.startswith("[") or " passed" in x or " failed" in x][-n:]
    return Panel(Text("\n".join(lineas), style="dim"), title="Ejecución", title_align="left", border_style="grey50")


def pantalla(db: Path, coste_sonnet: float | None, log: Path | None = None) -> Group:
    try:
        d = _leer(db)
    except sqlite3.Error:  # la base de datos aún se está creando
        return Group(Text("Médula · esperando a que arranque…", style="dim"))
    ahora = time.time()

    agentes = Table(expand=True, box=None, header_style="bold")
    for col in ("Agente", "Tarea", "Estado", "Última acción"):
        agentes.add_column(col)
    for a in d["agentes"]:
        estado = a["estado"]
        if estado == "esperando":
            estado = f"esperando a {a['espera_a']}"
        agentes.add_row(a["id"], a["tarea"] or "", Text(estado, style=COLOR_ESTADO.get(a["estado"], "")),
                        (a["ultima_accion"] or "")[:60])

    locks = Table(expand=True, box=None, header_style="bold")
    for col in ("Recurso", "Agente", "Intención", "Desde"):
        locks.add_column(col)
    for lk in d["locks"]:
        i = json.loads(lk["intencion"])
        locks.add_row(lk["recurso"][:40], lk["agente"], (i.get("cambio") or "").replace("\n", " ")[:60],
                      _hace(lk["desde"]))

    cola = Table(expand=True, box=None, header_style="bold")
    for col in ("Agente", "Espera a", "Recurso", "Desde", "Prioridad"):
        cola.add_column(col)
    for c in d["cola"]:
        cola.add_row(c["agente"], c["espera_a"], c["recurso"][:40], _hace(c["desde"]), f"{c['prioridad']:g}")

    dec = Table(expand=True, box=None, header_style="bold")
    for col in ("Hora", "Tipo", "Agente", "Acción", "p", "Veredicto", "Decisor", "ms", "USD"):
        dec.add_column(col, justify="right" if col in ("p", "ms", "USD") else "left")
    for x in d["decisiones"]:
        accion = json.loads(x["accion"]) if x["accion"] else {}
        decisor = x["decisor"] or ""
        if x["reserva_de"]:
            decisor += f" (reserva de {x['reserva_de']})"
        ver = x["veredicto"] or ("error" if x["error"] else "")
        dec.add_row(time.strftime("%H:%M:%S", time.localtime(x["ts"])), x["tipo"], x["agente"] or "",
                    f"{accion.get('herramienta', '')} {accion.get('objetivo', '')}"[:40],
                    "" if x["p_choca"] is None else f"{x['p_choca']:.2f}",
                    Text(ver, style=COLOR_VEREDICTO.get(ver.split(":")[0], "")), decisor,
                    "" if x["latencia_ms"] is None else f"{x['latencia_ms']:.0f}",
                    "" if x["coste_usd"] is None else f"{x['coste_usd']:.5f}")

    modelo = [x for x in d["todas"] if x["decisor"] not in (None, "regla")]
    lat = [x["latencia_ms"] for x in modelo if x["latencia_ms"] is not None and x["tipo"] != "lento"]
    coste = sum(x["coste_usd"] or 0 for x in d["todas"])
    n_rapidas = sum(1 for x in modelo if x["tipo"] in ("acquire", "notify"))
    escaladas = {n: sum(1 for x in d["todas"] if x["tipo"] == "lento" and x["decisor"] == n
                        and x["pregunta"] != "verificacion" and x.get("finish_reason") != "length")
                 for n in ("sonnet", "opus")}
    rechazadas = sum(1 for x in d["todas"] if (x["veredicto"] or "").startswith("rechazada"))
    reservas = sum(1 for x in d["todas"] if x["reserva_de"])
    p50, p95 = _p(lat, 0.5), _p(lat, 0.95)
    totales = Text.assemble(
        ("Decisiones ", "dim"), (f"{len(d['todas'])}", "bold"), ("  ·  latencia p50 ", "dim"),
        (f"{p50:.0f} ms" if p50 is not None else "—", "bold"), ("  p95 ", "dim"),
        (f"{p95:.0f} ms" if p95 is not None else "—", "bold"), ("  ·  coste ", "dim"), (f"${coste:.4f}", "bold"),
    )
    if coste_sonnet:
        totales.append_text(Text.assemble(("  frente a ", "dim"), (f"${n_rapidas * coste_sonnet:.4f}", "bold"),
                                          (" si todo lo decidiese Sonnet", "dim")))
    totales.append_text(Text.assemble(("  ·  escaladas Sonnet ", "dim"), (str(escaladas["sonnet"]), "bold"),
                                      (" Opus ", "dim"), (str(escaladas["opus"]), "bold"),
                                      ("  ·  rechazadas por la spec ", "dim"), (str(rechazadas), "bold"),
                                      ("  ·  reservas ", "dim"), (str(reservas), "bold"),
                                      ("  ·  avisos ", "dim"), (str(d["avisos"]), "bold")))

    partes = [
        Text.assemble(("Médula", "bold"), " · htop de agentes · ", (time.strftime("%H:%M:%S", time.localtime(ahora)), "dim")),
        Panel(agentes, title="Agentes", title_align="left", border_style="cyan"),
        Panel(locks, title="Locks e intenciones", title_align="left", border_style="grey50"),
        Panel(cola, title="Cola de espera", title_align="left", border_style="yellow"),
        Panel(dec, title="Últimas decisiones", title_align="left", border_style="grey50"),
        Panel(totales, border_style="green"),
    ]
    registro = _cola_log(log)
    if registro:
        partes.append(registro)
    return Group(*partes)


def _vivo(pid: int | None) -> bool:
    if pid is None:
        return True
    import os

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def ejecutar(db: Path, coste_sonnet: float | None = None, una_vez: bool = False, log: Path | None = None,
             mientras_pid: int | None = None) -> int:
    """Pinta el htop. Con mientras_pid, sale solo cuando termina ese proceso (la ejecución)."""
    consola = Console()
    espera = 0
    while not Path(db).exists():
        if una_vez or espera > 600 or not _vivo(mientras_pid):
            consola.print(f"[red]No existe {db}[/]")
            return 2
        time.sleep(0.5)
        espera += 0.5
    if una_vez:
        consola.print(pantalla(db, coste_sonnet, log))
        return 0
    try:
        with Live(pantalla(db, coste_sonnet, log), console=consola, refresh_per_second=2, screen=True) as live:
            while _vivo(mientras_pid):
                time.sleep(0.5)
                live.update(pantalla(db, coste_sonnet, log))
    except KeyboardInterrupt:
        return 0
    consola.print(pantalla(db, coste_sonnet, log))  # el estado final queda en pantalla
    return 0
