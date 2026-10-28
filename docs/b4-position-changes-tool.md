# B4, PR 2: la herramienta `get_position_changes`

**Estado:** detrás de `FOOTBALL_INTELLIGENCE_ENABLED` (apagado en producción) y de que el almacén licenciado esté sincronizado (`FPL_FOOTBALL_LICENSED_SYNC_ENABLED`, ver [la auditoría](b4-licensed-runtime-audit.md)). Sin esas dos cosas la herramienta ni se ofrece al modelo, ni devuelve datos: responde `missing_context`.

## Qué responde

Para un jugador (id FPL): su casilla en el **once inicial anunciado** de los últimos partidos de su club que están en el almacén; si esa casilla difiere de la de sus propios últimos inicios; y qué compañeros habituales **no estaban en el once** esos días. Con `absent_player` (un compañero), separa los partidos en que ese compañero no fue titular de aquellos en que sí lo fue.

Caso de prueba de Leo: *"cambio de posicion de Rogers cuando no jugo Joao Pedro?"* → `get_position_changes(player="Rogers", absent_player="Joao Pedro")`.

## Tres estados de afirmación (`claim_status`)

| Estado | Qué es | Ejemplo |
|---|---|---|
| `observed` | un hecho del once guardado | "empezó de mediapunta; en sus 3 inicios anteriores fue banda derecha" |
| `associated` | dos hechos observados que coinciden | "coincidió con la ausencia de X en el once inicial (en el banquillo / no figuraba)" |
| `hypothesis` | posible vínculo que el dato no establece | "sin demostrar: ocupó la posición habitual de X" (solo si la posición habitual de X es la que tomó el jugador) |

## Reglas de redacción (en la descripción de la herramienta y en el renderizador)

Permitido: *"empezó en otra casilla"*, *"coincidió con la ausencia de X"*. Prohibido: *"se movió en el partido"* (la casilla es la del once anunciado, no un movimiento), *"por la lesión"* (ninguna causa), *"rendirá más"* (ninguna predicción), "debilidad". Además:

- **provisional ≠ confirmado**: cada partido lleva `lineup_status`; si hay confirmado, gana al provisional del mismo partido.
- **ausencia del once ≠ lesión**: `presence` (banquillo / no figura) y `listed_sidelined` (lista de bajas del proveedor ese día) van por separado.
- **un titular que el almacén no pudo mapear** se marca `may_be_unmapped` en vez de llamarlo ausente (el almacén descarta a los jugadores que no emparejan con FPL).
- **muestra pequeña** se dice (`sample.small_sample`, menos de 5 partidos con once guardado; con `absent_player`, menos de 3 de cada lado). **La historia empieza cuando empezó la ingesta**, así que al principio habrá pocos partidos.
- Un cambio solo se afirma con al menos 2 inicios anteriores del propio jugador como referencia; sin eso, no se dice nada.

## Mismo rol, otra casilla: línea o columna

Un cambio de **rol** (posición o lado) sigue diciéndose "empezó en otra casilla (antes: X)". Si el rol es el mismo pero la casilla de la rejilla (`fila:columna`) difiere de la habitual, `football_intelligence.position_changes._line_shift` decide entre tres cosas, solo con los inicios previos del jugador **con ese mismo rol** (mínimo 2):

| Resultado | Cuándo | Qué se muestra |
|---|---|---|
| `further_forward` / `deeper` | otra **línea** | cambio de tipo `line`: "mismo rol, otra línea: más adelantado / más retrasado"; cuenta en el héroe |
| `column_only` | misma formación, misma fila, otra columna | no es cambio: `column_shift: true`, sin nota y sin contar en el héroe |
| `not_comparable` | formación desconocida, casilla ilegible o menos de 2 inicios comparables | `line_comparable: false`: "mismo rol; línea no comparable" |

**Normalización.** Las filas se numeran por formación (fila 1 = portero; `4-2-3-1` tiene cuatro líneas de campo en las filas 2 a 5), así que la fila cruda **solo se compara dentro de una misma formación**. Entre formaciones se usa la profundidad `(fila − 2) / (líneas − 1)`, de 0.0 (línea defensiva) a 1.0 (línea de ataque), y solo se afirma otra línea si se mueve al menos `LINE_STEP_MIN = 0.25`; menos que eso es la misma línea vista desde otra forma (`same_line`, sin nota). Es una aproximación: una línea de 3 y una de 5 cuentan igual. Probada con 4-2-3-1, 4-3-3, 4-4-2, 3-4-2-1, 3-5-2, 5-3-2 y 4-1-4-1.

## Asociaciones y aviso de muestra (umbrales)

- **Asociaciones:** como máximo 2 compañeros nombrados por partido (`MAX_ASSOCIATIONS`). Orden: (1) figuraba en la lista de bajas ese día, (2) su rol habitual coincide con el nuevo rol del jugador (`role_match`), (3) el resto no se nombra: `associations_more` lo cuenta ("y N más").
- **Dos avisos independientes**, cada uno con su texto: "Solo N partidos con alineación" desaparece con **al menos 5 partidos con alineación guardada del jugador** (`SMALL_SAMPLE_BELOW`; `sample.lineups_needed` dice cuántos faltan); con `absent_player`, "Solo K partidos sin X" y "Solo M partidos con X" desaparecen con **al menos 3 partidos sin él y 3 con él** (`ABSENCE_MIN_EACH_SIDE`; `absence_focus.without_needed` y `with_needed` dicen cuántos faltan de cada lado).

## Identidad: dónde vive el bug de subcadena

- **La causa** está en `find_players` (`fpl_grounded_assistant/find_players.py`): su rango 2 es una búsqueda por subcadena a propósito (`allow_substring=True`), y el nombre completo de Costinha (Brighton) contiene "João Pedro". Es una herramienta de **búsqueda**, no de resolución; no se cambia aquí.
- **El resolvedor de un jugador** (`tool_resolve_player`, `fpl-tool-contract`) compara nombres completos, no subcadenas: con "João Pedro" y los dos jugadores presentes devuelve `ambiguous` con ambos candidatos (club incluido), nunca Costinha en silencio. Hay un test con los dos jugadores.
- **B4 no usa subcadenas**: resuelve al jugador con `tool_resolve_player`; al compañero ausente lo resuelve igual y además lo **acota al club del jugador por id FPL y código de club** (así "João Pedro" junto a Rogers es el del Chelsea; un jugador de otro club se devuelve como `not_a_teammate`). En el almacén todo se une por **id de elemento FPL + club de la fila del partido**; el nombre solo se añade al final para mostrarlo. Un jugador que cambió de club se lee con el club en que jugó ese día.
- Lo que sí puede pasar con "João Pedro" a solas (sin Rogers delante): `ambiguous` con candidatos, y la conversación debe preguntar (o usar el club del contexto).

## Datos que necesita y de dónde salen

- Almacén licenciado (tablas `lineup_snapshots`, `lineup_slots`, `sidelined`, `squad_membership`), solo lectura, vía `LicensedRuntimeHandle` (rechaza `live_trial_local`, exige `licensed_starter`, no sirve `crosswalk`).
- Lista de partidos de FPL (`get_all_fixtures`, API gratuita de FPL) para pasar el id de partido a jornada, fecha, rival y local/visitante; caché de 10 minutos. Si no se puede leer: `missing_context` (`fixture_list_unavailable`).
- Nada crudo sale: ni filas del almacén, ni ids de partido, ni ids de proveedor; la salida son valores derivados por jugador.

## PR 3: la tarjeta

La tarjeta reutiliza el contrato `generic_card` que la interfaz ya pinta (ver `GenericCard.tsx`), así que **no hay componente nuevo** y el español existente no cambia: `compose_position_changes_card` (`atomic_tool_cards.py`) construye la tarjeta a partir de la salida determinista de la herramienta, en el idioma de la petición (`locale` llega desde `ask_v2`). Una fila por partido con once guardado: jornada (`J7`/`GW7`), rival con local/visitante, la casilla en que figuró como titular y una nota que es el cambio observado ("Empezó en otra casilla (antes: Banda derecha)"), la ausencia asociada ("Coincidió con la ausencia de X") o nada.

- Subtítulo fijo: "Once inicial anunciado, no un movimiento durante el partido" / "Announced starting XI, not movement during the match".
- Píldoras: muestra pequeña, alineación provisional, y (con `absent_player`) la posición habitual sin ese compañero en el once.
- Pie: procedencia con la fecha de la build. Sin ids de partido, de proveedor ni filas del almacén.
- Solo se compone en turnos de una única herramienta y si la respuesta es `ok` con partidos; en cualquier otro caso queda el texto determinista.
- El texto de posición (`role_text`) está compartido con el renderizador, así que tarjeta y prosa no pueden divergir. Los pares ES/EN están en el catálogo (`gcard.position_changes.*`).

## Qué NO hace B4

No predice ni atribuye causas, no muestra movimiento durante el partido, no sirve filas del almacén y no se enciende solo: sigue detrás de `FOOTBALL_INTELLIGENCE_ENABLED` y del sync licenciado, ambos apagados hasta que el cerebro lo apruebe.
