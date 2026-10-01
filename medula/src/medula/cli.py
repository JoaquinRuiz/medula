"""Línea de órdenes: `medula servir` y `medula htop`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import CADENAS, Config


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="medula", description="Médula: kernel de coordinación de agentes")
    sub = p.add_subparsers(dest="orden", required=True)

    s = sub.add_parser("servir", help="arrancar el servidor")
    s.add_argument("--db", type=Path, required=True)
    s.add_argument("--decisor", choices=list(CADENAS), default="jev")
    s.add_argument("--raiz", type=Path, help="directorio de trabajo de los agentes")
    s.add_argument("--tareas", type=Path, help="carpeta con TN.md")
    s.add_argument("--plan", type=Path, help="plan.yaml con el grafo de tareas")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--puerto", type=int, default=8787)
    s.add_argument("--pregunta", choices=["choca", "direccional"], default="choca", help="pregunta de Jev")
    s.add_argument("--regla-simbolos", action="store_true", help="regla de símbolos compartidos antes de Jev")
    s.add_argument("--umbral-bajo", type=float, default=0.2)
    s.add_argument("--umbral-alto", type=float, default=0.8)
    s.add_argument("--umbral-aviso", type=float, default=0.5)
    s.add_argument("--espera-max", type=float, default=60.0)
    s.add_argument("--coste-sonnet", type=float, help="coste medio por decisión de Sonnet, para el htop")

    h = sub.add_parser("htop", help="interfaz de terminal sobre el SQLite")
    h.add_argument("--db", type=Path, required=True)
    h.add_argument("--coste-sonnet", type=float, help="coste medio por decisión de Sonnet")
    h.add_argument("--una-vez", action="store_true", help="pintar una vez y salir")
    h.add_argument("--log", type=Path, help="log de la ejecución: se muestran sus últimas líneas")
    h.add_argument("--mientras-pid", type=int, help="salir cuando termine este proceso")

    a = p.parse_args(argv)
    if a.orden == "servir":
        import uvicorn

        from . import plan
        from .servidor import crear_app

        config = Config(db=a.db, decisor=a.decisor, raiz=a.raiz, tareas_dir=a.tareas, plan=plan.cargar(a.plan),
                        pregunta=a.pregunta, regla_simbolos=a.regla_simbolos,
                        umbral_bajo=a.umbral_bajo, umbral_alto=a.umbral_alto, umbral_aviso=a.umbral_aviso,
                        espera_max=a.espera_max, coste_sonnet_por_decision=a.coste_sonnet)
        if config.decisor != "locks" and not config.openrouter_key:
            print("Falta OPENROUTER_API_KEY (usa uv run --env-file .env ...)", file=sys.stderr)
            return 2
        uvicorn.run(crear_app(config), host=a.host, port=a.puerto, log_level="warning")
        return 0
    from .htop import ejecutar

    return ejecutar(a.db, a.coste_sonnet, a.una_vez, a.log, a.mientras_pid)


if __name__ == "__main__":
    sys.exit(main())
