"""Saca el evento final "result" de una salida stream-json de Claude Code.

Es el mismo objeto que da --output-format json (coste, turnos, session_id...).
Si no hay evento final (el agente murió a medias), escribe un error.
"""
import json
import sys

resultado = None
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        for linea in f:
            try:
                evento = json.loads(linea)
            except ValueError:
                continue
            if evento.get("type") == "result":
                resultado = evento
except OSError:
    pass
json.dump(resultado or {"is_error": True, "result": "sin evento result en el stream"}, sys.stdout, ensure_ascii=False)
sys.stdout.write("\n")
