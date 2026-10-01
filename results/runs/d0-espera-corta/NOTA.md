# d0-espera-corta (antes d1): ejecución descartada de la matriz

Primera ejecución del modo D (2026-09-29). Médula detectó los dos choques reales (T1-T2 y T3-T4) sin
bloqueos innecesarios, pero la ejecución no es válida para E-07 por un fallo del banco, no de Médula:

- La espera dentro del hook duraba como máximo 60 s. A T2 se le denegó la escritura tras esperar a T1.
- El agente de T2 respondió con `ScheduleWakeup` (esperar 240 s) y cerró la sesión; en modo no
  interactivo ese despertar no llega, así que T2 quedó sin hacer (7 tests en rojo, todos de T2).

Corregido después: espera de hasta 600 s dentro del hook, `ScheduleWakeup` y similares prohibidos a
los agentes en todos los modos, `sleep` como lectura y un prompt que pide no terminar sin completar la tarea.
