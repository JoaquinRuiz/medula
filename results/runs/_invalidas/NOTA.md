# Ejecuciones inválidas: sin crédito en OpenRouter

El 2026-09-29, a partir de las 15:54 (hora local), OpenRouter respondió `402 This request would exceed your
available credits` a los agentes. c3 y d2 cayeron a mitad de ejecución; d3, d4, e1, e2, e3 y f1 fallaron ya
en la llamada de prueba. Sus resultados no significan nada y están fuera de summary.csv; los run_id se
repiten con crédito. Desde entonces, un error de API en cualquier agente marca la ejecución como no
completada y para la matriz.
