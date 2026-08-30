# Encargo — superficie de capitanía

**Para:** Codex · **Preparado:** 2026-08-29 · **Estado:** sin empezar

Contexto completo y razonamiento:
`field-notes/2026-08-28-captain-answer-nondeterminism-prod.md` (findings 1–10).
Cartas del board: **i50** (capitanía no determinista) e **i51** (`get_chip_advice`
contesta otra pregunta). No hace falta leerlas para ejecutar este encargo, pero
sí antes de discutir el alcance.

---

## El problema en una frase

Las herramientas de capitanía **no saben expresar cuándo ni sobre quién** se
pregunta. Todo lo demás son síntomas.

Tres ejes faltan o están incompletos:

| eje | estado | consecuencia observada en producción |
|---|---|---|
| **1 · tiempo** | ausente en las tres herramientas | «¿a quién capitaneo en la fecha 3?» se contesta sobre la jornada actual, sin avisar |
| **2 · jugador** | inconsistente | «¿le doy el TC a Haaland?» se contesta sobre el mejor capitán global |
| **3 · pool** | no existe modo «rankea el pool» | la misma pregunta devolvió 3 candidatos una vez y 8 otra, con nombres distintos |

---

## Reglas de no-colisión — leer antes de tocar nada

Medido el 2026-08-29 contra `origin/main`. Hay **cero colisiones de código**:
todas las ramas vivas están en `main` o por detrás. Pero hay un fichero en
disputa y una zona ocupada.

**PROHIBIDO tocar en este encargo:**

1. **`roadmap-board/data.json`** — la rama `chore/board-i46-repro` tiene 3
   commits encima de main y toca **solo** ese fichero. Es el único punto de
   contención real. Si este trabajo necesita una carta de board, **pídela; no la
   escribas**.
2. **`orchestrator.py` (camino de síntesis) y `final_response.py` (fallback de
   render)** — territorio de **i46**, con dos worktrees activos
   (`chore/board-i46-empty-synthesis`, `chore/board-i46-repro`). El volcado crudo
   es suyo. No re-diagnosticar, no arreglar de paso.

**Trabajar en worktree propio.** Nunca en un checkout compartido: hay sesiones
paralelas vivas y las colisiones de rama/stash son silenciosas.

---

## Mapa de ficheros

Todo lo que este encargo puede tocar:

| qué | dónde |
|---|---|
| Schemas de las 3 herramientas | `packages/fpl-grounded-assistant/fpl_grounded_assistant/tool_schema_registry.py` — `GET_CAPTAIN_SCORE_SCHEMA:232`, `RANK_CAPTAIN_CANDIDATES_SCHEMA:252`, `GET_CHIP_ADVICE_SCHEMA:328` |
| Implementación de las tools | `packages/fpl-tool-contract/fpl_tool_contract/tools.py` — `tool_get_captain_score():377`, `tool_rank_captain_candidates():505` |
| Consejo de chip | `packages/fpl-grounded-assistant/fpl_grounded_assistant/chip_advisor.py` — `_advise_triple_captain():265`, umbrales en `:94` |
| Motor de puntuación | `packages/fpl-captain-engine/fpl_captain_engine/captain_score.py` |
| Contrato intent↔tool | `packages/fpl-grounded-assistant/fpl_grounded_assistant/dispatcher.py` — `requires_candidates_list:229` |
| Dispatch | `packages/fpl-tool-runner/fpl_tool_runner/runner.py` |
| Tests | `packages/fpl-tool-contract/tests/test_tools.py`, `packages/fpl-grounded-assistant/tests/test_tool_description_argument_consistency.py` |

---

## Slice 0 — medir la varianza (antes de cambiar nada)

Hoy **no hay número**. Lo único observado son 2 o 3 fallos en ~5 turnos, con el
observador buscando el fallo. Eso no es una tasa y no debe citarse como tal.

**Escribir la regla de decisión dentro del script ANTES de la primera llamada**,
como en i41/i44, para que no se pueda ajustar después.

- Pregunta fija: `¿A quién debería dar el brazalete?`
- N repeticiones (≥20), proveedor y modelo explícitos, bootstrap congelado.
- Registrar por turno: herramienta elegida, lista de `candidates` que el modelo
  emitió, nº de candidatos, nombres, y `synthesis_turn`.
- **Métrica principal:** cuántas listas de candidatos *distintas* salen de N
  turnos idénticos.

**Regla pre-registrada sugerida:** si ≥3 listas distintas en 20 turnos, el eje 3
queda justificado por datos y no solo por estructura. Si sale 1 sola lista, la
varianza que se vio en prod tenía otra causa y **hay que parar y re-mirar** antes
de tocar el schema.

> El defecto estructural (no existe modo pool) es un hecho verificable en el
> schema y no depende de esta medición. Lo que la medición decide es si ese
> defecto es lo que el usuario está sufriendo.

---

## Slice 1 — eje 3: pool determinista

El más barato, el que más rinde, y no necesita datos nuevos ni toca fixtures.

**Hoy:** `rank_captain_candidates` declara `candidates` como **requerido**, y
`dispatcher.py:229` lo marca `requires_candidates_list: True`. No hay forma de
pedir «rankea el pool»: el modelo decide a quién nominar.

**Cambio:**
- `candidates` pasa a **opcional** en el schema y en
  `tool_rank_captain_candidates()`.
- Si falta o viene vacío: rankear un pool determinista derivado del bootstrap
  (mismo criterio que ya usa `_score_outfield_players` en `chip_advisor.py`, para
  no inventar un segundo ranking que discrepe del primero).
- Devolver **`pool_source`** en el payload: `"caller"` cuando el llamador dio la
  lista, `"derived"` cuando la derivó la herramienta. Sin eso no se puede
  auditar de dónde salió una respuesta.

**Criterios de aceptación:**
1. La misma pregunta N veces devuelve **la misma lista**, con el mismo orden.
2. Pasar `candidates` explícitos sigue funcionando igual que hoy (sin regresión).
3. `pool_source` viaja hasta la respuesta y es visible.
4. La descripción del schema deja de decir «candidates is required».

---

## Slice 2 — eje 2: jugador en `get_chip_advice`

**Hoy:** `GET_CHIP_ADVICE_SCHEMA` declara **una sola propiedad**, `chip`, con
`additionalProperties: False`. Por eso «¿le doy el triple capitán a Haaland?» se
contestó sobre Cherki: `_advise_triple_captain(bootstrap)` toma `ranked[0]`, el
máximo global.

**Cambio:**
- `player` opcional en el schema y en `_advise_triple_captain()`.
- Cuando venga: el veredicto es **sobre ese jugador**, y el top global se
  mantiene como contraste explícito («tu candidato 79 · mejor disponible 85»).
- Propagar `top_player` al payload `chip`. Hoy la tarjeta enseña `79.0` sin decir
  de quién es, junto a una pregunta sobre otro jugador.

**Arreglo suelto que va aquí porque es el mismo fichero y cuesta una línea:**
`chip_advisor.py` incrusta incondicionalmente *«whether you still have this chip
available is not known to this system»*, pero desde la Fase 8e1
(`final_response.py:285`) el sistema **sí** lo comprueba contra
`squad_context.chips_remaining`. Condicionar la frase a si llegó `squad_context`.

**Criterios de aceptación:**
1. Con `player`, el veredicto nombra a ese jugador y no al top global.
2. Sin `player`, comportamiento idéntico al de hoy.
3. La tarjeta muestra de quién es la puntuación.
4. Con `squad_context` presente, el disclaimer de disponibilidad no aparece.

---

## Slice 3 — eje 1: ventana temporal

**El más grande: toca lógica de fixtures y las tres herramientas.** Va al final
por eso. **No empezar sin cerrar 1 y 2.**

- `gameweek` y `horizon` opcionales en las tres.
- Mientras no existan —y también cuando el usuario no los dé— la respuesta debe
  **decir explícitamente que evaluó la jornada actual**, en vez de presentar el
  veredicto como si contestara la jornada pedida. Ese aviso es más urgente que
  el parámetro: hoy el sistema recomendó *«guarda el chip para un rival más
  débil»* cuando el rival más débil era justo el de la jornada preguntada.

---

## Slice 4 — corrección de review (2026-08-29) · BLOQUEANTE

Revisada la implementación de `fix/captaincy-surface`. Un solo bloqueante;
todo lo demás está aprobado.

**El pool derivado no tiene tope: son 283 jugadores.**

`captain_pool_elements()` devuelve todos los MID/FWD disponibles ordenados por
id, sin cap. Y nadie lo trunca aguas abajo:

- `tool_rank_captain_candidates` — sin top-N
- `final_response.py:1449` — itera todos hacia `captain_ranking`
- `renderer.py:252` — una línea por candidato

Medido contra el bootstrap en vivo: **283**. Antes la respuesta en producción
devolvía 8. Hoy una pregunta de capitanía sin candidatos explícitos hace 283
cálculos de puntuación, devuelve 283 entradas en la respuesta, 283 líneas de
texto y 283 filas de tarjeta.

**Por qué es urgente y no cosmético:** fabrica exactamente la condición de
*payload de herramienta grande*, que es el terreno que el frente de **i46** está
investigando. Es un riesgo de regresión cruzada entre dos trabajos.

**Cambio pedido:**

1. Cap en el pool **derivado** — 10–15 candidatos. `pool_source` ya distingue
   `caller` de `derived`, así que el tope se aplica **solo** al derivado y el
   camino explícito del llamador no cambia.
2. Test que fije el tope: pool derivado ⇒ `len(ranked_candidates) <= N`.
3. Test que fije el criterio de aceptación 1 del Slice 1, que quedó sin clavar:
   la misma pregunta N veces devuelve **la misma lista y el mismo orden**. Hoy
   es determinista por construcción (`sorted(key=id)`), pero nada lo pinea.

**No cambiar nada más.** El resto de la implementación está aprobado:
`captain_pool_elements` como fuente única para `_score_outfield_players` y para
`tool_rank_captain_candidates` es exactamente lo pedido, `pool_source` trata
bien la lista vacía, y la cobertura de Slice 3 incluye el caso que originó todo
(`test_chip_advice_refuses_to_present_current_fdr_as_future_analysis`).

**Corrección al encargo original, culpa del que lo escribió:** prohibí
`final_response.py` por nombre de fichero cuando quería decir *el área de render
de fallback*. Los cambios hechos ahí (`ChipAdviceMeta`, `_extract_chip_meta`,
`_apply_squad_overrides`, `respond()`) están fuera de esa zona y son correctos.
No hay que revertirlos.

---

---

# Encargo 2 — respuesta dual: tu plantilla vs global

**Depende de PR #195.** Basar sobre él o esperar a que entre: usa
`captain_pool_elements`, `pool_source` y el cap de 12 que introduce.

## La respuesta que se quiere

    A) Dentro de tu plantilla, los mejores candidatos son...
    B) Los mejores candidatos globales son...

Hoy solo existe B. El ranking es puramente global: `tools.py` no lee
`squad_context` en ningún punto. Por eso en producción recomendó a Cherki y a
Hinshelwood a un usuario que no los tiene.

## La restricción que decide el diseño

`get_my_squad()` (`fpl-grounded-assistant/get_my_squad.py:136`) **hace red** y
lee `bootstrap["_my_team_id"]`. `fpl-tool-contract` es **capa pura sin I/O**
—solo importa `get_players`/`get_teams`, que operan sobre el bootstrap—.

**Por tanto `tool_rank_captain_candidates` NO debe ir a buscar la plantilla.**
Meter red en la capa pura la rompe y duplica `get_my_squad`.

Y tampoco puede depender de que el modelo encadene `get_my_squad` +
`rank_captain_candidates`: eso es precisamente la no-determinación que acaba de
arreglar el Slice 1.

**Diseño pedido:** la plantilla se resuelve **deterministamente** en la capa de
`fpl-grounded-assistant` (dispatch de la herramienta es la costura natural; si
eliges otra, dilo y justifica), y se pasa hacia abajo como **ids**:

    tool_rank_captain_candidates(..., squad_player_ids: list[int] | None = None)

La capa pura recibe ids, no los busca.

## Forma del payload — UNA lista, no dos

Añadir `owned: bool` a cada entrada de `ranked_candidates`. **No** devolver dos
listas paralelas.

Razón: un jugador puede estar en las dos, duplicarlo invita a que se
contradigan y **dobla el payload que se manda al modelo**, que es justo el
terreno de i46/i49. Los bloques A y B son una decisión de **renderizado**, no de
contrato.

Campos nuevos de primer nivel:

- `squad_source`: `"connected"` · `"not_connected"` · `"unavailable"`
- `squad_excluded`: lista de jugadores de la plantilla que el filtro de
  disponibilidad dejó fuera (`status` en `i`/`s`/`u`).

## El problema que hay que resolver de verdad

Si tu mejor opción es la **número 40 del ranking global**, el cap de 12 la
excluye y el bloque A sale vacío o incompleto.

**El pool derivado pasa a ser:** `top 12 global` **∪** `todos los jugadores
elegibles de tu plantilla`. Cota máxima ~22 entradas — sigue siendo pequeño.

El cap de 12 sigue aplicando **solo** a la parte global. El bloque A no se
capea: una plantilla tiene 15 jugadores y como mucho ~10 son MID/FWD.

## Reglas de contenido

- **B no excluye a los tuyos.** «Mejores globales» debe ser el top global de
  verdad; esconder tus jugadores lo falsearía. Márcalos en su lugar. Que tu
  mejor opción coincida con la global es información útil, no redundancia.
- **Sin equipo conectado:** solo bloque B, y la respuesta **debe decirlo** —
  «no hay equipo conectado, te muestro solo el ranking global». Nunca enseñar un
  bloque en silencio como si fuera la respuesta completa. Ese es el caso
  anónimo que originó todo esto.
- **Nada se cae en silencio.** Un jugador de tu plantilla lesionado no puede
  desaparecer sin dejar rastro: va en `squad_excluded` y se menciona. Es
  exactamente el modo de fallo que persigue toda esta línea de trabajo.

## Criterios de aceptación

1. Un jugador de tu plantilla que sea el **#40 global** aparece con
   `owned: true`.
2. Sin equipo conectado: `squad_source: "not_connected"`, bloque B solo, y el
   texto lo declara.
3. Un jugador de plantilla no disponible aparece en `squad_excluded`, no
   desaparece.
4. El camino de `candidates` explícitos (`pool_source: "caller"`) no cambia.
5. Se mantiene el determinismo del Slice 1: misma pregunta N veces, misma lista
   y mismo orden.
6. La tarjeta renderiza los dos bloques y marca los propios dentro de B.

## Fuera de alcance

- El texto de las burbujas (`StarterPrompts.tsx`) sigue sin tocarse.
- `roadmap-board/data.json`, `orchestrator.py` (síntesis) y el render de
  fallback: siguen prohibidos, ahora también por **i49**.
- La latencia: los 283 se siguen puntuando. Es decisión de diseño abierta, no
  parte de este encargo.

---

# Encargo 3 — abrir el pool, acortar las listas, y un hipster de verdad

**Depende del Encargo 2**, ya implementado en `fix/captaincy-surface`.

## 1 · Quitar el filtro de posición

Decisión de producto del dueño: **no excluir a nadie por posición**. Hay gente
que considera capitanear a un defensa o a un portero, y el sistema no debería
decidirlo por ellos.

Hoy `captain_pool_elements` filtra `element_type in (3, 4)`.

**Medido contra la API en vivo (GW3), quitando ese filtro:**

    4 de los 12 primeros serían DEF/GKP
    el mejor defensa (De Cuyper, BHA) entraría en el puesto 2, por encima de Haaland

No quedan sepultados: el 80% de la puntuación —forma 40%, fixture 30%, minutos
10%— es ciego a la posición. Solo el 20% de xGI les penaliza.

**Consecuencia agradable:** `squad_excluded` deja de llenarse de
`not_eligible_position`. Pasa a contener solo lesionados y no disponibles, que
es lo accionable. La línea de siete nombres desaparece sola.

## 2 · Mostrar la posición en la tarjeta

**Imprescindible si entran porteros y defensas.** Hoy la tarjeta solo enseña
nombre y equipo, así que un portero sería indistinguible de un delantero.

## 3 · Acortar ambas listas

    A) tu plantilla   ->  top 3  + 1 hipster
    B) globales       ->  top 5  + 1 hipster

**Cuidado con la invariante que acaba de construirse.** El Encargo 2 garantiza
que cada jugador propio se contabiliza exactamente una vez. Ese recuento debe
seguir cuadrando **en el payload** — los 15 siguen repartidos entre evaluados y
`squad_excluded`. El recorte a 3+1 es de **presentación**, no de contrato. Si se
capa el payload, se rompe la auditoría que costó un ciclo de review construir.

## 4 · «Hipster» se calcula por propiedad, NO por el tier actual

**Trampa verificada, leer antes de implementar.** El tier `differential` de hoy
es una banda de puntuación:

    differential  =  captain_score >= 30  AND  minutes_risk <= 30

`captain_tiers.py` lo declara en su cabecera: *"no ownership data, no external
API"*. Sacar el hipster de ahí devolvería **el jugador peor puntuado** de la
lista, que es lo contrario de lo que se pide.

**Usar `selected_by_percent`**, que ya viaja en el cliente de la API
(`fpl_client.py:137`) pero el tier ignora.

Definición propuesta, ajustable: *el jugador de menor propiedad entre los que
superan el umbral de `upside` (score ≥ 45, minutes_risk ≤ 25)*. El umbral evita
que el hipster sea simplemente alguien malo y poco poseído.

El hipster de A sale de tu plantilla; el de B, del pool global. Si el hipster ya
está en el top, coger el siguiente y decirlo.

## 5 · Lo que NO hay que hacer

**No añadir un término de «techo» a la fórmula.** Es la objeción real a abrir el
pool: la puntuación trata «6 puntos casi seguros» igual que «6 de media con cola
de 20», y para capitanear esa cola es lo que importa. Pero los coeficientes por
posición de la Fase 8a quedaron marcados como *experimento v1, calibrar contra
resultados antes de confiar*. Ajustar pesos a ojo aquí es exactamente lo que ahí
se desaconsejó.

Ese matiz se remite a **i54**, que ya va a revisar qué significan los tiers.

**Y de paso, para i54:** el nombre `differential` es engañoso en el vocabulario
del propio producto. Si va a existir un hipster real por propiedad, ese tier
debería renombrarse a algo que describa lo que hace — una banda de puntuación.

## Criterios de aceptación

1. Un defensa o portero puede aparecer en ambos bloques, con su posición visible.
2. `squad_excluded` ya no contiene `not_eligible_position`; el recuento de 15
   sigue cuadrando en el payload.
3. A muestra 3 + 1; B muestra 5 + 1. El payload sigue completo.
4. El hipster se deriva de `selected_by_percent` y respeta el umbral mínimo.
5. Si no existe hipster que cumpla el umbral, se dice; no se rellena con
   cualquiera.

---

## Lo que este encargo NO hace

- **No toca el texto de las burbujas** (`StarterPrompts.tsx`). El copy no debe
  adelantarse al schema: una burbuja que promete algo que la herramienta no sabe
  expresar es exactamente cómo llegamos aquí. Se afina **después** de los slices
  1–3.
- **No arregla la elección de herramienta.** Eso es **i38**, ya medido con 450
  observaciones, y su arreglo va en la descripción del schema de
  `get_gameweek_context`, no aquí.
- **No arregla el volcado crudo.** Eso es **i46**, ocupado.
