"""Anonimiza las rutas locales de la evidencia de una o varias ejecuciones antes de publicarla.

Sustituye la carpeta de ejecuciones por <runs>, la raíz del repo por <repo>, el temporal por <tmp> y la home
por <home>, en ficheros de texto y, con SQL, en las bases de Médula (reemplazar bytes las corrompería).

    uv run python bench/lib/anonimizar.py results/runs/e4 results/runs/e5
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def sustituciones() -> list[tuple[str, str]]:
    tmp = Path(os.environ.get("TMPDIR") or tempfile.gettempdir()).resolve()
    runs = Path(os.environ.get("MEDULA_RUNS_DIR") or tmp / "medula-runs").resolve()
    pares = []
    for ruta, marca in ((runs, "<runs>"), (RAIZ, "<repo>"), (tmp, "<tmp>"), (Path.home().resolve(), "<home>")):
        for variante in {str(ruta), str(ruta).removeprefix("/private")}:  # macOS: /var es /private/var
            pares.append((variante.rstrip("/"), marca))
    return sorted(pares, key=lambda p: -len(p[0]))  # primero las más largas


def _texto(f: Path, pares) -> int:
    try:
        s = f.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 0
    n = sum(s.count(a) for a, _ in pares)
    if n:
        for a, b in pares:
            s = s.replace(a, b)
        f.write_text(s, encoding="utf-8")
    return n


def _sqlite(f: Path, pares) -> int:
    c = sqlite3.connect(f)
    n = 0
    for (tabla,) in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
        for col in c.execute(f"PRAGMA table_info({tabla})").fetchall():
            if col[2].upper() not in ("TEXT", ""):
                continue
            for a, b in pares:
                cur = c.execute(f"UPDATE {tabla} SET {col[1]} = replace({col[1]}, ?, ?) WHERE {col[1]} LIKE ?",
                                (a, b, f"%{a}%"))
                n += cur.rowcount
    c.commit()
    c.execute("VACUUM")  # que no queden los textos antiguos en páginas libres
    c.close()
    return n


def main(rutas: list[str]) -> None:
    pares = sustituciones()
    for r in rutas:
        total = 0
        ficheros = sorted(p for p in Path(r).rglob("*") if p.is_file() and not p.name.endswith(("-wal", "-shm")))
        for f in ficheros:  # la lista va antes: SQLite crea y borra -wal/-shm mientras trabaja
            total += _sqlite(f, pares) if f.suffix == ".db" else _texto(f, pares)
        print(f"{r}: {total} sustituciones")


if __name__ == "__main__":
    main(sys.argv[1:])
