# f3

Modo F con la v0.3.0, agentes con la suscripción de Claude, como f2.

**Crédito de OpenRouter al límite:** a las 14:35:00, cuatro peticiones simultáneas a Sonnet (decisiones 62–65)
superaron el crédito disponible y OpenRouter las rechazó con HTTP 402 («would exceed your available credits given
your current in-flight requests»). Médula pasó a locks en esas cuatro, como está previsto: dos accesos concedidos y
dos avisos sin enviar. Desde la decisión 66 todo volvió a ir por Sonnet sin errores. Resultado: 37/0, 2 de 2
conflictos detectados, 0 bloqueos innecesarios, 277 s. Se cuenta como válida, con `reservas = 4` en `summary.csv`.
