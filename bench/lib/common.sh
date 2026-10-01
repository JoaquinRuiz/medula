# Utilidades compartidas por los scripts de bench/. Se carga con `source`.

MEDULA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export MEDULA_ROOT

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# Directorio base de los runs, fuera del repo.
runs_dir() {
  local base="${MEDULA_RUNS_DIR:-${TMPDIR:-/tmp}/medula-runs}"
  base="${base%/}"
  mkdir -p "$base"
  (cd "$base" && pwd -P)
}

# Aborta si la ruta está dentro del repo o si algún directorio padre tiene
# CLAUDE.md o .claude/: un agente lanzado ahí heredaría esas instrucciones.
assert_isolated_path() {
  local path; path="$(cd "$1" && pwd -P)"
  local root; root="$(cd "$MEDULA_ROOT" && pwd -P)"
  case "$path/" in
    "$root"/*) die "la ruta $path está dentro del repo medula; usa MEDULA_RUNS_DIR fuera de $root" ;;
  esac
  local d="$path"
  while :; do
    if [[ -e "$d/CLAUDE.md" || -e "$d/CLAUDE.local.md" || -d "$d/.claude" ]]; then
      die "encontrado CLAUDE.md o .claude/ en $d (padre de $path); elige otra MEDULA_RUNS_DIR"
    fi
    [[ "$d" == "/" ]] && break
    d="$(dirname "$d")"
  done
}

# Carga .env si existe (sin pisar variables ya definidas en el entorno).
load_env() {
  local f="$MEDULA_ROOT/.env"
  [[ -f "$f" ]] || return 0
  local line key val
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    key="${line%%=*}"; val="${line#*=}"
    key="${key//[[:space:]]/}"; val="${val%\"}"; val="${val#\"}"
    [[ -z "${!key:-}" ]] && export "$key=$val"
  done < "$f"
}

# Python de las herramientas de bench (proyecto uv de la raíz).
py() { uv run --quiet --project "$MEDULA_ROOT" python "$@"; }

now_s() { py -c 'import time; print(f"{time.time():.3f}")'; }
