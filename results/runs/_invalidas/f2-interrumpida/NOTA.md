# f2 · interrumpida

Ejecución del modo F (v0.2.0, agentes con la suscripción de Claude) parada a mano a los 64 s, en la ronda 1.
Motivo: en e5 apareció un fallo de Médula en la espera cruzada (dos agentes que se esperan el uno al otro no
se desbloquean hasta que vence `espera_max`), y no tenía sentido seguir midiendo con él. No cuenta para nada:
fuera de `summary.csv`.
