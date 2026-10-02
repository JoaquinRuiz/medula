#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pyyaml>=6",
#     "rich>=13.7",
# ]
# ///
"""E-04 · Etiquetado a mano del set de calibración.

Recorre calibration/candidatas.yaml y guarda tus etiquetas en
calibration/etiquetas.yaml, que es la verdad contra la que se mide.

Por defecto es a ciegas: primero decides tú y solo después, si no coincides
con la propuesta, te la enseña con su motivo para que confirmes o cambies.

    uv run bench/e04_etiquetar.py             # sigue por donde lo dejaste
    uv run bench/e04_etiquetar.py --revisar   # repasa también las ya etiquetadas
    uv run bench/e04_etiquetar.py --desde C040
    uv run bench/e04_etiquetar.py --resumen   # solo el estado
    uv run bench/e04_etiquetar.py --salida calibration/etiquetas_humanas/<tu-usuario>.yaml
                                              # tus etiquetas, a ciegas y en tu propio fichero
    uv run bench/e04_etiquetar.py --salida calibration/etiquetas_humanas/<tu-usuario>.yaml --plantilla
                                              # lo mismo, pero todas las parejas en un fichero para editarlo

Teclas: c = choca · n = no choca · d = dudosa (se excluye) · s = saltar · q = salir
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

RAIZ = Path(__file__).resolve().parents[1]
CANDIDATAS = RAIZ / "calibration" / "candidatas.yaml"
ETIQUETAS = RAIZ / "calibration" / "etiquetas.yaml"
TECLAS = {"c": "choca", "n": "no_choca", "d": "dudosa"}


def normalizar(etiquetas: dict) -> dict:
    """Admite la forma corta de la plantilla (c / n / d) y descarta las parejas sin etiquetar."""
    salida = {}
    for k, v in (etiquetas or {}).items():
        v = v if isinstance(v, dict) else {"etiqueta": v}
        e = str(v.get("etiqueta") or "").strip().lower()
        e = TECLAS.get(e, e)
        if e in TECLAS.values():
            salida[k] = {**v, "etiqueta": e}
    return salida


def cargar_pares() -> list[dict]:
    return yaml.safe_load(CANDIDATAS.read_text(encoding="utf-8"))["pares"]


def cargar_etiquetas() -> dict:
    if not ETIQUETAS.exists():
        return {}
    return normalizar((yaml.safe_load(ETIQUETAS.read_text(encoding="utf-8")) or {}).get("etiquetas", {}))


def guardar_etiquetas(etiquetas: dict) -> None:
    cabecera = (
        "# Etiquetas a mano del set de calibración (E-04). Las escribe bench/e04_etiquetar.py.\n"
        "# etiqueta: choca | no_choca | dudosa (las dudosas se excluyen de la medición).\n"
    )
    cuerpo = yaml.safe_dump({"etiquetas": dict(sorted(etiquetas.items()))}, allow_unicode=True, sort_keys=False)
    tmp = ETIQUETAS.with_suffix(".tmp")
    tmp.write_text(cabecera + cuerpo, encoding="utf-8")
    tmp.replace(ETIQUETAS)


def plantilla(pares: list[dict], destino: Path) -> None:
    """Todas las parejas en un fichero para etiquetar de una vez, a ciegas: sin propuesta, motivo ni categoría."""
    def comentario(texto: str, sangria: str = "    ") -> str:
        return "\n".join(f"#{sangria}{linea}".rstrip() for linea in str(texto).splitlines() or [""])

    trozos = [
        "# Etiquetas humanas del set de calibración. Escribe en cada «etiqueta:» una de estas letras:\n"
        "#   c = choca · n = no choca · d = dudosa\n"
        "# Las que dejes en blanco no cuentan. «nota» es opcional: lo más útil en las dudosas.\n"
        "# Qué significa «choca»: calibration/README.md. Acuerdo: uv run bench/acuerdo_etiquetas.py\n"
        "etiquetas:\n"
    ]
    for par in pares:
        s, o, a = par["solicitante"], par["otro"], par["solicitante"]["accion"]
        trozos.append(
            f"\n# ── {par['id']} " + "─" * 60 + "\n"
            f"# {s['agente']} · {s['tarea']}\n"
            f"#   quiere {a['herramienta']} en {a['objetivo']}\n"
            f"{comentario(a['cambio'])}\n"
            f"# {o['agente']} · {o['tarea']}\n"
            f"#   tiene {', '.join(o['tiene'])}\n"
            f"{comentario(o['intencion'])}\n"
            f"  {par['id']}:\n    etiqueta:\n    nota: ''\n"
        )
    destino.write_text("".join(trozos), encoding="utf-8")


def mostrar(par: dict, posicion: str, consola: Console) -> None:
    s, o = par["solicitante"], par["otro"]
    a = s["accion"]
    texto = (
        f"[bold]{s['agente']}[/] · {s['tarea']}\n"
        f"  quiere [bold]{a['herramienta']}[/] en [cyan]{a['objetivo']}[/]\n"
        f"  [dim]{a['cambio']}[/]\n\n"
        f"[bold]{o['agente']}[/] · {o['tarea']}\n"
        f"  tiene [cyan]{', '.join(o['tiene'])}[/]\n"
        f"  [dim]{o['intencion']}[/]"
    )
    consola.print(Panel(texto, title=f"{par['id']} · {posicion}", subtitle="¿choca?", border_style="cyan"))


def resumen(pares: list[dict], etiquetas: dict, consola: Console) -> None:
    cuenta = {"choca": 0, "no_choca": 0, "dudosa": 0}
    discrepancias = marcadas = 0
    for p in pares:
        e = etiquetas.get(p["id"])
        if e:
            cuenta[e["etiqueta"]] += 1
            discrepancias += e["etiqueta"] != p["propuesta"] and e["etiqueta"] != "dudosa"
            marcadas += bool(e.get("revisar"))
    t = Table(title="Estado del etiquetado")
    for col in ("Etiquetadas", "choca", "no choca", "dudosas", "Pendientes", "Por revisar",
                "Distintas de la propuesta"):
        t.add_column(col, justify="right")
    hechas = sum(cuenta.values())
    t.add_row(str(hechas), str(cuenta["choca"]), str(cuenta["no_choca"]), str(cuenta["dudosa"]),
              str(len(pares) - hechas), str(marcadas), str(discrepancias))
    consola.print(t)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="E-04 · etiquetado a mano del set de calibración")
    p.add_argument("--revisar", action="store_true", help="repasar también las ya etiquetadas")
    p.add_argument("--desde", help="empezar en este id (p. ej. C040)")
    p.add_argument("--ver-propuesta", action="store_true", help="enseñar la propuesta antes de decidir")
    p.add_argument("--resumen", action="store_true", help="mostrar el estado y salir")
    p.add_argument("--salida", type=Path,
                   help="fichero de etiquetas (por defecto calibration/etiquetas.yaml); uno por persona, a ciegas")
    p.add_argument("--plantilla", action="store_true",
                   help="con --salida: escribir todas las parejas en ese fichero para etiquetarlas de una vez")
    p.add_argument("--marcadas", action="store_true",
                   help="repasar solo las marcadas con revisar: true (las discutibles)")
    args = p.parse_args(argv)
    global ETIQUETAS
    if args.salida:
        ETIQUETAS = args.salida if args.salida.is_absolute() else RAIZ / args.salida
        ETIQUETAS.parent.mkdir(parents=True, exist_ok=True)

    consola = Console()
    pares = cargar_pares()
    if args.plantilla:
        if not args.salida:
            consola.print("[red]--plantilla necesita --salida (tu fichero en calibration/etiquetas_humanas/).[/]")
            return 2
        if ETIQUETAS.exists():
            consola.print(f"[red]{ETIQUETAS} ya existe; no lo sobrescribo.[/]")
            return 2
        plantilla(pares, ETIQUETAS)
        consola.print(f"Plantilla con {len(pares)} parejas en {ETIQUETAS}")
        return 0
    etiquetas = cargar_etiquetas()
    if args.resumen:
        resumen(pares, etiquetas, consola)
        return 0

    ids = [x["id"] for x in pares]
    inicio = ids.index(args.desde) if args.desde in ids else 0
    if args.marcadas:
        cola = [x for x in pares[inicio:] if etiquetas.get(x["id"], {}).get("revisar")]
    else:
        cola = [x for x in pares[inicio:] if args.revisar or x["id"] not in etiquetas]
    if not cola:
        consola.print("[green]No queda nada por etiquetar.[/]")
        resumen(pares, etiquetas, consola)
        return 0

    consola.print("[dim]c = choca · n = no choca · d = dudosa · s = saltar · q = salir. "
                  "Guía de etiquetado en calibration/README.md.[/]")
    for i, par in enumerate(cola, 1):
        mostrar(par, f"{i}/{len(cola)}", consola)
        previa = etiquetas.get(par["id"], {}).get("etiqueta")
        if previa and not args.marcadas and args.ver_propuesta:  # en --marcadas se decide a ciegas; la nota sale al discrepar
            consola.print(f"[dim]Etiqueta actual: {previa} ({etiquetas[par['id']].get('autor', 'mano')})[/]")
        if args.ver_propuesta:
            consola.print(f"[dim]Propuesta: {par['propuesta']} · {par['motivo']}[/]")
        tecla = Prompt.ask("¿choca?", choices=["c", "n", "d", "s", "q"], show_choices=False)
        if tecla == "q":
            break
        if tecla == "s":
            continue
        etiqueta = TECLAS[tecla]
        # Con --salida (etiquetas humanas) no se enseña la propuesta ni después: a ciegas hasta el final.
        if etiqueta != "dudosa" and etiqueta != par["propuesta"] and not args.salida:
            consola.print(Panel(f"La propuesta era [bold]{par['propuesta']}[/]: {par['motivo']}",
                                border_style="yellow"))
            confirma = Prompt.ask("¿Te quedas con la tuya?", choices=["s", "c", "n", "d"], default="s",
                                  show_choices=False)
            if confirma != "s":
                etiqueta = TECLAS[confirma]
        nota = ""
        if etiqueta != par["propuesta"]:  # discrepancia o dudosa: vale la pena saber por qué
            nota = Prompt.ask("Nota (Enter para ninguna)", default="", show_default=False)
        etiquetas[par["id"]] = {
            "etiqueta": etiqueta,
            "propuesta": par["propuesta"],
            "autor": "mano",
            "nota": nota,
            "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        guardar_etiquetas(etiquetas)

    resumen(pares, etiquetas, consola)
    return 0


if __name__ == "__main__":
    sys.exit(main())
