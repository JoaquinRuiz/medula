# Reservas de salas

API pequeña de reservas de salas (FastAPI + SQLite).

- `POST /login` — `{"username", "password"}` → `{"token"}`
- `POST /reservas` — `Authorization: Bearer <token>`, `{"sala", "fecha", "duracion_min"}` → reserva creada
- `GET /reservas` — lista de reservas

Tests: `python -m pytest`.
