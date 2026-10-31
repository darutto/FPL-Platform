# R6, PR 3: la herramienta `get_player_involvement`

**Estado:** detrás de `FOOTBALL_INTELLIGENCE_ENABLED` y del sync licenciado (`FPL_FOOTBALL_LICENSED_SYNC_ENABLED`). Sin ellos la herramienta no se ofrece al modelo ni devuelve datos: responde `missing_context`. Necesita además que el almacén tenga la tabla `player_match_stats` (PR #553) llena por la ingesta (PR 2): sin ella, `missing_context` con `no_player_stats`.

## Qué responde

`get_player_involvement(player, absent_player?, matches?)`: para un jugador (id FPL), en sus últimos partidos con estadísticas guardadas, **toques, pases, % de acierto, pases clave y pases hacia atrás** (y qué parte de sus pases fue hacia atrás), como **totales por partido del proveedor**, más promedios por 90 minutos. Con `absent_player` (un compañero) compara sus toques por 90 en los partidos en que el compañero **no jugó** con aquellos en que **fue titular**.

## Lo que el dato no es

- Son **totales por partido**: sin zonas, sin mapas de calor, sin minuto de la acción. No hay pases progresivos ni pases hacia delante exactos. "Cuota atrás" es `pases hacia atrás / pases`.
- Por 90 solo usa partidos con **30+ minutos**; el resto se muestra pero no entra en el promedio.

## Estados de afirmación

| Estado | Qué es | Ejemplo |
|---|---|---|
| `observed` | un total del partido guardado | "62 toques, 41 pases (85 % de acierto), 9 hacia atrás" |
| `associated` | dos hechos observados que coinciden | "tuvo más toques cuando X no jugó; ambas cosas coincidieron" |

No hay `hypothesis`: la herramienta no ofrece explicaciones.

## Redacción (en la descripción de la herramienta y en el renderizador)

Permitido: *"tuvo más/menos toques"*, *"coincidió con la ausencia de X"*. Prohibido: causalidad (*"por la lesión"*, *"porque faltó X"*), predicción, "debilidad", y hablar de **dónde** del campo (zonas, mapas de calor). Un test recorre texto y tarjeta en ES y EN contra esa lista.

## Reglas de datos (mismo patrón que `get_position_changes`)

- **Identidad por id**: ambos jugadores se resuelven con `tool_resolve_player` (nombres completos, nunca subcadenas); el compañero se acota al club del jugador por id FPL y código de club; otro club ⇒ `not_a_teammate`. En el almacén todo se une por **id de elemento FPL + club de la fila del partido**.
- **Compañero ausente** = no tiene fila en un partido que el almacén guarda para el club (la tabla solo tiene jugadores con minutos). **Con él** = fue titular. Si entró de suplente no cuenta en ningún lado (`matches_mixed`).
- **Once guardado incompleto**: si el club tiene menos de 11 titulares guardados en ese partido (el almacén descarta a quien no empareja con FPL), el partido queda **fuera de la comparación** (`matches_uncertain`): un titular sin mapear no se lee como ausencia.
- **Muestra pequeña se dice**: menos de 5 partidos con estadísticas; en la comparación, menos de 3 por lado. `touches_without_vs_with` es `more`/`fewer` solo si la diferencia relativa es ≥ 10 %, si no `similar`; `null` si falta un lado.
- **La historia empieza cuando empezó la ingesta** (más el relleno `--pass backfill`), así que al principio habrá pocos partidos.
- Una corrección posterior del proveedor sustituye a la primera lectura del mismo partido (se toma la última observación).
- Nada crudo sale: ni filas del almacén, ni ids de partido, ni ids de proveedor.

## Tarjeta

Contrato `generic_card` existente (no hay componente nuevo): una fila por partido (jornada, rival L/V, toques, pases con % de acierto, pases clave, pases hacia atrás con su %), héroe = toques por 90, píldoras de muestra pequeña y de la comparación ("Más toques sin X"), pie con la fecha de la build. Pares ES/EN en el catálogo (`gcard.player_involvement.*`, `renderer.player_involvement.*`). Se compone solo en turnos de una única herramienta y si la respuesta es `ok` con partidos.
