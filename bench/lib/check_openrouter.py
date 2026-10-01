"""Verifica que OpenRouter reenvía output_config.effort a Anthropic.

1. El modelo existe en OpenRouter.
2. La misma pregunta de razonamiento con effort low y high por
   /api/v1/messages: si el esfuerzo llega, high gasta claramente más tokens
   de salida. Se cruza con /api/v1/generation (tokens nativos y coste).
3. Un valor de esfuerzo inválido: ¿OpenRouter lo rechaza o lo ignora?
El resultado (con la evidencia en crudo) va a stdout en JSON.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import httpx2 as httpx  # httpx2: misma API; es la dependencia del proyecto raíz

BASE = "https://openrouter.ai/api/v1"
PREGUNTA = (
    "¿Cuántos números primos p menores que 2000 cumplen que p + 2 también es primo "
    "y que la suma de los dígitos de p es par? Razona con cuidado y termina con "
    "una línea 'RESPUESTA: <número>'."
)
RATIO_MINIMO = 1.5  # tokens de salida high / low para dar el esfuerzo por aplicado


def cliente(key: str) -> httpx.Client:
    return httpx.Client(
        base_url=BASE,
        timeout=600,
        headers={
            "Authorization": f"Bearer {key}",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "effort-2025-11-24",
            "X-Title": "medula-bench",
        },
    )


def mensaje(c: httpx.Client, model: str, effort: str) -> dict:
    body = {
        "model": model,
        "max_tokens": 32000,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
        "messages": [{"role": "user", "content": PREGUNTA}],
    }
    t = time.time()
    r = c.post("/messages", json=body)
    res = {"effort": effort, "status": r.status_code, "latency_s": round(time.time() - t, 2)}
    try:
        d = r.json()
    except ValueError:
        return {**res, "error": r.text[:500]}
    if r.status_code != 200:
        return {**res, "error": d}
    res.update({"id": d.get("id"), "usage": d.get("usage"), "stop_reason": d.get("stop_reason")})
    res["block_types"] = [b.get("type") for b in d.get("content", [])]
    return res


def generacion(c: httpx.Client, gen_id: str | None) -> dict | None:
    if not gen_id:
        return None
    for _ in range(10):  # la generación tarda unos segundos en aparecer
        r = c.get("/generation", params={"id": gen_id})
        if r.status_code == 200:
            d = r.json().get("data", {})
            keys = ("model", "provider_name", "tokens_completion", "native_tokens_completion",
                    "native_tokens_reasoning", "total_cost", "usage")
            return {k: d.get(k) for k in keys if k in d}
        time.sleep(3)
    return {"error": f"generation {gen_id} no disponible ({r.status_code})"}


def salida(m: dict, g: dict | None) -> int | None:
    if g and g.get("native_tokens_completion") is not None:
        return g["native_tokens_completion"]
    return (m.get("usage") or {}).get("output_tokens")


def main(model: str) -> None:
    key = os.environ["OPENROUTER_API_KEY"]
    out = {"model": model, "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with cliente(key) as c:
        ids = {m["id"] for m in c.get("/models").json().get("data", [])}
        out["model_listed"] = model in ids
        low = mensaje(c, model, "low")
        high = mensaje(c, model, "high")
        low["generation"] = generacion(c, low.get("id"))
        high["generation"] = generacion(c, high.get("id"))
        invalido = mensaje(c, model, "no-existe")
    out["runs"] = {"low": low, "high": high}
    out["invalid_effort"] = {"status": invalido["status"], "error": invalido.get("error")}
    out["invalid_effort_rejected"] = invalido["status"] >= 400

    tl, th = salida(low, low["generation"]), salida(high, high["generation"])
    out["output_tokens"] = {"low": tl, "high": th}
    out["ratio_high_low"] = round(th / tl, 2) if tl and th else None
    out["effort_passthrough"] = bool(out["ratio_high_low"] and out["ratio_high_low"] >= RATIO_MINIMO)
    out["criterion"] = f"tokens de salida high/low >= {RATIO_MINIMO} sobre la misma pregunta"
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv[1])
