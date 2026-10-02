# SPEC — Médula v1 (fase E-06)

Kernel de coordinación para varios agentes de Claude Code que trabajan a la vez sobre el mismo repositorio. Antes de cada escritura, un agente pide permiso (`acquire`). Médula construye la intención de esa acción y pregunta a un decisor si choca con lo que están haciendo los demás. Después de cada escritura (`notify`), Médula avisa a los agentes cuyo plan pueda haber quedado invalidado.

Estado: **aprobada** el 2026-09-29, con las seis decisiones de la sección 12 tal como están.

Referencias comprobadas:
- **Hooks de Claude Code** (V-04): <https://code.claude.com/docs/en/hooks>, consultado el 2026-09-29.
- **API System One de Jev**: <https://openrouter.ai/docs/guides/community/typesafe-sdk>. La pregunta `noul` devuelve una probabilidad (`{"type": "noul", "noul": 0.98}`); `choice` devuelve opción y confianza. Varias preguntas van en un mismo diccionario `questions`, así que se pueden agrupar en una petición. No hay límite documentado. Contexto máximo de 32k tokens.

---

## 0. Alcance y modos

Médula sirve a los modos C–F de la matriz de E-07 con el mismo servidor, cambiando solo el decisor:

| Modo | Decisor principal | Reserva automática | Camino lento |
|---|---|---|---|
| C | `locks` (lock clásico por fichero) | — | no |
| D | `jev` | jev → haiku → locks | Sonnet → Opus |
| E | `haiku` | haiku → locks | Sonnet → Opus |
| F | `sonnet` | sonnet → locks | Sonnet → Opus |

- **Todos los modelos van por OpenRouter**, con la misma clave y la misma pasarela: `typesafe/jev-1.13`, `anthropic/claude-haiku-4.5`, `anthropic/claude-sonnet-5` y `anthropic/claude-opus-5.5`. Así D, E y F se comparan en igualdad de condiciones.
- **Agentes iguales en todos los modos:** Claude Code `anthropic/claude-sonnet-5 · effort high`, con la configuración vacía y aislada de E-05. Lo único que cambia entre modos son los hooks.

## 1. Proyecto

`medula/` es un proyecto uv propio: Python 3.12, `fastapi`, `uvicorn`, `httpx2`, `pyyaml` y `rich`, con `pytest` en dev.

```
medula/
  pyproject.toml  uv.lock  SPEC.md  README.md
  src/medula/
    servidor.py        # FastAPI: /registrar /acquire /notify /release /estado
    almacen.py         # SQLite: esquema y acceso (una conexión por petición, WAL)
    intencion.py       # construye la intención a partir de tarea + herramienta
    decisores/
      base.py          # interfaz Decisor y Veredicto
      jev.py           # System One (noul + choice)
      llm.py           # Haiku / Sonnet / Opus por Chat Completions con salida estructurada
      locks.py         # lock clásico por fichero
      cadena.py        # reserva automática jev → haiku → locks
    camino_lento.py    # Sonnet propone la salida; si no resuelve, Opus
    interrupciones.py  # ¿invalida este cambio el plan de este agente?
    plan.py            # grafo de tareas y prioridad de la cola
    htop.py            # interfaz de terminal que lee el SQLite
    config.py
  hook/medula-hook.sh  # el hook de Claude Code: un curl al servidor
  tests/
```

Arranque: `uv run medula servir --decisor jev --plan plan.yaml --db <run>/medula.db` y `uv run medula htop --db <run>/medula.db`.

## 2. Estado en SQLite

| Tabla | Columnas |
|---|---|
| `agentes` | `id` (A1…), `tarea`, `session_id`, `estado` (trabajando / esperando / terminado), `registrado`, `ultima_accion` |
| `locks` | `id`, `agente`, `recurso` (ruta relativa, o `repo` para Bash que escribe), `intencion` (JSON), `desde` |
| `cola` | `id`, `agente`, `recurso`, `intencion`, `espera_a` (agente), `prioridad`, `desde`, `estado` (esperando / concedido / caducado) |
| `buzon` | `id`, `para`, `de`, `texto`, `p_invalida`, `creado`, `entregado` |
| `decisiones` | `id`, `ts`, `tipo` (acquire / notify / lento), `agente`, `accion` (JSON), `pregunta`, `estado_enviado` (JSON), `respuesta` (JSON en crudo), `veredicto`, `p_choca`, `confianza`, `latencia_ms`, `coste_usd`, `decisor`, `modelo`, `reserva_de` (decisor que falló, si lo hubo), `error`, `finish_reason` (el que da el proveedor en las llamadas a LLM: `stop`, `length`…) |

- **Latencia y coste** de cada decisión: latencia medida de extremo a extremo desde Médula; coste el que devuelve OpenRouter (`usage.cost`), o 0 en `locks`.
- **Métricas de E-07 a E-11:** latencias, avisos, detecciones, bloqueos innecesarios, escaladas y costes salen de aquí, todas por consultas sobre el SQLite.

## 3. La intención la construye Médula

El agente no describe lo que va a hacer. Médula monta la intención con:
- **La tarea asignada:** título y alcance de `tasks/TN.md`, recortados a unos 600 caracteres.
- **Lo que va a hacer de verdad la herramienta**, sacado de `tool_input` del hook:
  - `Edit`: fichero, `old_string` y `new_string` (recortados a unos 1.500 caracteres).
  - `Write`: fichero y diff contra el contenido actual, o su principio si el fichero es nuevo.
  - `Bash`: `command` y `description`.

El estado que ve el decisor tiene la misma forma que en E-03 y E-04, para que la calibración sirva:
```json
{"solicitante": {"agente", "tarea", "accion": {"herramienta", "objetivo", "cambio"}},
 "otros_agentes": [{"agente", "tarea", "tiene": [recursos con lock], "intencion": "últimas escrituras resumidas"}]}
```
Se recorta para caber en 32k tokens: si falta sitio, pierde primero el historial de los otros agentes.

**Lecturas.** `Bash` de solo lectura se concede sin preguntar al decisor, con `decisor = "regla"`. Cuenta como solo lectura una lista blanca: `ls`, `cat`, `head`, `tail`, `grep`/`rg`, `find` sin `-delete`/`-exec`, `git status|diff|log|show`, `uv run pytest` y `uv run python -c` sin redirecciones. Es la regla de E-04: lo que no escribe nunca choca. Cualquier otro `Bash` pasa por el decisor como escritura sobre el recurso `repo`.

## 4. Hooks de Claude Code

**Configuración.** Va en el `settings.json` de la configuración vacía de cada ejecución (`CLAUDE_CONFIG_DIR`), no en el repositorio de trabajo; así el agente no la ve ni la commitea.

```json
{"hooks": {
  "PreToolUse":  [{"matcher": "Edit|Write|Bash", "hooks": [{"type": "command", "command": "<run>/medula-hook.sh pre",  "timeout": 300}]}],
  "PostToolUse": [{"matcher": "Edit|Write|Bash", "hooks": [{"type": "command", "command": "<run>/medula-hook.sh post", "timeout": 60}]}],
  "SessionEnd":  [{"hooks": [{"type": "command", "command": "<run>/medula-hook.sh fin"}]}]
}}
```

**`medula-hook.sh`.** Lee el JSON del hook por stdin y lo reenvía con `curl` a `$MEDULA_URL/acquire`, `/notify` o `/release`, añadiendo la cabecera `X-Medula-Agente: $MEDULA_AGENTE`. El servidor responde directamente en el formato de salida de los hooks, y el script lo imprime tal cual. En `pre`, `curl` espera como mucho `MEDULA_HOOK_TIMEOUT` segundos (290 por defecto); ese plazo tiene que cubrir `espera_max` más una decisión del camino lento y quedar por debajo del `timeout` del hook (`bench/run_mode.sh` usa `espera_max + 100` y `espera_max + 120`). Si se agota, el hook bloquea la acción con un mensaje propio, distinto del de Médula caída.
- **Si el servidor no responde, sale con código 2 y bloquea** («Médula no responde»). Uso un hook de comando en lugar de un hook `http` por esto: un hook `http` que falla deja pasar la herramienta, y el experimento quedaría contaminado sin que nadie lo notase.

**Respuestas del servidor:**
- **Conceder:** `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow", "additionalContext": "<avisos del buzón, si hay>"}}`.
- **Esperar o conflicto:** `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "<motivo>"}}`. Un ejemplo de motivo: «Médula: A1 está cambiando `login()` para exigir OTP (T1). Tu `/export` llama a `login(username, password)`. Espera a que A1 termine; te avisaré en cuanto acabe. Mientras, puedes avanzar en otra parte de tu tarea.»
- **Tras cada escritura (`notify`):** `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "<avisos pendientes>"}}`. Los avisos se marcan como entregados.
- **Al terminar (`SessionEnd` → `/release`):** se liberan todos los locks del agente, se pasa a `terminado` y se despierta la cola.

**Espera corta dentro del hook.** Cuando el veredicto es esperar, `/acquire` no deniega enseguida: mantiene la petición abierta hasta `espera_max` (60 s por defecto) por si el agente al que espera termina. Si termina y la nueva decisión es conceder, se concede y el agente ni se entera. Si no, se deniega con el motivo. Así se ahorran reintentos, que gastan turnos y dinero, y el agente sigue viéndose «esperando» en el htop.

## 5. Decisores

```python
class Decisor(Protocol):
    nombre: str
    def acquire(self, estado: dict, otros: list[str]) -> dict[str, Veredicto]: ...  # un veredicto por cada otro agente
    def invalida(self, estado: dict, otros: list[str]) -> dict[str, Veredicto]: ...
@dataclass
class Veredicto:
    p: float                 # probabilidad de choque (o de invalidar el plan)
    remedio: str | None      # esperar | replanificar (solo si p es alta)
    confianza: float | None
    latencia_ms: float; coste_usd: float; modelo: str; crudo: dict
```

- **jev.** Una sola petición a `/api/v1/systemone` con, para cada otro agente `X`:
  - `choca_X`: `noul`, «¿Choca la acción del solicitante con lo que está haciendo X?», con la guía de E-04;
  - `remedio_X`: `choice` entre `esperar` y `replanificar`.

  `p` es el valor de `noul`.
- **haiku / sonnet.** Chat Completions por OpenRouter con salida estructurada `{por_agente: {X: {p_choca, remedio}}}`: la misma pregunta, todos los agentes en una llamada. Sonnet en esfuerzo `low` y Haiku sin razonamiento, como en E-03.
- **locks.** Sin modelo:
  - `p = 1` si otro agente tiene lock sobre el mismo fichero, o sobre `repo` si la acción es un Bash que escribe;
  - `p = 0` en otro caso;
  - el remedio siempre es `esperar`.
- **Reserva automática** (`cadena.py`). Si el decisor da error, supera su tiempo máximo (jev 5 s, haiku 15 s, sonnet 30 s) o devuelve algo fuera de formato, se pasa al siguiente de la cadena y se anota `reserva_de`.

**Regla de decisión en `acquire`**, con `p = max` sobre los otros agentes:

| Condición | Veredicto |
|---|---|
| `p < umbral_bajo` | conceder, y la acción queda anotada como lock con su intención |
| `p > umbral_alto` y remedio `esperar` | esperar al agente con mayor `p` hasta que termine (`SessionEnd`) |
| `umbral_bajo ≤ p ≤ umbral_alto`, o remedio `replanificar` | camino lento |

Los umbrales empiezan en **0,2 y 0,8** y se fijan con E-04 repetido con `noul` (ver sección 10).

**Qué es un lock en los modos semánticos.** Un lock no es un cerrojo que impida tocar el fichero: es la constancia de que el agente está cambiando ese recurso con esa intención, y dura hasta que termina su tarea. Por eso «esperar a A1» significa esperar a que A1 acabe T1. Cuando reintente, el agente de T2 verá ya el `login()` con OTP y se adaptará.

## 6. Camino lento

1. **Sonnet** recibe el estado, las intenciones en juego y los veredictos, y propone una salida con salida estructurada: `conceder` (falso choque), `esperar` (a quién), `reordenar` (quién va primero; se cambia la prioridad en la cola) o `reescribir` (instrucciones concretas para el solicitante, que se le devuelven como motivo del `deny`).
2. Si la respuesta de Sonnet llega cortada por `max_tokens` (`finish_reason = length`), se repite una vez con el doble de tokens; cada intento queda en `decisiones` con su coste.
3. Si Sonnet da error, contesta fuera de formato o declara que no puede resolverlo (`resuelto: false`), **Opus** hace lo mismo.
4. Si Opus tampoco lo resuelve, se espera por defecto, que es lo seguro.

Cada paso queda en `decisiones` con `tipo = lento`. De aquí salen las escaladas a Sonnet y a Opus de E-07.

## 7. Interrupciones

En cada `/notify` de una escritura (`Edit`, `Write` o `Bash` que escribe), Médula pregunta **en una sola petición** al decisor, por cada otro agente activo, «¿invalida este cambio el plan de X?» (`noul` en Jev):
- **Si `p > umbral_aviso`** (0,5 por defecto; se ajusta con E-09), deja en el buzón de X un aviso con el cambio resumido, por ejemplo: «A3 acaba de renombrar `Reserva.fecha` a `inicio` en `models.py` y `db.py`».
- **Entrega:** el aviso llega a X con el siguiente hook que ejecute X, en `PreToolUse` o `PostToolUse`, como `additionalContext`.
- **Métricas de E-09:** avisos posibles = escrituras × (agentes activos − 1); avisos enviados = filas del buzón.
- **En el modo C no hay interrupciones**, porque el lock clásico no las tiene.

## 8. Prioridades desde el grafo de tareas

`plan.yaml` describe las tareas de la ejecución con su agente y sus dependencias declaradas, como las escribiría la spec:
```yaml
tareas:
  T1: {agente: A1, depende_de: []}
  T2: {agente: A2, depende_de: []}
```
La cola de un recurso se ordena por orden topológico del grafo (una tarea va antes que las que dependen de ella), después por `prioridad` (la que cambie el camino lento con `reordenar`) y después por orden de llegada.

**Aviso de sesgo.** Si el grafo declara «T2 depende de T1», le está chivando a Médula el choque que queremos medir. Para E-07, `plan.yaml` no declara dependencias entre T1–T6, que en la spec de la app son funcionalidades independientes. Ver la decisión 3.

## 9. htop de agentes

`uv run medula htop --db <run>/medula.db` refresca cada 0,5 s con `rich` y muestra:
- **Agentes:** tarea, estado (trabajando / esperando a A1 desde hace 42 s / terminado) y última acción.
- **Locks:** recurso, agente y un resumen de la intención.
- **Cola de espera:** quién espera a quién, desde cuándo y con qué prioridad.
- **Últimas decisiones:** hora, agente, acción, `p`, veredicto, decisor (marcando `reserva` y `lento`), latencia y coste.
- **Totales:**
  - número de decisiones;
  - latencia p50 y p95;
  - coste acumulado de decisiones frente al equivalente si todas las hubiera tomado Sonnet (número de decisiones × coste medio por decisión de Sonnet medido en E-03);
  - escaladas a Sonnet y a Opus;
  - avisos enviados.

## 10. Dependencias con otras fases

- **Repetir E-04 con la pregunta `noul`.** Las tres ejecuciones de E-04 en `results/e04/` hicieron la pregunta a Jev como `choice`, pero el kernel usa `noul` (probabilidad de choque), que es la que pide el plan. Antes de fijar los umbrales hay que adaptar `e04_calibracion.py` a `noul` (Jev) y a `p_choca` (Haiku y Sonnet), con tramos sobre `p` y una tabla de umbrales de dos lados (bajo y alto).
- **Puerta de E-04.** La última ejecución (`choice`) dio PARAR solo por ECE 0,117 > 0,10, con Jev = Haiku (87 %) y un 100 % de acierto cuando Jev declara ≥ 0,9. Conviene releerla con la pregunta `noul` antes de E-07.
- **Lanzador.** `bench/run_mode.sh --modo C|D|E|F` generaliza `run_mode_b.sh`:
  - arranca Médula con el decisor del modo y el htop;
  - lanza los agentes con los hooks;
  - registra la ejecución en `results/runs/<id>/`, con el `medula.db` incluido;
  - añade una fila a `results/summary.csv`.

  Lo especifico en la fase E-07; aquí solo se deja preparado el servidor.

## 11. Terminado

1. `uv run pytest` en verde en `medula/`, cubriendo:
   - el almacén;
   - la intención;
   - cada decisor contra un OpenRouter simulado, incluida la reserva automática;
   - la regla de decisión con los dos umbrales;
   - el camino lento (Sonnet que no resuelve → Opus);
   - el buzón;
   - la cola con prioridades;
   - el script del hook (servidor caído → código 2).
2. Una prueba de extremo a extremo sin coste: dos `claude` falsos que ejecutan T1 y T2 contra el servidor real con el decisor `locks` y con un Jev simulado. Tiene que verse que T2 espera a T1 y que el aviso llega al buzón.
3. Una prueba con Claude Code de verdad y un solo agente (unos céntimos): el hook bloquea una `Edit` y el agente recibe el motivo. Confirma el formato de V-04 en la práctica.
4. El htop se ve bien en una terminal de tamaño normal.

## 12. Decisiones para tu visto bueno

1. **Hook de comando con `curl` que bloquea si Médula cae**, en lugar de un hook `http`, que deja pasar la herramienta.
2. **Espera corta dentro del hook** (hasta 60 s) antes de denegar con motivo, frente a denegar enseguida como dice el plan literalmente. Ahorra reintentos y turnos, y el agente se ve esperando.
3. **Grafo de tareas sin dependencias entre T1–T6 en E-07**, para no darle a Médula la respuesta. El mecanismo de prioridades existe y se prueba en los tests.
4. **Árbol de trabajo compartido.** En los modos C–F los cuatro agentes trabajan sobre el **mismo directorio**: coordinarse sobre ficheros compartidos es justo lo que mide Médula. No hacen commit: el banco hace uno al final y evalúa. En este modelo no hay conflictos de git (los conflictos de git solo existen en el modo B).
5. **Bash de solo lectura por lista blanca**, sin preguntar al decisor.
6. **Jev con dos preguntas por agente** (`noul` para la probabilidad de choque y `choice` para el remedio) en una sola petición.
