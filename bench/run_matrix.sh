#!/usr/bin/env bash
# E-07: matriz de ejecuciones. A×1, B×3, C×3, D×3, E×3, F×1 = 14 ejecuciones, una detrás de otra.
# Se salta los run_id que ya estén completos en results/summary.csv (b1, de E-05, cuenta como la
# primera de B), así que se puede cortar y retomar. Si una ejecución falla, sigue con la siguiente.
# D, E y F usan los umbrales calibrados de su decisor (calibration/umbrales.yaml). Las de D son d2-d4:
# d1 queda aparte como «v1 sin calibrar» (0,2/0,8).
#
# Uso: run_matrix.sh [--estimar] [--solo "D E"] [--excluir "b2"]
#   --estimar  solo muestra lo que falta, el coste y el tiempo estimados, y sale.
set -euo pipefail
source "$(dirname "$0")/lib/common.sh"

PLAN="A:1:1 B:1:3 C:1:3 D:2:4 E:1:3 F:1:1"   # modo:primero:último
SOLO=""
EXCLUIR=""
ESTIMAR=0
EXTRA=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --estimar) ESTIMAR=1; shift ;;
    --solo) SOLO="$(tr '[:lower:]' '[:upper:]' <<< "$2")"; shift 2 ;;
    --excluir) EXCLUIR="$2"; shift 2 ;;
    --umbral-aviso|--espera-max) EXTRA+=("$1" "$2"); shift 2 ;;
    *) die "opción desconocida: $1" ;;
  esac
done

cd "$MEDULA_ROOT"
# Ejecuciones pendientes: run_id = <modo en minúscula><n>.
pendientes=()
for par in $PLAN; do
  IFS=: read -r modo desde hasta <<< "$par"
  [[ -n "$SOLO" && " $SOLO " != *" $modo "* ]] && continue
  for i in $(seq "$desde" "$hasta"); do
    id="$(tr '[:upper:]' '[:lower:]' <<< "$modo")$i"
    [[ " $EXCLUIR " == *" $id "* ]] && continue
    if ! py - "$id" <<'PY'
import csv, sys
from pathlib import Path
ruta = Path("results/summary.csv")
hecho = ruta.exists() and any(r["run_id"] == sys.argv[1] and r["completado"] == "True" for r in csv.DictReader(ruta.open()))
sys.exit(0 if hecho else 1)
PY
    then pendientes+=("$modo:$id"); fi
  done
done

py - "${pendientes[@]+"${pendientes[@]}"}" <<'PY'
import csv, statistics, sys
from pathlib import Path
filas = [r for r in csv.DictReader(Path("results/summary.csv").open())] if Path("results/summary.csv").exists() else []
hechas = [r for r in filas if r["completado"] == "True"]
def media(modo, campo):
    v = [float(r[campo]) for r in hechas if r["modo"] == modo and r[campo]]
    if not v:
        v = [float(r[campo]) for r in hechas if r[campo]]
    return statistics.mean(v) if v else None
pend = [a.split(":") for a in sys.argv[1:]]
print(f"Hechas: {', '.join(r['run_id'] for r in hechas) or 'ninguna'}")
print(f"Pendientes ({len(pend)}): {', '.join(i for _, i in pend) or 'ninguna'}")
coste = sum(media(m, "coste_total_usd") or 0 for m, _ in pend)
tiempo = sum(media(m, "tiempo_total_s") or 0 for m, _ in pend)
print(f"Estimación con las medias de lo ya hecho: ~${coste:.0f} y ~{tiempo / 60:.0f} min (una detrás de otra).")
print("La estimación de un modo sin ejecuciones usa la media de todos; F (Sonnet decide todo) saldrá algo más caro.")
PY
[[ $ESTIMAR -eq 1 || ${#pendientes[@]} -eq 0 ]] && exit 0

for p in "${pendientes[@]}"; do
  modo="${p%%:*}"; id="${p##*:}"
  log "=== matriz: $id (modo $modo) ==="
  if [[ "$modo" == B ]]; then
    "$MEDULA_ROOT/bench/run_mode_b.sh" --run-id "$id" || log "AVISO: $id terminó con error"
  else
    umbrales=()
    case "$modo" in D) dec=jev ;; E) dec=haiku ;; F) dec=sonnet ;; *) dec="" ;; esac
    if [[ -n "$dec" ]]; then
      read -r bajo alto < <(py - "$dec" <<'PY'
import sys, yaml
u = yaml.safe_load(open("calibration/umbrales.yaml"))["decisores"][sys.argv[1]]
print(u["bajo"], u["alto"])
PY
)
      umbrales=(--umbral-bajo "$bajo" --umbral-alto "$alto")
      log "umbrales de $dec: $bajo / $alto"
    fi
    "$MEDULA_ROOT/bench/run_mode.sh" --modo "$modo" --run-id "$id" "${umbrales[@]+"${umbrales[@]}"}" "${EXTRA[@]+"${EXTRA[@]}"}" \
      || log "AVISO: $id terminó con error"
  fi
  # Un error de API (sin crédito, clave, límite) invalida lo que queda: se para la matriz.
  if ! py - "$MEDULA_ROOT/results/runs/$id" <<'PY'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
humo = d / "smoke.json"
if humo.exists() and "API Error" in humo.read_text():
    sys.exit(1)
for f in d.glob("mode_*.json"):
    if json.loads(f.read_text()).get("agentes_con_error_api"):
        sys.exit(1)
PY
  then
    die "$id falló por un error de la API (¿crédito de OpenRouter?). Matriz parada; revisa y vuelve a lanzarla."
  fi
done
log "matriz terminada: results/summary.csv"
