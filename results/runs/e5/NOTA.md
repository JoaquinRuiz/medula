# e5

Modo E con la v0.2.0, agentes con la suscripción de Claude, como e4.

- **Espera cruzada (issue #14):** T3 esperaba a T4 desde las 13:57:48 y T4 se puso a esperar a T3 a las 14:02:50.
  Como T4 tenía peor prioridad, ninguno cedió hasta que venció la espera de T3 (600 s); T2 estuvo 9,5 min detrás de
  T3. De ahí los 1261 s, frente a los 311 s de e4. Arreglado en la v0.3.0 (#15).
- **Respuesta cortada (issue #5):** en la decisión 28, Sonnet agotó los 2048 tokens (`finish_reason = length`); el
  reintento con 4096 respondió bien (decisión 29) y no hubo que escalar a Opus.
