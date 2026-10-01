# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6"]
# ///
"""Acuerdo entre etiquetadores del set de calibración.

Compara las etiquetas del modelo (calibration/etiquetas.yaml) con cada fichero de etiquetas humanas
(calibration/etiquetas_humanas/*.yaml) y los humanos entre sí: acuerdo bruto y kappa de Cohen, y la
lista de parejas en las que discrepan (las que más vale la pena discutir en un issue).

    uv run bench/acuerdo_etiquetas.py
"""
from __future__ import annotations

import itertools
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
CLASES = ("choca", "no_choca")


def cargar(f: Path) -> dict[str, str]:
    et = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("etiquetas", {})
    return {k: v["etiqueta"] for k, v in et.items() if v.get("etiqueta") in CLASES}


def kappa(a: dict, b: dict) -> tuple[int, float | None, float | None]:
    comunes = sorted(set(a) & set(b))
    if not comunes:
        return 0, None, None
    n = len(comunes)
    po = sum(a[k] == b[k] for k in comunes) / n
    pe = sum((sum(a[k] == c for k in comunes) / n) * (sum(b[k] == c for k in comunes) / n) for c in CLASES)
    return n, po, (po - pe) / (1 - pe) if pe < 1 else None


def main() -> None:
    fuentes = {"modelo": cargar(RAIZ / "calibration" / "etiquetas.yaml")}
    for f in sorted((RAIZ / "calibration" / "etiquetas_humanas").glob("*.yaml")):
        fuentes[f.stem] = cargar(f)
    if len(fuentes) == 1:
        print("Aún no hay etiquetas humanas en calibration/etiquetas_humanas/.")
        return
    print(f"{'pareja de etiquetadores':32} {'parejas':>7} {'acuerdo':>8} {'kappa':>6}")
    for x, y in itertools.combinations(fuentes, 2):
        n, po, k = kappa(fuentes[x], fuentes[y])
        print(f"{x + ' / ' + y:32} {n:>7} {'—' if po is None else f'{po:.0%}':>8} {'—' if k is None else f'{k:.2f}':>6}")
        discrepan = sorted(i for i in set(fuentes[x]) & set(fuentes[y]) if fuentes[x][i] != fuentes[y][i])
        if discrepan:
            print(f"{'':32} discrepan: {', '.join(discrepan)}")


if __name__ == "__main__":
    main()
