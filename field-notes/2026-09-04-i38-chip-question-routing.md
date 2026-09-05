# i38 — una pregunta de chip con jugador y jornada se reparte entre tres herramientas

**Fecha:** 2026-09-04 · **Carta:** i38 (elección de herramienta)
**Estado:** observación registrada, **sin medir y sin arreglar**. No se tocó
ningún schema.

## Qué se observó

Pregunta, literal y sin variar entre intentos:

    uso el triple capitan en haaland en la fecha 3?

Cuatro envíos idénticos al backend local (Gemini, controles de muestreo de
producción), **tres herramientas distintas**:

| intento | herramienta elegida | ¿llega al consejo de chip? |
|---|---|---|
| 1 (dueño, en la UI) | `get_player_snapshot` | no |
| 2 | `get_chip_advice` | **sí** |
| 3 | `get_gameweek_context` | no |
| 4 | `get_chip_advice` | **sí** |

**n=4. Esto no es una tasa.** Es una observación que dice que vale la pena
medir, y nada más. La regla de la casa sobre muestras pequeñas se aplica igual
aquí que en i52: no atribuir la diferencia entre intentos a ninguna causa.

## Por qué es interesante y no solo molesto

La frase contiene **las tres anclas a la vez**: un chip («triple capitán»), un
jugador («haaland») y una jornada («la fecha 3»). Cada ancla tiene una
herramienta que la reclama, y en estos cuatro intentos ganó una distinta casi
cada vez.

`get_gameweek_context` como atractor general de jornada **ya está medido** en la
matriz de confusión de rutas (rama `measure/tool-routing-confusion`, 8487f76),
donde se concluyó podar solo `get_current_gameweek`. Este caso añade un dato:
el atractor también gana cuando la pregunta trae un chip y un jugador
explícitos, no solo cuando menciona el calendario.

`get_player_snapshot` compitiendo por una pregunta de chip es el dato nuevo.

## Consecuencia de producto

Es la pregunta insignia del producto —«¿le doy el triple capitán a X?»— y en
estos cuatro intentos no llegó al consejo de chip la mitad de las veces. Cuando
no llega, el usuario recibe una tarjeta de jugador o el contexto de la jornada:
respuestas correctas a preguntas que no hizo.

Todo el trabajo de factores visibles del encargo de capitanía cuelga de que la
pregunta llegue a `get_chip_advice`. Está construido y verificado en vivo, pero
solo se ve cuando la ruta acierta.

## Lo que este trabajo NO hizo

El encargo de capitanía **no tocó ninguna superficie de enrutado**: ni schemas,
ni descripciones de herramienta, ni `dispatcher.py`, ni `decision_router.py`, ni
`orchestrator.py`. Comprobado por diff contra `origin/main`. Este comportamiento
es anterior y sigue igual.

## Siguiente paso, cuando se decida hacerlo

Medir antes de tocar una descripción, con el instrumento que ya existe
(`scripts/measure_tool_routing.py`), regla de decisión escrita antes de la
primera llamada, y un N que sostenga una tasa. El último arreglo de i38 se
decidió con 450 observaciones; este merece el mismo trato y no cuatro.

Lo que **no** hay que hacer es ajustar la descripción de `get_chip_advice` a ojo
porque cuatro intentos salieron así.
