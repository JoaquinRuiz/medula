# T2 en d1 (modo D, Médula + Jev, umbrales 0,2 / 0,8): espera, recibe los avisos y se adapta

| Hora | Quién | Qué |
|---|---|---|
| 10:14:40 | T2 | Intenta `Write app/routes_export.py` con `login(credentials.username, credentials.password)` |
| 10:14:41 | Médula · Jev (383 ms) | Probabilidad de choque 0,45 frente a A1 y 0,56 frente a A3 (falso): franja dudosa → camino lento |
| 10:14:50 | Médula · Sonnet (9,2 s) | «esperar a A1»: «las columnas se obtienen dinámicamente de Reserva.model_fields […]. Pero la firma de login() cambiará con A1, rompiendo la llamada actual de A2» |
| 10:14:50 | Médula | T2 queda en cola esperando a A1, dentro del hook: el agente no ve ningún motivo, su `Write` simplemente no vuelve |
| 10:14:44 – 10:16:19 | Médula | Cinco avisos al buzón de T2 mientras A1 trabaja: cambio de `USERS` con `otp_secret` en `config.py`, `login()` con OTP en `auth.py`, `POST /login` con `otp` en `routes_auth.py`, `conftest.py`; uno de A3 sobre `tests/test_reservas.py` (falsa alarma, con el diff vacío por el bug ya corregido) |
| 10:17:10 | Médula | A1 termina (SessionEnd). Jev vuelve a decidir (0,40 s) → camino lento |
| 10:17:18 | Médula · Sonnet (8,1 s) | «conceder». T2 recibe el permiso junto con los cinco avisos (como `additionalContext`). Espera total: 148 s |
| 10:17:23 | T2 | «Other agents are modifying `auth.py`, `config.py`, `routes_auth.py`, and `conftest.py` concurrently — likely adding OTP support. I need to check the current state of these files before finishing.» |
| 10:17:48 | T2 | `Edit app/routes_export.py`: `from app.auth import AuthError, login, otp_header` · `otp: str = Depends(otp_header)` · `login(credentials.username, credentials.password, otp)` |
| 10:18:15 | T2 | Tests con `X-OTP`: `headers={**basic_auth("alice", "alice-pass"), "X-OTP": otp_now("alice")}` |
| 10:18:25 | T2 | Termina con los tests en verde. Resultado del run: 37/37 en verde |

Notas:
- En d1 no hubo denegación con motivo: con la espera de hasta 600 s dentro del hook, el agente no llega a ver
  «espera». Lo que ve son los avisos, que llegan con el permiso. Para ver el motivo en la terminal del agente
  está la demo de E-08 con `--espera-max 30`.
- Uno de los avisos (10:16:04) salió por un `find … -exec cat {}` de A1, que la lista blanca trata como
  escritura por el `-exec`: es una lectura y no debería avisar.

Fuentes: `results/runs/d1/agents/T2.stream.jsonl` y `results/runs/d1/medula.db`.
