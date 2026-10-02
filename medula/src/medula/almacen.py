"""Estado de Médula en SQLite: agentes, locks, cola, buzón y log de decisiones."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS agentes (
    id TEXT PRIMARY KEY,
    tarea TEXT,
    session_id TEXT,
    estado TEXT NOT NULL DEFAULT 'trabajando',   -- trabajando | esperando | terminado
    espera_a TEXT,
    registrado REAL NOT NULL,
    ultima_accion TEXT,
    terminado REAL
);
CREATE TABLE IF NOT EXISTS locks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agente TEXT NOT NULL,
    recurso TEXT NOT NULL,                       -- ruta relativa, o 'repo' (Bash que escribe)
    intencion TEXT NOT NULL,                     -- JSON
    transitorio INTEGER NOT NULL DEFAULT 0,      -- 1: se libera al terminar la herramienta
    desde REAL NOT NULL,
    UNIQUE (agente, recurso)
);
CREATE TABLE IF NOT EXISTS cola (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agente TEXT NOT NULL,
    recurso TEXT NOT NULL,
    intencion TEXT NOT NULL,
    espera_a TEXT NOT NULL,
    prioridad REAL NOT NULL DEFAULT 0,           -- menor = antes
    desde REAL NOT NULL,
    estado TEXT NOT NULL DEFAULT 'esperando',    -- esperando | concedido | caducado | denegado
    hasta REAL
);
CREATE TABLE IF NOT EXISTS buzon (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    para TEXT NOT NULL,
    de TEXT,
    texto TEXT NOT NULL,
    p_invalida REAL,
    creado REAL NOT NULL,
    entregado REAL
);
CREATE TABLE IF NOT EXISTS decisiones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    tipo TEXT NOT NULL,                          -- acquire | notify | lento
    agente TEXT,
    accion TEXT,                                 -- JSON
    pregunta TEXT,
    estado_enviado TEXT,                         -- JSON
    respuesta TEXT,                              -- JSON en crudo
    veredicto TEXT,
    p_choca REAL,
    confianza REAL,
    latencia_ms REAL,
    coste_usd REAL,
    decisor TEXT,
    modelo TEXT,
    reserva_de TEXT,
    error TEXT,
    finish_reason TEXT                           -- del proveedor en las llamadas a LLM (stop, length…)
);
"""


def _j(v):
    return None if v is None else json.dumps(v, ensure_ascii=False)


class Almacen:
    """Acceso a SQLite seguro entre hilos (FastAPI atiende peticiones en un pool)."""

    def __init__(self, ruta: Path | str):
        self.ruta = str(ruta)
        self._lock = threading.RLock()
        self._c = sqlite3.connect(self.ruta, check_same_thread=False, isolation_level=None)
        self._c.row_factory = sqlite3.Row
        self._c.execute("PRAGMA journal_mode=WAL")
        self._c.executescript(ESQUEMA)
        # Bases de ejecuciones anteriores, creadas sin la columna finish_reason.
        if "finish_reason" not in {f[1] for f in self._c.execute("PRAGMA table_info(decisiones)")}:
            self._c.execute("ALTER TABLE decisiones ADD COLUMN finish_reason TEXT")

    def _q(self, sql: str, args=()):
        with self._lock:
            return self._c.execute(sql, args).fetchall()

    def _x(self, sql: str, args=()) -> int:
        with self._lock:
            return self._c.execute(sql, args).lastrowid

    # --- agentes ---
    def registrar(self, agente: str, tarea: str | None, session_id: str | None = None) -> None:
        with self._lock:
            fila = self._c.execute("SELECT id FROM agentes WHERE id = ?", (agente,)).fetchone()
            if fila:
                self._c.execute("UPDATE agentes SET tarea = COALESCE(?, tarea), session_id = COALESCE(?, session_id) "
                                "WHERE id = ?", (tarea, session_id, agente))
            else:
                self._c.execute("INSERT INTO agentes (id, tarea, session_id, registrado) VALUES (?, ?, ?, ?)",
                                (agente, tarea, session_id, time.time()))

    def agente(self, agente: str) -> dict | None:
        filas = self._q("SELECT * FROM agentes WHERE id = ?", (agente,))
        return dict(filas[0]) if filas else None

    def agentes(self) -> list[dict]:
        return [dict(f) for f in self._q("SELECT * FROM agentes ORDER BY id")]

    def activos(self, excepto: str | None = None) -> list[dict]:
        return [dict(f) for f in self._q("SELECT * FROM agentes WHERE estado != 'terminado' AND id != ? ORDER BY id",
                                          (excepto or "",))]

    def set_estado(self, agente: str, estado: str, espera_a: str | None = None) -> None:
        self._x("UPDATE agentes SET estado = ?, espera_a = ? WHERE id = ?", (estado, espera_a, agente))

    def set_ultima_accion(self, agente: str, texto: str) -> None:
        self._x("UPDATE agentes SET ultima_accion = ? WHERE id = ?", (texto, agente))

    def terminar(self, agente: str) -> None:
        with self._lock:
            self._c.execute("UPDATE agentes SET estado = 'terminado', espera_a = NULL, terminado = ? WHERE id = ?",
                            (time.time(), agente))
            self._c.execute("DELETE FROM locks WHERE agente = ?", (agente,))

    # --- locks ---
    def anadir_lock(self, agente: str, recurso: str, intencion: dict, transitorio: bool = False) -> None:
        self._x("INSERT INTO locks (agente, recurso, intencion, transitorio, desde) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (agente, recurso) DO UPDATE SET intencion = excluded.intencion, "
                "transitorio = MIN(locks.transitorio, excluded.transitorio)",
                (agente, recurso, _j(intencion), int(transitorio), time.time()))

    def liberar_transitorios(self, agente: str) -> None:
        self._x("DELETE FROM locks WHERE agente = ? AND transitorio = 1", (agente,))

    def locks(self, agente: str | None = None) -> list[dict]:
        if agente:
            filas = self._q("SELECT * FROM locks WHERE agente = ? ORDER BY desde", (agente,))
        else:
            filas = self._q("SELECT * FROM locks ORDER BY desde")
        return [{**dict(f), "intencion": json.loads(f["intencion"])} for f in filas]

    # --- cola ---
    def encolar(self, agente: str, recurso: str, intencion: dict, espera_a: str, prioridad: float) -> int:
        return self._x("INSERT INTO cola (agente, recurso, intencion, espera_a, prioridad, desde) VALUES (?, ?, ?, ?, ?, ?)",
                       (agente, recurso, _j(intencion), espera_a, prioridad, time.time()))

    def actualizar_espera(self, id_: int, espera_a: str) -> None:
        self._x("UPDATE cola SET espera_a = ? WHERE id = ?", (espera_a, id_))

    def cola_de(self, id_: int) -> dict | None:
        filas = self._q("SELECT * FROM cola WHERE id = ?", (id_,))
        return dict(filas[0]) if filas else None

    def cerrar_cola(self, id_: int, estado: str) -> None:
        self._x("UPDATE cola SET estado = ?, hasta = ? WHERE id = ?", (estado, time.time(), id_))

    def cola(self, solo_esperando: bool = True) -> list[dict]:
        sql = "SELECT * FROM cola" + (" WHERE estado = 'esperando'" if solo_esperando else "") + " ORDER BY prioridad, desde"
        return [dict(f) for f in self._q(sql)]

    # --- buzón ---
    def al_buzon(self, para: str, texto: str, de: str | None = None, p_invalida: float | None = None) -> int:
        return self._x("INSERT INTO buzon (para, de, texto, p_invalida, creado) VALUES (?, ?, ?, ?, ?)",
                       (para, de, texto, p_invalida, time.time()))

    def recoger_buzon(self, para: str) -> list[str]:
        with self._lock:
            filas = self._c.execute("SELECT id, texto FROM buzon WHERE para = ? AND entregado IS NULL ORDER BY id",
                                    (para,)).fetchall()
            ahora = time.time()
            for f in filas:
                self._c.execute("UPDATE buzon SET entregado = ? WHERE id = ?", (ahora, f["id"]))
        return [f["texto"] for f in filas]

    def buzon(self) -> list[dict]:
        return [dict(f) for f in self._q("SELECT * FROM buzon ORDER BY id")]

    # --- decisiones ---
    def registrar_decision(self, **kw) -> int:
        cols = ["ts", "tipo", "agente", "accion", "pregunta", "estado_enviado", "respuesta", "veredicto", "p_choca",
                "confianza", "latencia_ms", "coste_usd", "decisor", "modelo", "reserva_de", "error", "finish_reason"]
        kw.setdefault("ts", time.time())
        for k in ("accion", "estado_enviado", "respuesta"):
            if k in kw and not isinstance(kw[k], str):
                kw[k] = _j(kw[k])
        vals = [kw.get(c) for c in cols]
        return self._x(f"INSERT INTO decisiones ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)

    def decisiones(self, limite: int | None = None) -> list[dict]:
        sql = "SELECT * FROM decisiones ORDER BY id DESC" + (f" LIMIT {int(limite)}" if limite else "")
        return [dict(f) for f in self._q(sql)]
