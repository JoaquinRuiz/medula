# Etiquetas humanas

Un fichero por persona (`<tu-usuario-de-github>.yaml`), escrito con
`uv run bench/e04_etiquetar.py --salida calibration/etiquetas_humanas/<tu-usuario>.yaml`.
El etiquetado es a ciegas: no se ven las etiquetas del modelo ni las de otras personas.
El acuerdo se mide con `uv run bench/acuerdo_etiquetas.py`.
