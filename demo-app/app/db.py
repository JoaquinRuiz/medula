"""Acceso a SQLite. La base de datos se crea al arrancar; no hay migraciones."""
import sqlite3
from contextlib import contextmanager

from app import config
from app.models import Reserva, ReservaIn


@contextmanager
def conectar():
    conn = sqlite3.connect(config.db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with conectar() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reservas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sala TEXT NOT NULL,
                fecha TEXT NOT NULL,
                duracion_min INTEGER NOT NULL,
                usuario TEXT NOT NULL
            )
            """
        )


def insertar_reserva(r: ReservaIn, usuario: str) -> Reserva:
    with conectar() as conn:
        cur = conn.execute(
            "INSERT INTO reservas (sala, fecha, duracion_min, usuario) VALUES (?, ?, ?, ?)",
            (r.sala, r.fecha.isoformat(), r.duracion_min, usuario),
        )
        return Reserva(id=cur.lastrowid, usuario=usuario, **r.model_dump())


def listar_reservas() -> list[Reserva]:
    with conectar() as conn:
        filas = conn.execute(
            "SELECT id, sala, fecha, duracion_min, usuario FROM reservas ORDER BY fecha"
        ).fetchall()
    return [Reserva(**dict(f)) for f in filas]
