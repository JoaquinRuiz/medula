"""Gráfico de calibración con los datos de E-04b: probabilidad de choque declarada frente a la frecuencia real de choque.

Si el decisor está bien calibrado, de las parejas a las que da ~0,7, chocan ~el 70 %: los puntos
caen sobre la diagonal. Usa las llamadas de results/e04b (Jev = variante base, noul «¿choca?").

    uv run --project medula --with matplotlib python bench/grafico_calibracion.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
FUENTES = ["results/e04b/20260929-103843", "results/e04b/20260929-104619"]
SALIDA = RAIZ / "results" / "e04b" / "calibracion"
SERIES = {"base": "Jev", "haiku": "Haiku", "sonnet": "Sonnet"}
TRAMOS = [(i / 10, (i + 1) / 10 + (1e-9 if i == 9 else 0)) for i in range(10)]
MIN_N = 4
# Paleta de referencia (slots 1-3), tinta, rejilla y superficie por modo, como el gráfico de calibración de E-04.
TEMAS = {
    "claro": {"superficie": "#fcfcfb", "tinta": "#0b0b0b", "secundaria": "#52514e", "muted": "#898781",
              "rejilla": "#e1e0d9", "eje": "#c3c2b7", "series": {"base": "#2a78d6", "haiku": "#eb6834", "sonnet": "#1baf7a"}},
    "oscuro": {"superficie": "#1a1a19", "tinta": "#ffffff", "secundaria": "#c3c2b7", "muted": "#898781",
               "rejilla": "#2c2c2a", "eje": "#383835", "series": {"base": "#3987e5", "haiku": "#d95926", "sonnet": "#199e70"}},
}


def tramos(filas: list[dict]) -> list[dict]:
    salida = []
    for lo, hi in TRAMOS:
        t = [f for f in filas if lo <= f["p"] < hi]
        salida.append({"tramo": f"{lo:.1f}-{min(hi, 1):.1f}", "n": len(t),
                       "p_media": sum(f["p"] for f in t) / len(t) if t else None,
                       "frecuencia_choque": sum(f["etiqueta"] == "choca" for f in t) / len(t) if t else None})
    return salida


def ece(ts: list[dict], n: int) -> float:
    return sum(t["n"] / n * abs(t["frecuencia_choque"] - t["p_media"]) for t in ts if t["n"])


def grafico(datos: dict, tema: str, destino: Path) -> None:
    t = TEMAS[tema]
    plt.rcParams.update({"font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"], "font.size": 12})
    fig, ax = plt.subplots(figsize=(10, 6.4), dpi=200)
    fig.patch.set_facecolor(t["superficie"])
    ax.set_facecolor(t["superficie"])
    ax.plot([0, 1], [0, 1], color=t["eje"], linewidth=1, zorder=1)
    ax.text(0.03, 0.12, "calibración perfecta", color=t["muted"], fontsize=10, ha="left", va="bottom", rotation=0)
    for v in ("sonnet", "haiku", "base"):  # Jev encima: es la serie de la historia
        pts = [(x["p_media"], x["frecuencia_choque"]) for x in datos[v]["tramos"] if x["n"] >= MIN_N]
        if not pts:
            continue
        xs, ys = zip(*pts)
        jev = v == "base"
        ax.plot(xs, ys, color=t["series"][v], linewidth=2.5 if jev else 2, marker="o", markersize=8 if jev else 6.5,
                markeredgecolor=t["superficie"], markeredgewidth=2, solid_capstyle="round", solid_joinstyle="round",
                label=f"{SERIES[v]} · ECE {datos[v]['ece']:.3f}".replace(".", ","), zorder=3 if jev else 2,
                alpha=1 if jev else 0.9)
        if jev:
            ax.annotate("Jev", (xs[2], ys[2]), xytext=(8, -4), textcoords="offset points", color=t["tinta"],
                        fontsize=12, fontweight="bold", va="top")
    ax.set_xlim(-0.02, 1.04)
    ax.set_ylim(-0.03, 1.05)
    ticks = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
    ax.set_xticks(ticks)
    ax.set_yticks(ticks)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.1f}".replace(".", ","))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}".replace("%", " %"))
    ax.grid(True, color=t["rejilla"], linewidth=1)
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(t["eje"])
    ax.tick_params(colors=t["muted"], length=0, labelsize=11)
    ax.set_xlabel("Probabilidad de choque declarada (media del tramo)", color=t["secundaria"], labelpad=10)
    ax.set_ylabel("Parejas que chocan de verdad", color=t["secundaria"], labelpad=10)
    fig.text(0.07, 0.95, "¿Cuánto vale la probabilidad de Jev?", color=t["tinta"], fontsize=17, fontweight="bold")
    fig.text(0.07, 0.905, f"Probabilidad declarada frente a frecuencia real de choque · {datos['_n']} parejas "
             f"etiquetadas por Claude, 2 repeticiones", color=t["secundaria"], fontsize=11)
    ley = ax.legend(loc="lower right", frameon=False, labelcolor=t["secundaria"], fontsize=11)
    for linea in ley.get_lines():
        linea.set_markeredgecolor(t["superficie"])
    fig.subplots_adjust(left=0.1, right=0.95, top=0.85, bottom=0.12)
    fig.savefig(destino, facecolor=t["superficie"])
    plt.close(fig)


def main() -> int:
    registros = [json.loads(l) for d in FUENTES for l in (RAIZ / d / "calls.jsonl").read_text().splitlines() if l]
    datos = {"_n": len({r["par"] for r in registros})}
    for v in SERIES:
        filas = [r for r in registros if r["variante"] == v and r.get("p") is not None]
        ts = tramos(filas)
        datos[v] = {"tramos": ts, "ece": ece(ts, len(filas)), "n": len(filas)}
    SALIDA.mkdir(parents=True, exist_ok=True)
    with (SALIDA / "calibracion_noul.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["decisor", "tramo", "n", "p_media", "frecuencia_choque"])
        for v, nombre in SERIES.items():
            for x in datos[v]["tramos"]:
                w.writerow([nombre, x["tramo"], x["n"], x["p_media"], x["frecuencia_choque"]])
    for tema in TEMAS:
        grafico(datos, tema, SALIDA / f"calibracion_noul_{tema}.png")
    for v, nombre in SERIES.items():
        print(f"{nombre:7} ECE {datos[v]['ece']:.3f}  " + "  ".join(
            f"{x['tramo']}:{x['n']}→{x['frecuencia_choque']:.0%}" for x in datos[v]["tramos"] if x["n"]))
    print(f"Escrito en {SALIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
