# f2

Modo F con la v0.3.0 (espera cruzada arreglada). Agentes con la suscripción de Claude (`proveedor_agentes =
suscripcion`): mismo modelo y esfuerzo (`claude-sonnet-5`, high), directos a Anthropic; los decisores, por
OpenRouter. Sin canal entre agentes (ListAgents/SendMessage desactivados), sin errores del decisor y sin esperas
cruzadas: 286 s.

No confundir con `results/runs/_invalidas/f2-interrumpida`, la primera f2, parada a los 64 s con la v0.2.0.
