import pytest

from medula import intencion
from medula.intencion import accion_de, solo_lectura

from .conftest import TAREAS


@pytest.mark.parametrize("cmd", [
    "ls app", "cat app/auth.py", "grep -rn fecha app/", "git diff", "git log --oneline -5", "git status",
    "uv run pytest -q", "uv run pytest -q 2>&1 | tail -40", "uv run python -m pytest tests", "find . -name '*.py'",
    "cd app && ls", "sed -n '1,20p' app/db.py", "rg login", "python -m pytest -q", "wc -l app/*.py",
    'find . -name conftest.py -not -path "*/.venv/*" -exec cat {} \\;', "find app -name '*.py' -exec grep -n login {} +",
])
def test_solo_lectura(cmd):
    assert solo_lectura(cmd)


@pytest.mark.parametrize("cmd", [
    "uv run ruff format .", "git checkout -- .", "git commit -m x", "rm reservas.db", "sed -i 's/a/b/' x.py",
    "echo hola > x.txt", "cat a >> b", "find . -delete", "find . -exec rm {} \\;", "uv add bcrypt",
    "python script.py", "ls $(rm x)", "mv a b", "git stash", "touch x",
])
def test_escritura(cmd):
    assert not solo_lectura(cmd)


def test_accion_edit(tmp_path):
    a = accion_de("Edit", {"file_path": str(tmp_path / "app/auth.py"), "old_string": "def login(u, p)",
                           "new_string": "def login(u, p, otp)"}, tmp_path)
    assert a.objetivo == "app/auth.py" and a.recurso == "app/auth.py" and a.escritura
    assert "- def login(u, p)" in a.cambio and "+ def login(u, p, otp)" in a.cambio


def test_accion_write_nuevo_y_existente(tmp_path):
    nuevo = accion_de("Write", {"file_path": str(tmp_path / "x.py"), "content": "print(1)\n"}, tmp_path)
    assert nuevo.cambio.startswith("(fichero nuevo)")
    (tmp_path / "y.py").write_text("a\nb\n")
    existente = accion_de("Write", {"file_path": str(tmp_path / "y.py"), "content": "a\nc\n"}, tmp_path)
    assert "-b" in existente.cambio and "+c" in existente.cambio


def test_accion_bash():
    lectura = accion_de("Bash", {"command": "uv run pytest -q", "description": "tests"}, None)
    assert lectura.recurso == "repo" and not lectura.escritura
    escritura = accion_de("Bash", {"command": "uv run ruff format ."}, None)
    assert escritura.escritura


def test_recorte_de_cambios_largos(tmp_path):
    a = accion_de("Edit", {"file_path": "x.py", "old_string": "a" * 5000, "new_string": "b"}, tmp_path)
    assert len(a.cambio) <= intencion.MAX_CAMBIO


def test_resumen_tarea():
    r = intencion.resumen_tarea(TAREAS, "T1")
    assert r.startswith("T1 — Segundo factor") and len(r) <= intencion.MAX_TAREA
    assert intencion.resumen_tarea(TAREAS, "T99") == "T99"


def test_estado_recorta_historial():
    a = accion_de("Bash", {"command": "uv run ruff format ."}, None)
    otros = [{"agente": "A2", "tarea": "t", "tiene": [], "intencion": "x" * 200_000}]
    est = intencion.estado("A1", "t", a, otros)
    assert len(est["otros_agentes"][0]["intencion"]) < 60_000


def test_simbolos_compartidos():
    from medula import simbolos
    accion = {"objetivo": "app/routes_export.py", "cambio": "session = login(username, password)"}
    otro = {"tarea": "T1 — Segundo factor. `login(username, password, otp)` con otp obligatorio",
            "intencion": "Edit app/auth.py: - def login(u, p)\n+ def login(u, p, otp)"}
    assert "login" in simbolos.compartidos(accion, otro)
    assert simbolos.compartidos({"objetivo": "README.md", "cambio": "Documentar la instalación"}, otro) == set()
