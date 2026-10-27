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

## Identidad: dónde vive el bug de subcadena

- **La causa** está en `find_players` (`fpl_grounded_assistant/find_players.py`): su rango 2 es una búsqueda por subcadena a propósito (`allow_substring=True`), y el nombre completo de Costinha (Brighton) contiene "João Pedro". Es una herramienta de **búsqueda**, no de resolución; no se cambia aquí.
- **El resolvedor de un jugador** (`tool_resolve_player`, `fpl-tool-contract`) compara nombres completos, no subcadenas: con "João Pedro" y los dos jugadores presentes devuelve `ambiguous` con ambos candidatos (club incluido), nunca Costinha en silencio. Hay un test con los dos jugadores.
- **B4 no usa subcadenas**: resuelve al jugador con `tool_resolve_player`; al compañero ausente lo resuelve igual y además lo **acota al club del jugador por id FPL y código de club** (así "João Pedro" junto a Rogers es el del Chelsea; un jugador de otro club se devuelve como `not_a_teammate`). En el almacén todo se une por **id de elemento FPL + club de la fila del partido**; el nombre solo se añade al final para mostrarlo. Un jugador que cambió de club se lee con el club en que jugó ese día.
- Lo que sí puede pasar con "João Pedro" a solas (sin Rogers delante): `ambiguous` con candidatos, y la conversación debe preguntar (o usar el club del contexto).

## Datos que necesita y de dónde salen

- Almacén licenciado (tablas `lineup_snapshots`, `lineup_slots`, `sidelined`, `squad_membership`), solo lectura, vía `LicensedRuntimeHandle` (rechaza `live_trial_local`, exige `licensed_starter`, no sirve `crosswalk`).
- Lista de partidos de FPL (`get_all_fixtures`, API gratuita de FPL) para pasar el id de partido a jornada, fecha, rival y local/visitante; caché de 10 minutos. Si no se puede leer: `missing_context` (`fixture_list_unavailable`).
- Nada crudo sale: ni filas del almacén, ni ids de partido, ni ids de proveedor; la salida son valores derivados por jugador.

## Qué NO hace este PR

La tarjeta de interfaz (PR 3). El texto determinista ES/EN ya existe en el catálogo (`renderer.position_changes.*`, 25 pares) porque el repositorio exige un renderizador por herramienta registrada.
