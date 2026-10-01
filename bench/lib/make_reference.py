"""Genera las soluciones de referencia de reference/.

- reference/tasks/TN.patch: cada tarea hecha en aislamiento sobre el commit
  base, como la haría un agente que no sabe nada de las demás (T2 llama a
  login con la firma antigua, T4 filtra por `fecha`).
- reference/all_tasks.patch: las seis tareas integradas bien (T2 con OTP, T4
  sobre `inicio`).

Uso: make_reference.py <workspace-base>   (un repo recién preparado)
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def git(ws: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(ws), *args], check=True, capture_output=True, text=True).stdout


def edit(ws: Path, rel: str, *pairs: tuple[str, str]) -> None:
    p = ws / rel
    s = p.read_text()
    for old, new in pairs:
        if old not in s:
            raise SystemExit(f"{rel}: no encuentro {old[:60]!r}")
        s = s.replace(old, new, 1)
    p.write_text(s)


def write(ws: Path, rel: str, content: str) -> None:
    (ws / rel).write_text(content.lstrip("\n"))


# --- Cada tarea en aislamiento -----------------------------------------------

def t1(ws: Path) -> None:
    edit(ws, "app/config.py",
         ('"alice": {"password": "alice-pass"}', '"alice": {"password": "alice-pass", "otp_secret": "JBSWY3DPEHPK3PXP"}'),
         ('"bob": {"password": "bob-pass"}', '"bob": {"password": "bob-pass", "otp_secret": "KRSXG5CTMVRXEZLU"}'))
    edit(ws, "app/auth.py",
         ("import secrets\nfrom dataclasses import dataclass\n",
          "import secrets\nimport sys\nfrom dataclasses import dataclass\n\nimport pyotp\nfrom fastapi import Header\n"),
         ('def login(username: str, password: str) -> Session:\n    """Valida las credenciales y abre una sesión. Lanza AuthError si no son válidas."""\n',
          '''def verificar_otp(username: str, code: str) -> bool:
    """Comprueba un código TOTP (RFC 6238, 30 s, ±1 paso). Sustituible en tests."""
    user = USERS.get(username)
    return bool(user and code) and pyotp.TOTP(user["otp_secret"]).verify(code, valid_window=1)


def otp_header(x_otp: str = Header(default="")) -> str:
    """Dependencia de FastAPI que lee el OTP de la cabecera X-OTP.

    Regla general: todo endpoint HTTP que autentique con usuario y contraseña
    exige además el OTP. En POST /login va en el campo `otp` del body; en
    cualquier otro endpoint, en la cabecera X-OTP (léela con esta dependencia).
    """
    return x_otp


def login(username: str, password: str, otp: str) -> Session:
    """Valida credenciales y OTP y abre una sesión. Lanza AuthError si no son válidos."""
'''),
         ('        raise AuthError("credenciales invalidas")\n    session',
          '        raise AuthError("credenciales invalidas")\n'
          '    if not sys.modules[__name__].verificar_otp(username, otp):\n'
          '        raise AuthError("otp invalido")\n    session'))
    edit(ws, "app/routes_auth.py",
         ("    password: str\n", "    password: str\n    otp: str = \"\"\n"),
         ("login(body.username, body.password)", "login(body.username, body.password, body.otp)"))
    edit(ws, "tests/conftest.py",
         ("import pytest\n", "import pyotp\nimport pytest\n"),
         ('json={"username": "alice", "password": "alice-pass"}',
          'json={"username": "alice", "password": "alice-pass", "otp": pyotp.TOTP("JBSWY3DPEHPK3PXP").now()}'))
    write(ws, "tests/test_auth.py", '''
import pyotp
import pytest

from app.auth import AuthError, get_session, login

ALICE = pyotp.TOTP("JBSWY3DPEHPK3PXP")


def test_login_correcto_abre_sesion():
    s = login("alice", "alice-pass", ALICE.now())
    assert s.username == "alice"
    assert get_session(s.token) == s


def test_login_incorrecto():
    with pytest.raises(AuthError):
        login("alice", "mal", ALICE.now())
    with pytest.raises(AuthError):
        login("alice", "alice-pass", "")


def test_endpoint_login(client):
    otp = pyotp.TOTP("KRSXG5CTMVRXEZLU").now()
    assert client.post("/login", json={"username": "bob", "password": "bob-pass", "otp": otp}).status_code == 200
    assert client.post("/login", json={"username": "bob", "password": "bob-pass"}).status_code == 401
''')


def t2(ws: Path) -> None:
    write(ws, "app/routes_export.py", '''
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app import db
from app.auth import AuthError, login
from app.models import Reserva

router = APIRouter()
basic = HTTPBasic(auto_error=False)


@router.get("/export")
def export(cred: HTTPBasicCredentials | None = Depends(basic)) -> Response:
    if cred is None:
        raise HTTPException(status_code=401)
    try:
        login(cred.username, cred.password)
    except AuthError:
        raise HTTPException(status_code=401)
    columnas = list(Reserva.model_fields)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columnas)
    for r in db.listar_reservas():
        d = r.model_dump(mode="json")
        w.writerow([d[c] for c in columnas])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8")
''')
    edit(ws, "app/main.py",
         ("routes_auth, routes_consulta, routes_reservas", "routes_auth, routes_consulta, routes_export, routes_reservas"),
         ("app.include_router(routes_consulta.router)\n",
          "app.include_router(routes_consulta.router)\napp.include_router(routes_export.router)\n"))
    write(ws, "tests/test_export.py", '''
from app.models import Reserva


def test_export_vacio_solo_cabecera(client):
    r = client.get("/export", auth=("alice", "alice-pass"))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.strip() == ",".join(Reserva.model_fields)


def test_export_sin_credenciales(client):
    assert client.get("/export").status_code == 401
    assert client.get("/export", auth=("alice", "mal")).status_code == 401
''')


def t3(ws: Path) -> None:
    for rel in ("app/models.py", "app/db.py", "app/routes_reservas.py", "tests/test_reservas.py"):
        p = ws / rel
        p.write_text(p.read_text().replace("fecha", "inicio"))


CONSULTAS = '''
"""Consultas de lectura con filtros."""
from app.db import conectar
from app.models import Reserva


def listar_reservas_desde(desde: str) -> list[Reserva]:
    with conectar() as conn:
        filas = conn.execute(
            "SELECT * FROM reservas WHERE {campo} >= ? ORDER BY {campo}", (desde,)
        ).fetchall()
    return [Reserva(**dict(f)) for f in filas]
'''


def t4(ws: Path, campo: str = "fecha") -> None:
    write(ws, "app/consultas.py", CONSULTAS.replace("{campo}", campo))
    write(ws, "app/routes_consulta.py", '''
"""Consulta pública de reservas."""
from datetime import date

from fastapi import APIRouter

from app import consultas, db
from app.models import Reserva

router = APIRouter()


@router.get("/reservas")
def listar_reservas(desde: date | None = None) -> list[Reserva]:
    if desde is None:
        return db.listar_reservas()
    return consultas.listar_reservas_desde(desde.isoformat())
''')
    write(ws, "tests/test_consulta.py", f'''
def _crear(client, auth, dia):
    r = client.post("/reservas", json={{"sala": "Atlas", "{campo}": dia + "T10:00", "duracion_min": 60}}, headers=auth)
    assert r.status_code == 201


def test_filtro_desde(client, auth):
    for dia in ("2026-10-05", "2026-10-06", "2026-10-08"):
        _crear(client, auth, dia)
    r = client.get("/reservas", params={{"desde": "2026-10-06"}})
    assert [x["{campo}"][:10] for x in r.json()] == ["2026-10-06", "2026-10-08"]


def test_filtro_formato_invalido(client):
    assert client.get("/reservas", params={{"desde": "06-10-2026"}}).status_code == 422
''')


def t5(ws: Path) -> None:
    edit(ws, "app/validators.py",
         ('raise ValidationError("sala requerida")', 'raise ValidationError("La sala es obligatoria.")'),
         ('raise ValidationError("sala invalida")',
          'raise ValidationError(\n            f"La sala «{sala}» no existe. Salas disponibles: {\', \'.join(SALAS)}."\n        )'))
    edit(ws, "tests/test_validators.py",
         ('[("", "sala requerida"), ("Delta", "sala invalida")]',
          '[("", "La sala es obligatoria."), ("Delta", "La sala «Delta» no existe. Salas disponibles: Atlas, Boreal, Cierzo.")]'),
         ('match=f"^{mensaje}$"', "match=f\"^{re.escape(mensaje)}$\""),
         ("from datetime import datetime\n", "import re\nfrom datetime import datetime\n"))


def t6(ws: Path) -> None:
    edit(ws, "app/validators.py",
         ("from datetime import datetime\n", "from datetime import datetime, timedelta\n"),
         ('        raise ValidationError("minutos invalidos")\n',
          '        raise ValidationError("minutos invalidos")\n'
          '    fin = fecha + timedelta(minutes=duracion_min)\n'
          '    if fecha.hour < 8 or fin > fecha.replace(hour=20, minute=0):\n'
          '        raise ValidationError("fuera de horario (8:00-20:00)")\n'))
    p = ws / "tests/test_validators.py"
    p.write_text(p.read_text() + '''

@pytest.mark.parametrize("hora,minuto,duracion", [(7, 30, 60), (19, 30, 60)])
def test_horario_fuera_de_franja(hora, minuto, duracion):
    with pytest.raises(ValidationError, match="^fuera de horario"):
        validar_horario(datetime(2026, 10, 5, hora, minuto), duracion)
''')


TASKS = {"T1": t1, "T2": t2, "T3": t3, "T4": t4, "T5": t5, "T6": t6}


def integrate(ws: Path) -> None:
    """Lo que hace una integración correcta sobre las seis tareas aisladas."""
    edit(ws, "app/routes_export.py",
         ("from app.auth import AuthError, login\n", "from app.auth import AuthError, login, otp_header\n"),
         ("def export(cred: HTTPBasicCredentials | None = Depends(basic)) -> Response:",
          "def export(\n    cred: HTTPBasicCredentials | None = Depends(basic), otp: str = Depends(otp_header)\n) -> Response:"),
         ("login(cred.username, cred.password)", "login(cred.username, cred.password, otp)"))
    edit(ws, "tests/test_export.py",
         ('r = client.get("/export", auth=("alice", "alice-pass"))',
          'r = client.get("/export", auth=("alice", "alice-pass"), headers={"X-OTP": pyotp.TOTP("JBSWY3DPEHPK3PXP").now()})'),
         ("from app.models import Reserva\n", "import pyotp\n\nfrom app.models import Reserva\n"))
    t4(ws, campo="inicio")


def main(base: Path) -> None:
    out = ROOT / "reference"
    (out / "tasks").mkdir(parents=True, exist_ok=True)
    base_sha = git(base, "rev-parse", "HEAD").strip()
    for name, fn in TASKS.items():
        git(base, "checkout", "-q", "-B", f"ref/{name}", base_sha)
        fn(base)
        git(base, "add", "-A")
        (out / "tasks" / f"{name}.patch").write_text(git(base, "diff", "--cached", base_sha))
        git(base, "commit", "-q", "-m", name)
    git(base, "checkout", "-q", "-B", "ref/all", base_sha)
    for name in TASKS:
        git(base, "merge", "-q", "--no-ff", "-m", f"merge {name}", f"ref/{name}")
    integrate(base)
    git(base, "add", "-A")
    git(base, "commit", "-q", "-m", "integración")
    (out / "all_tasks.patch").write_text(git(base, "diff", base_sha, "HEAD"))
    print(f"escritos reference/tasks/T1-T6.patch y reference/all_tasks.patch desde {base_sha[:7]}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
