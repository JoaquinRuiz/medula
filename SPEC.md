# SPEC — medula (fase E-00)

Laboratorio para medir cómo se coordinan varios agentes de código que trabajan a la vez sobre el mismo repositorio. Esta spec cubre solo la fase E-00: la app de demo, las seis tareas, los tests de aceptación, la verdad de referencia y los scripts de banco del modo B. El kernel (`medula/`) llega en E-06 con su propia spec.

Estado: **aprobada** el 2026-09-28, con las decisiones de la sección 8.

---

## 0. Entorno

- **Todo el Python con `uv`**, sin `pip` ni `requirements.txt`, con Python 3.12 (`.python-version`); el del sistema (3.9) no se usa. Hay dos proyectos uv:
  - `demo-app/` es un **proyecto propio** con su `pyproject.toml` y su `uv.lock` (`package = false`). Como cada workspace es una copia de `demo-app/`, agentes y evaluación ejecutan `uv run pytest` en él con su propio entorno.
  - La raíz es el proyecto de las herramientas de `bench/` (`pyyaml`, `httpx2`). Los scripts de bash llaman a Python con `uv run --project <medula> python` (función `py` de `bench/lib/common.sh`), nunca con `python3`.
- Dependencias de `demo-app/`: `fastapi`, `uvicorn` y `pyotp`, más `pytest` y `httpx2` en el grupo `dev`. `httpx2` es para `TestClient`, porque Starlette marca `httpx` como obsoleto.
  - `pyotp` se instala desde el principio aunque la app inicial no lo use: así T1 no depende de instalar paquetes y el entorno es idéntico en todos los modos.
- **Modelos vía OpenRouter**: la clave va en `.env` (`OPENROUTER_API_KEY`, en `.gitignore`), con un `.env.example` versionado. Los agentes de Claude Code del modo B apuntan a OpenRouter con `ANTHROPIC_BASE_URL=https://openrouter.ai/api`, `ANTHROPIC_AUTH_TOKEN=$OPENROUTER_API_KEY` y `ANTHROPIC_API_KEY=""`, y los modelos se nombran con el id de OpenRouter (p. ej. `anthropic/claude-sonnet-5`). Los decisores de E-03/E-06 usarán la misma clave.
- SQLite con el módulo `sqlite3` de la librería estándar, sin ORM. Es intencionado: el renombrado de T3 tiene que tocar a mano modelo, SQL y API, que es donde se produce el choque con T4.

## 1. `demo-app/` — API de reservas de salas (estado inicial)

### 1.1 Estructura

```
demo-app/
  app/
    __init__.py
    main.py             # crea la app FastAPI e incluye los routers
    config.py           # ruta de la BD (env MEDULA_DB_PATH), usuarios y salas de demo
    db.py               # conexión, init_db() con CREATE TABLE, insertar/listar reservas
    auth.py             # login(username, password) -> Session; sesiones en memoria
    models.py           # Reserva, ReservaIn (pydantic)
    validators.py       # validar_sala(), validar_horario()
    routes_auth.py      # POST /login
    routes_reservas.py  # POST /reservas (escritura, con sesión)
    routes_consulta.py  # GET /reservas (lectura pública)
  tests/
    conftest.py         # BD temporal por test, TestClient
    test_auth.py
    test_reservas.py
    test_validators.py
  pyproject.toml        # proyecto uv propio; incluye la config de pytest
  uv.lock
  .python-version
  .gitignore
  README.md
```

La separación en ficheros es deliberada: cada par que choca tiene que tocar **ficheros distintos** que comparten un contrato, para que git fusione limpio y el choque solo sea visible en el comportamiento.
- T1 toca `auth.py`, `routes_auth.py` y `config.py`; T2 crea `routes_export.py` y lo registra en `main.py`. Comparten la firma de `login`.
- T3 toca `models.py`, `db.py` y `routes_reservas.py`; T4 crea `consultas.py` y cambia `routes_consulta.py`. Comparten el nombre de la columna.
- Por eso `GET /reservas` vive aparte de `POST /reservas`, y T4 no puede tocar `db.py`.

### 1.2 Piezas obligatorias

**`app/auth.py`**
- `USERS` en `config.py`: `alice` / `alice-pass` y `bob` / `bob-pass`.
- `Session` (dataclass): `token: str`, `username: str`.
- `login(username: str, password: str) -> Session`: si las credenciales son válidas, crea un token aleatorio, lo guarda en un dict en memoria y devuelve la sesión; si no, lanza `AuthError`.
- `get_session(token: str) -> Session | None`.

**`app/models.py`**
- `ReservaIn`: `sala: str`, `fecha: datetime` (inicio de la reserva, ISO 8601 `AAAA-MM-DDTHH:MM`), `duracion_min: int`.
- `Reserva(ReservaIn)`: añade `id: int` y `usuario: str`.

**`app/db.py`**
- Tabla `reservas(id INTEGER PK, sala TEXT, fecha TEXT, duracion_min INTEGER, usuario TEXT)`.
- `init_db()`, `insertar_reserva(r) -> Reserva`, `listar_reservas() -> list[Reserva]` (ordenadas por `fecha`).
- No hay migraciones: la BD se crea al arrancar. Los tests usan una BD temporal.

**`app/validators.py`** — dos funciones independientes, separadas en el fichero por un bloque de código que ninguna tarea toca (constantes y un helper), para que T5 y T6 editen trozos no contiguos y git pueda fusionarlos sin conflicto textual.
- `validar_sala(sala: str) -> None`, lanza `ValidationError` con:
  - `"sala requerida"` si está vacía.
  - `"sala invalida"` si no está en `SALAS` (`Atlas`, `Boreal`, `Cierzo`).
- `validar_horario(fecha: datetime, duracion_min: int) -> None`, lanza `ValidationError` con:
  - `"duracion invalida"` si `duracion_min <= 0` o `> 240`.
  - `"minutos invalidos"` si la hora de inicio no cae en `:00` o `:30`.
- Los mensajes iniciales son deliberadamente escuetos: T5 los reescribe.

**Endpoints**
- `POST /login` — body `{"username", "password"}` → `200 {"token"}` o `401`.
- `POST /reservas` — cabecera `Authorization: Bearer <token>`, body `ReservaIn` → `201 Reserva`; `401` sin sesión válida; `422 {"detail": "<mensaje del validador>"}` si falla una validación.
- `GET /reservas` — sin autenticación → `200 [Reserva, ...]`.

### 1.3 Tests propios

Cubren login correcto e incorrecto, crear y listar reservas, las cuatro ramas de error de los validadores y el `401`. Terminado: `pytest` en verde dentro de `demo-app/`.

## 2. `tasks/` — seis tareas

Un fichero por tarea (`T1.md` … `T6.md`), redactado como lo recibiría un agente: **Objetivo**, **Contexto**, **Alcance** (qué ficheros y comportamiento cambian y qué queda fuera) y **Criterios de aceptación** concretos y comprobables. Ninguna menciona a las demás. Cada una pide dejar los tests del repo en verde y añadir los suyos.

| Tarea | Contrato que fija (lo que comprueban los tests de aceptación) |
|---|---|
| **T1** | `login(username, password, otp)` con `otp` obligatorio, TOTP (RFC 6238, `pyotp`, 30 s). Cada usuario de `USERS` gana un `otp_secret` (`alice`: `JBSWY3DPEHPK3PXP`, `bob`: `KRSXG5CTMVRXEZLU`). OTP inválido o ausente → `AuthError`. **Regla general:** todo punto de entrada HTTP que autentique con usuario y contraseña exige además el OTP, en `POST /login` como campo `otp` del body y en cualquier otro endpoint en la cabecera `X-OTP`. **La regla vive en código, no solo en T1.md:** T1 deja en `app/auth.py` una pieza reutilizable, `otp_header()` (dependencia de FastAPI que lee `X-OTP`), con un docstring que enuncia la regla, y un verificador inyectable `verificar_otp(username, code)` que `login()` usa por dentro. Los secretos de los usuarios de demo quedan en `config.py` para que los tests generen códigos válidos. |
| **T2** | `GET /export` con HTTP Basic (`username:password`). Valida llamando a `login(username, password)` de `app/auth.py`, no reimplementando la comprobación. Devuelve `text/csv` con una fila por reserva, leídas con `db.listar_reservas()`; las columnas son los campos del modelo `Reserva` en su orden de declaración (hoy `sala,fecha,duracion_min,id,usuario`, porque `Reserva` hereda de `ReservaIn`), sacados de `Reserva.model_fields` y no escritos a mano. `401` si las credenciales fallan. Nuevo fichero `app/routes_export.py` registrado en `main.py`. |
| **T3** | Renombra `fecha` → `inicio` en `models.py`, en la columna de la tabla y en el JSON de la API (entrada y salida). No hay datos que migrar. Tras el cambio, `fecha` no aparece en la API. |
| **T4** | `GET /reservas?desde=AAAA-MM-DD` (en `routes_consulta.py`) devuelve solo las reservas con `fecha >= desde 00:00`, filtrando en SQL (`WHERE fecha >= ?`) en un módulo nuevo `app/consultas.py`. No toca `db.py` ni los modelos. Formato inválido → `422`. Sin parámetro, igual que ahora. |
| **T5** | Reescribe solo los mensajes de `validar_sala()`: `"La sala es obligatoria."` y `"La sala «<nombre>» no existe. Salas disponibles: Atlas, Boreal, Cierzo."`. No toca `validar_horario()`. |
| **T6** | Añade a `validar_horario()` la regla de franja: la reserva empieza a las 8:00 o después y termina a las 20:00 o antes; si no, `"fuera de horario (8:00-20:00)"`. No toca `validar_sala()`. |

Por qué chocan:
- **T1 × T2**: T2 se escribe contra `login(username, password)`. Con T1 aplicado, esa llamada rompe (`TypeError` → 500) y además `/export` queda sin segundo factor, lo que viola la regla general de T1. Ficheros distintos, mismo contrato.
- **T3 × T4**: T4 filtra por la columna `fecha`, que T3 ha renombrado a `inicio`; con las dos aplicadas, el filtro rompe en SQL (`no such column: fecha`). Ficheros distintos, mismo contrato.
- **T2 × T3 no chocan**, y es a propósito: T2 deriva las columnas del modelo y lee con `listar_reservas()`, así que el renombrado de T3 se propaga solo. T3.md deja `validators.py` fuera de su alcance, para no pisar a T6.
- **T5 × T6**: mismo fichero, trozos distintos y sin relación. Git las fusiona limpias.
- **Alcance de la verdad de referencia**: se define sobre el contrato del producto, que es lo que miden los tests de aceptación. Los tests unitarios que escribe cada agente pueden romperse por un renombrado ajeno (un test de T6 que cree reservas con `fecha` falla tras T3) sin que eso cuente como choque. Para reducir ese ruido, T2 compara la cabecera con `Reserva.model_fields`, y el test de `demo-app` del 422 no mira el texto del mensaje.
- **Verificación**: `bench/self_check.sh`, con una solución de referencia por tarea hecha en aislamiento (`reference/tasks/TN.patch`, generada con `bench/lib/make_reference.py`), comprueba que:
  - cada tarea se puede hacer sola;
  - los 15 pares se fusionan sin conflicto textual;
  - el merge de las seis deja en rojo exactamente T2, T4 e integración;
  - la integración correcta (`reference/all_tasks.patch`) pasa todo.

## 3. `acceptance/` — tests de aceptación

```
acceptance/
  conftest.py            # BD temporal, TestClient, helpers: otp(usuario), token(usuario), crear_reserva(...)
  test_t1.py … test_t6.py
  test_integration.py
```

- **Los tests se evalúan siempre sobre el estado final, con las seis tareas aplicadas.** Por eso escriben contra el contrato final: todo test que autentica manda el OTP (`otp` en `POST /login`, `X-OTP` en el resto), y las reservas usan `inicio`.
  - Consecuencia buscada: si en el estado final falta T3, también cae `test_t4.py`. Eso mide el sistema integrado, no cada rama por separado.
- Cada `test_tN.py` concentra los criterios de aceptación de su tarea, y `test_integration.py` añade los cruces:
  - `GET /export` con Basic **y** `X-OTP` válido → 200 y CSV con cabecera `sala,inicio,duracion_min,id,usuario`; sin `X-OTP` o con OTP inválido → 401.
  - Crear reservas con `inicio`: `GET /reservas?desde=…` filtra bien y el JSON no contiene `fecha`.
  - Los mensajes nuevos de `validar_sala()` y la regla 8:00–20:00 de `validar_horario()` conviven.
- Todos los tests de las seis tareas y los de integración fallan sobre la app inicial.
- Esta carpeta **nunca** se copia a un espacio de trabajo de agentes. Solo la copia `evaluate.sh`, después de que los agentes terminen, y la borra al acabar.

## 4. `ground_truth.yaml`

```yaml
version: 1
tasks: [T1, T2, T3, T4, T5, T6]
pairs:
  - {a: T1, b: T2, conflict: true,  type: semantic, reason: "..."}
  - {a: T3, b: T4, conflict: true,  type: semantic, reason: "..."}
  - {a: T5, b: T6, conflict: false, type: false_positive_same_file, reason: "..."}
  # los 12 pares restantes: conflict: false, type: none
```

Los 15 pares C(6,2), con `a < b`, cada uno con su motivo en una línea. `bench/lib/check_ground_truth.py` comprueba la cobertura y las etiquetas.

## 5. `bench/`

Scripts en bash con `set -euo pipefail`; la lógica no trivial va en Python dentro de `bench/lib/` y se ejecuta con `uv run`.

### 5.0 Dónde se trabaja y aislamiento de los agentes
- **Workspaces**: `${MEDULA_RUNS_DIR:-$TMPDIR/medula-runs}/<run-id>/`, fuera del repo, para que ningún agente llegue a `acceptance/` ni a `ground_truth.yaml` subiendo carpetas. `MEDULA_RUNS_DIR` permite elegir otra ruta, por ejemplo una más corta.
- **Comprobación de CLAUDE.md**: antes de crear nada, `bench/lib/common.sh` recorre todos los directorios padre de la ruta elegida y aborta si encuentra un `CLAUDE.md` o un `.claude/`. También aborta si la ruta queda dentro del repo `medula`.
  - Comprobado el 2026-09-28: no hay ninguno en los padres de `$TMPDIR` (`/var/folders/9x/…/T/`).
- **Config de Claude Code limpia**: cada run usa `CLAUDE_CONFIG_DIR=<run>/claude-config`, vacío. Si no, los agentes heredarían los plugins, skills, MCP, hooks y memoria de la config del usuario (`~/.claude`), y los modos no serían comparables.
  - Comprobado: con una config vacía y `ANTHROPIC_AUTH_TOKEN`, `claude -p` funciona sin login.
- **Evidencia persistente**: al terminar cada run, pase lo que pase (con `trap`), se copia a `results/runs/<run-id>/`:
  - los logs y JSON de cada agente y de cada resolución de conflicto;
  - `final.diff`, el diff final contra el commit base;
  - `evaluation.json` y `mode_b.json`.
  
  `results/runs/` se versiona, porque es la evidencia publicada del experimento.

### 5.1 `prepare_workspace.sh <destino>`
Copia `demo-app/` a `<destino>` (que no debe existir), hace `git init -b main`, fija el usuario de git local (`medula-bench`) y hace un commit base `base: demo-app initial state`. Imprime la ruta.

### 5.2 `evaluate.sh <workspace> [salida.json]`
1. Copia `acceptance/` a `<workspace>/_acceptance/`.
2. Ejecuta `uv run pytest _acceptance --junitxml=…` con `cwd` en el workspace (su proyecto uv) y `PYTHONPATH=<workspace>`.
3. Borra `_acceptance/` con `trap`, también si algo falla.
4. Escribe un JSON:
   ```json
   {"workspace": "...", "timestamp": "...",
    "tasks": {"T1": {"passed": 0, "failed": 4, "failed_tests": ["..."]}, "...": {}},
    "integration": {"passed": 0, "failed": 5, "failed_tests": ["..."]},
    "total": {"passed": 0, "failed": 30}}
   ```
   Sale con código 0 si pytest se pudo ejecutar, aunque haya tests en rojo; los resultados van en el JSON. Solo sale con error si falla la evaluación misma.

### 5.3 Agentes: modelo, esfuerzo y OpenRouter
- **Modelo de los agentes: `anthropic/claude-sonnet-5 · effort high`**, igual en todos los modos. Van en `.env` (`MEDULA_AGENT_MODEL`, `MEDULA_AGENT_EFFORT`) y se pueden cambiar con `--model` y `--effort`.
- **Cómo se pasa el esfuerzo** (verificado el 2026-09-28 con Claude Code 2.1.283, capturando las peticiones con un proxy local):
  - El flag `--effort high` sale en el body de `POST /v1/messages` como `"output_config": {"effort": "high"}`, con la beta `effort-2025-11-24` en `anthropic-beta` y `"thinking": {"type": "adaptive"}`. Lo mismo pasa con `ANTHROPIC_BASE_URL` apuntando a otro host.
  - La variable de entorno `CLAUDE_EFFORT` **no tiene efecto**: con `low` o `medium` se siguió enviando `high`. El script la quita del entorno (`env -u`) y pasa siempre `--effort` explícito.
  - **Lo que queda sin verificar** es que OpenRouter reenvíe `output_config.effort` a Anthropic. Su guía de Claude Code no lo menciona, y hay informes de que acepta el esfuerzo de nivel superior pero no el de dentro de cada mensaje. Para cerrarlo, `bench/check_openrouter.sh` (necesita la clave):
    1. Llama directamente a `https://openrouter.ai/api/v1/messages` con el mismo `output_config` en `low` y en `high` sobre un problema de razonamiento, y compara los tokens de salida y razonamiento que devuelve `GET /api/v1/generation?id=…`.
    2. Manda un valor de esfuerzo inválido para ver si OpenRouter lo valida o lo ignora.
    3. Hace un `claude -p` de humo por OpenRouter con `--effort high`.
    
    Escribe `results/openrouter_check.json`. `run_mode_b.sh` exige que exista y diga `effort_passthrough: true`, salvo con `--skip-effort-check`, que queda anotado en el JSON del run.
- **Lanzamiento** (flags comprobados en `claude --help`):
  ```
  env -u CLAUDE_EFFORT CLAUDE_CONFIG_DIR=<run>/claude-config \
      ANTHROPIC_BASE_URL=https://openrouter.ai/api ANTHROPIC_AUTH_TOKEN=$OPENROUTER_API_KEY ANTHROPIC_API_KEY="" \
      claude -p "<prompt>" --model "$MODEL" --effort "$EFFORT" \
             --permission-mode bypassPermissions --output-format json
  ```
  con `cwd` en su clon y stdin redirigido desde `/dev/null` (si no, `claude -p` espera 3 s a que llegue algo por stdin). El `total_cost_usd` que devuelve Claude Code sale de la tarifa de Anthropic; el coste real se cuadra después con OpenRouter, y se guarda el `session_id` para cruzarlo.

### 5.4 `run_mode_b.sh [--model M] [--effort E] [--run-id ID] [--skip-effort-check]`
Modo B: ramas y merge al final.

1. Comprobaciones: existe `.env` con la clave, no hay CLAUDE.md en la ruta (5.0) y existe `openrouter_check.json`.
2. `prepare_workspace.sh` crea `<run>/repo`, el repo base del run.
3. Un **clon independiente** por tarea, en `<run>/ws-TN`, con la rama `task/TN` y sin remoto, todos desde el commit base. No son worktrees porque en un worktree `git log --all` deja ver las ramas de las demás tareas.
   - Cada clon hace `uv sync --frozen` desde su propio `uv.lock`, así que su `.venv` vive dentro del clon (ignorada por git) y nada en el entorno ni en el prompt apunta al repo `medula`.
4. **Ronda 1**: T1–T4 en paralelo. **Ronda 2**: T5 y T6 en paralelo, cuando termina la ronda 1. Las ramas de la ronda 2 también salen del commit base, porque en el modo B nadie ve el trabajo de los demás hasta el merge.
   - El prompt es el contenido de `tasks/TN.md` más una instrucción fija: trabaja solo en este directorio, ejecuta los tests con `uv run pytest` y haz commit al terminar.
   - Si el agente no hace commit, el script hace commit de lo que quede.
5. **Merge con resolución por agente**: en `main` del repo base, `git merge --no-ff task/TN` en orden T1…T6. Si una rama da conflicto textual:
   1. Se lanza un agente de Claude Code sin interacción, con el mismo modelo, esfuerzo y aislamiento, y `cwd` en el repo base en estado de merge. Su prompt incluye los textos de **las dos tareas implicadas** (la de la rama que entra y la o las tareas ya fusionadas que tocaron las mismas líneas, sacadas de `git log` sobre los ficheros en conflicto) y la lista de ficheros en conflicto. Se le pide resolver conservando la intención de ambas, ejecutar los tests y cerrar el merge con commit.
   2. Verificación: no quedan marcadores `<<<<<<<`/`=======`/`>>>>>>>` en ningún fichero versionado, el merge está cerrado y la app arranca (`uv run python -c "import app.main"` y un `GET /reservas` con `TestClient`).
   3. Si la verificación falla: `git merge --abort` (o `reset --hard` al commit anterior al merge), la tarea se marca como `failed_merge` y se sigue con la siguiente.
   
   El tiempo y el coste de estos agentes se suman a los del modo B.
6. `final.diff` contra el commit base, `evaluate.sh` sobre `main` y copia de la evidencia (5.0).
7. `results/runs/<run-id>/mode_b.json`:
   ```json
   {"mode": "B", "run_id": "...", "model": "anthropic/claude-sonnet-5", "effort": "high",
    "d61": "anthropic/claude-sonnet-5 · effort high", "claude_version": "2.1.283",
    "effort_check": "passed|skipped", "started_at": "...", "wall_time_s": 0,
    "rounds": [{"tasks": ["T1","T2","T3","T4"], "wall_time_s": 0}, {"tasks": ["T5","T6"], "wall_time_s": 0}],
    "agents": {"T1": {"exit_code": 0, "cost_usd": 0, "num_turns": 0, "duration_s": 0, "session_id": "...", "committed_by": "agent|script"}},
    "merge": {
      "order": ["T1","T2","T3","T4","T5","T6"],
      "merged": ["T1","T2","T3","T5","T6"],
      "failed": ["T4"],
      "textual_conflicts": [
        {"branch": "task/T4", "task": "T4", "against": ["T3"], "files": ["app/db.py"],
         "resolved": false, "resolver": {"cost_usd": 0, "duration_s": 0, "num_turns": 0, "exit_code": 0},
         "failure_reason": "conflict markers left"}],
      "textual_conflict_count": 1, "resolved_count": 0},
    "totals": {"agents_cost_usd": 0, "resolver_cost_usd": 0, "cost_usd": 0},
    "evaluation": {"...": "salida de evaluate.sh"}}
   ```
   De aquí salen los conflictos de git (`textual_conflicts`), los tests en rojo y el tiempo total (`wall_time_s`, que incluye las resoluciones).

**No se ejecuta en E-00.** Solo se entrega escrito y con `bash -n` pasado.

## 6. Resto

- `medula/` vacía con `.gitkeep` (el kernel llega en E-06).
- `results/` con `.gitkeep`; `results/runs/` se versiona.
- `README.md` en inglés con la estructura, cómo preparar el entorno, cómo ejecutar tests y evaluate, y qué es cada modo (solo B implementado por ahora).
- `.gitignore`: `.venv/`, `.env`, `__pycache__/`, `*.db`, `.pytest_cache/`.

## 7. Terminado

1. `pytest` en verde en `demo-app/`.
2. `bench/evaluate.sh` sobre un workspace recién preparado con la app sin tocar: se ejecuta sin errores y el JSON muestra **las seis tareas y la integración con al menos un test en rojo** (lo esperado, porque aún no están hechas).
3. `ground_truth.yaml` con los 15 pares, verificado con `check_ground_truth.py`.
4. `bash -n` en todos los scripts. Ni `run_mode_b.sh` ni `check_openrouter.sh` se ejecutan.
5. `bench/self_check.sh` en verde:
   - la app sin tocar deja en rojo las seis tareas y la integración;
   - la solución de referencia (`reference/all_tasks.patch`) pasa todo;
   - la integración ingenua (`reference/naive_integration.patch`: T2 con la firma antigua de `login` y T4 filtrando por `fecha`) deja en rojo T2, T4 y la integración;
   - T5 y T6 en ramas separadas se fusionan sin conflicto.

## 8. Decisiones tomadas

1. **OTP en `/export`**: cabecera `X-OTP` como regla general de T1, implementada como `otp_header()` en `app/auth.py` con su docstring, más el verificador inyectable y los secretos conocidos. T2.md no menciona T1 ni el OTP. Los tests se evalúan sobre el estado final y siempre mandan OTP.
2. **Conflictos de merge en el modo B**: los resuelve un agente con el mismo modelo y esfuerzo, y su tiempo y coste cuentan en el modo B. Solo si no lo consigue se aborta esa rama y la tarea queda como fallida.
3. **Modelo de los agentes**: `anthropic/claude-sonnet-5 · effort high`, pasado con `--effort`. Queda pendiente verificar que OpenRouter lo reenvía (`check_openrouter.sh`).
4. **Workspaces**: `MEDULA_RUNS_DIR` (por defecto `$TMPDIR/medula-runs`), con comprobación de CLAUDE.md en los padres, config de Claude Code vacía por run y evidencia copiada a `results/runs/<run-id>/`.
