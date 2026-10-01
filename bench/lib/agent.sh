# Lanzamiento de agentes de Claude Code por OpenRouter. Se carga con `source`
# después de common.sh. Necesita: MODEL, EFFORT, OPENROUTER_API_KEY,
# AGENT_CONFIG_DIR. Cada workspace es un proyecto uv propio (el de demo-app).

# Herramientas prohibidas a los agentes, en todos los modos:
# - ScheduleWakeup y similares: en modo no interactivo terminan la sesión esperando un despertar que
#   nunca llega (run d0: el agente de T2 hizo ScheduleWakeup y abandonó su tarea).
# - ListAgents y SendMessage: dejan hablar con otras sesiones de Claude Code de la máquina, es decir,
#   coordinarse por fuera de Médula (run f1: T3 avisó a T4 del renombrado por SendMessage).
# - EnterWorktree y ExitWorktree: sacarían al agente del directorio de trabajo del run.
AGENT_DISALLOWED="${AGENT_DISALLOWED:-ScheduleWakeup,CronCreate,CronDelete,CronList,RemoteTrigger,ListAgents,SendMessage,EnterWorktree,ExitWorktree}"

# run_agent <nombre> <cwd> <prompt-file> <logdir>
# Escribe en <logdir>:
#   <nombre>.stream.jsonl  eventos en vivo (stream-json), los que muestra bench/modo_b_en_directo.py
#   <nombre>.json          el evento final "result" (coste, turnos, session_id)
#   <nombre>.log           stderr
#   <nombre>.meta.json     código de salida y tiempos
run_agent() {
  local name="$1" cwd="$2" prompt_file="$3" logdir="$4"
  local start end rc
  start="$(now_s)"
  set +e
  (
    cd "$cwd" && env -u CLAUDE_EFFORT -u ANTHROPIC_MODEL -u VIRTUAL_ENV \
      CLAUDE_CONFIG_DIR="$AGENT_CONFIG_DIR" \
      ANTHROPIC_BASE_URL="https://openrouter.ai/api" \
      ANTHROPIC_AUTH_TOKEN="$OPENROUTER_API_KEY" \
      ANTHROPIC_API_KEY="" \
      claude -p "$(cat "$prompt_file")" \
        --model "$MODEL" --effort "$EFFORT" \
        --permission-mode bypassPermissions \
        --disallowedTools "$AGENT_DISALLOWED" \
        --output-format stream-json --verbose \
        < /dev/null > "$logdir/$name.stream.jsonl" 2> "$logdir/$name.log"
  )
  rc=$?
  set -e
  py "$MEDULA_ROOT/bench/lib/stream_result.py" "$logdir/$name.stream.jsonl" > "$logdir/$name.json"
  end="$(now_s)"
  printf '{"name": "%s", "exit_code": %d, "start": %s, "end": %s}\n' \
    "$name" "$rc" "$start" "$end" > "$logdir/$name.meta.json"
  return 0
}
