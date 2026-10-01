# Set de calibración (E-04)

Parejas de intenciones de dos agentes que trabajan a la vez sobre la API de reservas. Cada pareja es una acción concreta del **solicitante** (lo que va a hacer ahora, con la herramienta y el cambio) frente a la intención en curso del **otro agente**. La pregunta que se calibra es la misma que hará el kernel: **¿choca?**

- `candidatas.yaml`: las 100 parejas, con una etiqueta **propuesta** (`propuesta`) y su motivo. La propuesta la escribió Claude y no cuenta como verdad.
- `etiquetas.yaml`: tus etiquetas a mano, la verdad contra la que se mide. Se genera con `bench/e04_etiquetar.py`.

## Qué significa «choca»

**choca**: si el solicitante ejecuta su acción ahora y el otro agente termina su intención tal como la describe, sin coordinarse, el resultado combinado rompe algo (una llamada, un contrato, datos o tests) o una de las dos tareas tiene que rehacerse. También choca si la acción destruye o sobrescribe el trabajo en curso del otro.

**no choca**: las dos cosas pueden completarse en cualquier orden y el resultado es correcto, aunque toquen el mismo fichero.

Reglas para los casos límite:

- **Lecturas y comandos que no escriben nada** (leer un fichero, `grep`, `git diff`, ejecutar tests, un `curl`) no chocan nunca. El resultado puede quedar desactualizado, pero no rompe nada. La escritura que venga después ya pasará por su propio `acquire`.
- **Un comando de Bash que escribe** (formatear el repo, `git checkout`, `sed -i`, recrear la base de datos, `uv add`) se juzga por lo que escribe, no por parecer un comando inocente.
- **Mismo fichero no implica choque.** Lo que importa es si los contratos o los datos que usa uno los cambia el otro.
- **Un cambio compatible** (un parámetro nuevo con valor por defecto, una función nueva, un campo opcional) no choca con quien usa la versión anterior.
- **Los tests del otro cuentan como contrato.** Si una tarea cambia un comportamiento que la otra está fijando en un test, chocan.
- **Si no lo tienes claro, márcala como dudosa**: se excluye del set en vez de meter ruido.

## Composición

| Categoría | choca | no choca |
|---|---:|---:|
| Mismo fichero sin relación | 0 | 12 |
| Mismo fichero con relación | 6 | 0 |
| Distinto fichero con relación (datos, formatos, fixtures) | 8 | 0 |
| Cambio de firma incompatible / compatible | 8 | 5 |
| Renombrados | 8 | 4 |
| Cambio de comportamiento sin cambiar la firma | 10 | 3 |
| Lecturas y tests mientras otros editan / Bash que escribe | 4 | 12 |
| Distinto fichero sin relación | 0 | 10 |
| Configuración y dependencias | 6 | 4 |
| **Total** | **50** | **50** |

Las parejas no reproducen T1–T6, para no calibrar con los mismos casos que mide E-07.
