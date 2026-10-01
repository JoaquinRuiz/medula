# f1: válida por decisión del autor, con canal entre agentes

Los agentes tenían disponibles ListAgents y SendMessage (herramientas de Claude Code para hablar con otras
sesiones de la máquina) y las usaron: T3 avisó a los demás del renombrado («si tu tarea toca esa tabla
(p. ej. `WHERE fecha >= ?`), usa `inicio`») y T4 respondió que ya había adaptado app/consultas.py. El choque
T3-T4 no lo resolvió Médula. Se mantiene en la tabla del modo F por decisión del autor (2026-09-29), con esta salvedad: parte de la coordinación T3-T4 fue directa entre agentes.
Desde entonces esas herramientas están prohibidas a todos los agentes (bench/lib/agent.sh).
