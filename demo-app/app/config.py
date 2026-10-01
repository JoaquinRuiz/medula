"""Configuración de la app de reservas."""
import os

# Usuarios de demo: nombre -> datos de acceso.
USERS = {
    "alice": {"password": "alice-pass"},
    "bob": {"password": "bob-pass"},
}

SALAS = ("Atlas", "Boreal", "Cierzo")


def db_path() -> str:
    return os.environ.get("MEDULA_DB_PATH", "reservas.db")
