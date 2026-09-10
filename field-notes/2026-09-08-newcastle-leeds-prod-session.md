---
title: "Newcastle–Leeds J4 en prod — la misma pregunta por dos tools, una no-respuesta de 79 caracteres, y la identidad del usuario que se cae al continuar la conversación"
found_via: sesión de dogfooding en app.benditofantasy.com; el Network de DevTools se abrió tarde y no grabó nada, así que la evidencia se recuperó del audit log NDJSON del contenedor de Railway
captured: 2026-09-08
relevant_to: [orchestrator, fixtures, contracts, instruments, ui, data-quality]
status: new
---

## What prompted this

Sesión de preguntas en producción sobre **Newcastle vs Leeds (J4)**, la tarde del
2026-09-08 hora local. Las respuestas en pantalla se veían dispares y valía la
pena capturarlas.

El intento de capturar por DevTools **falló**: el panel Network solo graba
mientras está abierto, y se abrió después de preguntar (`0 / 3 requests`, ningún
`proxy`). Las requests de la sesión no eran recuperables del browser.

La evidencia salió del **audit log del lado del servidor**: `/ask` y
`/session/{id}/ask` escriben una línea NDJSON por turno vía `write_audit_entry()`.
Se recuperó por `railway ssh` desde el contenedor vivo:

```
cat /app/packages/fpl-grounded-assistant/audit_logs/2026-09-09.ndjson
```

El archivo va bajo fecha **UTC** ([audit.py:194](../packages/fpl-grounded-assistant/fpl_grounded_assistant/audit.py#L194)),
por eso `09-09` para una sesión del `09-08` local. Copia íntegra en
[`artifacts/2026-09-08-newcastle-leeds-audit.ndjson`](artifacts/2026-09-08-newcastle-leeds-audit.ndjson).

**Advertencia sobre esta evidencia:** [railway.toml](../railway.toml) no declara
volumen, así que `audit_logs/` es efímero. El directorio se creó `01:04` UTC y el
primer turno registrado es `01:04:09` — el contenedor arrancó justo antes de la
sesión. No hay historia previa y un redeploy la borra. Cinco turnos es lo que
había; ver *Open questions*.

---

## Findings

### 1. Pregunta específica contestada con un volcado de la jornada completa — severity: high

**What happens:** «Newcastle vs LEE (a domicilio), J4: ¿qué tal pinta
**ofensivamente** para el Newcastle?» se resuelve con
`get_fixtures_for_gw(gw_number=4)` — la lista de **todos** los partidos de la GW4
con su FDR local/visitante. No dice nada sobre la amenaza ofensiva del Newcastle.

**Evidence:** turno `01:04:09.566090Z`. `outcome: ok`, `branch: orchestrator`,
`final_text_length: 783`. Texto completo capturado por screenshot — las 10
fixtures de la GW4 con su FDR, ninguna línea sobre el Newcastle en particular:

```
Partidos GW4:
GW4: AVL vs NFO (kickoff: 2026-09-12T14:00:00Z) | FDR local 3, FDR visit 4
GW4: BOU vs BRE (kickoff: 2026-09-12T14:00:00Z) | FDR local 3, FDR visit 3
GW4: CHE vs HUL (kickoff: 2026-09-12T14:00:00Z) | FDR local 2, FDR visit 4
GW4: CRY vs IPS (kickoff: 2026-09-12T14:00:00Z) | FDR local 2, FDR visit 3
GW4: LIV vs FUL (kickoff: 2026-09-12T14:00:00Z) | FDR local 2, FDR visit 4
GW4: TOT vs EVE (kickoff: 2026-09-12T16:30:00Z) | FDR local 3, FDR visit 3
GW4: SUN vs ARS (kickoff: 2026-09-12T19:00:00Z) | FDR local 4, FDR visit 3
GW4: COV vs BHA (kickoff: 2026-09-13T13:00:00Z) | FDR local 2, FDR visit 2
GW4: MUN vs MCI (kickoff: 2026-09-13T15:30:00Z) | FDR local 4, FDR visit 4
GW4: LEE vs NEW (kickoff: 2026-09-14T19:00:00Z) | FDR local 2, FDR visit 3
```

**Origen de la pregunta — no fue texto libre.** La sesión arrancó dando click en
la celda GW4 del Newcastle, vista de ataque, en el calendario (`/fixtures`). Ese
click genera el texto de la pregunta de forma determinística vía
`fixtureCellQuestion()` en
[fixture-chat-links.ts:24-32](../packages/fpl-ui/lib/fixture-chat-links.ts#L24-L32),
llamada desde `FixtureCompactGrid.tsx:112`, `FixturesBoard.tsx:289` y
`FixtureTendencyChart.tsx:156`. El propio comentario del archivo dice: *"El
usuario le entrega una pregunta ya armada para que las engines dueñas
respondan en el chat"* (Track D / FI7). O sea: **el deep-link que el producto
diseñó a propósito para esta acción falla en su primer intento**, no fue una
formulación ambigua del usuario la que confundió al router.

**Where:** elección de tool del orquestador; el volcado es la salida normal de
`get_fixtures_for_gw`.

**Why it happens:** mismo patrón que el hallazgo 1 de
[2026-08-28](2026-08-28-captain-answer-nondeterminism-prod.md) — una tool
ancla-de-jornada gana la selección frente a una pregunta específica, y su salida
genérica pasa como respuesta. Allá el atractor medido fue `get_gameweek_context`;
**esta es una instancia nueva con otra tool**, lo que sugiere que el atractor es
la *forma* de la salida (un volcado de GW plausible), no una tool en particular.

**Fix direction:** el catálogo de i38 midió `get_gameweek_context` como atractor
general. Conviene volver a correr esa medición incluyendo `get_fixtures_for_gw`
antes de decidir podas — la nota de i38 ya advierte de no podar por un solo caso
observado. Dado que el punto de entrada es un botón del propio producto con
pregunta fija, este es el caso más barato de arreglar de todo el catálogo: un
solo texto de pregunta, reproducible a voluntad, sin depender de que el usuario
la escriba "bien".

**Nota de producto (del usuario):** los turnos 4 y 5 de esta misma sesión —
alcanzados por texto libre de seguimiento, no por el botón — sí entregan el
tipo de análisis que este botón debería dar por default: fixture + localía +
fuerza del rival + jugadores con datos de forma/xG, con veredicto. La brecha no
es de ambición de producto sino de que el botón enruta a la tool equivocada; la
`teamOutlookQuestion` / `fixtureCellQuestion` ya existen exactamente para
disparar esto.

---

### 2. Tres intentos idénticos, dos tools, dos respuestas distintas — severity: high

**What happens:** la **misma pregunta literal** se lanzó tres veces en menos de
cuatro minutos y produjo dos comportamientos distintos.

**Evidence:**

| turno | timestamp | tool elegida | largo respuesta |
|---|---|---|---|
| 1 | `01:04:09` | `get_fixtures_for_gw(gw_number=4)` | 783 |
| 2 | `01:05:42` | `get_fixture_outlook(axis=attack, team_query=Newcastle, horizon=1)` | 79 |
| 3 | `01:07:49` | `get_fixture_outlook(axis=attack, team_query=Newcastle, horizon=1)` | 79 |

Los tres con `outcome: ok`, `branch: orchestrator`, `provider: gemini`.

**Why it happens:** varianza de muestreo del LLM en la elección de herramienta —
segunda instancia en producción del mecanismo del 08-28. Los turnos 2 y 3
convergen a la misma tool y dan salida idéntica, así que la varianza está en la
selección, no en la síntesis.

**Fix direction:** ya conocido y sin compuerta que lo vea. Se registra aquí como
segunda observación en prod para que la frecuencia deje de ser anecdótica.

---

### 3. Una no-respuesta de 79 caracteres cuesta 52.817 tokens y sale como `ok` — severity: high

**What happens:** a «¿qué tal pinta ofensivamente para el Newcastle?»,
`get_fixture_outlook` responde entero:

```
Calendario sin rachas claras en el horizonte.
  J4: LEE (fuera), dificultad 3/5
```

Con `horizon=1` la frase sobre «rachas» es vacua por construcción — una racha
necesita varios partidos. La tool se llamó con el horizonte que garantiza que su
propio mensaje principal no aplique, y de amenaza ofensiva no dice nada.

**Evidence:** turnos `01:05:42` y `01:07:49`. `final_text_length: 79`,
`output_status: ok`, `outcome: ok`. Tokens del turno 2: `total 52817`
(`primary_input` 20772, `primary_cache_read` 20506, `evaluator` 875,
`retry_input` 10299), `usd_cost_estimate: 0.00265925`.

**Fix direction:** dos cosas separables — (a) `axis=attack` con `horizon=1`
debería ser una combinación que la tool rechace o reinterprete, y (b) 79
caracteres tras 52k tokens es la señal barata que ninguna compuerta mira.
`final_text_length` ya está en el audit; un piso por intent es medible sin
decidir política nueva.

---

### 4. `retry_attempted` está cableado a `False` y lo desmienten los tokens del mismo registro — severity: med

**What happens:** el campo afirma que no hubo reintento en turnos donde los
propios tokens del registro muestran que sí lo hubo.

**Evidence:** turno `01:04:09` → `"retry_attempted": false` junto a
`"retry_input": 10304, "retry_output": 249`. Igual en `01:05:42` (10299/113) y
`01:07:49` (10294/83). El turno `01:08:55` tiene `retry_input: 0,
retry_output: 0` **y** `retry_attempted: false`, o sea que el campo acierta solo
cuando por casualidad coincide.

**Where:** [fpl_server.py:2062](../packages/fpl-grounded-assistant/fpl_server.py#L2062)
— `retry_attempted=False,` literal en la única construcción de entrada de `/ask`.
El parámetro existe en `make_audit_entry`
([audit.py:247](../packages/fpl-grounded-assistant/fpl_grounded_assistant/audit.py#L247))
y nadie le pasa otra cosa.

**Why it happens:** placeholder que nunca se cableó, igual que
`evaluator_verdict=None` en la línea de arriba — ese sí lleva el comentario
`not yet surfaced in ask_v2 dict (P3.2)`; este no lleva ninguno.

**Fix direction:** cablearlo o borrar el campo. Un `false` constante es peor que
la ausencia: se lee como medición. Mismo patrón que
[2026-08-13](2026-08-13-instruments-failing-silently.md) — el factor común es el
silencio, y aquí el desmentido vino de una segunda señal dentro del mismo
registro.

---

### 5. La identidad y el tier del usuario se pierden al continuar la conversación — severity: high

**What happens:** los turnos 1–4 llegan como `user_id: 7339d562062e2f65`,
`tier: patreon_premium`. El turno 5, mismo usuario y misma sesión, llega como
**`user_id: "anonymous"`, `tier: "free"`**.

**Evidence:** turno `01:10:53.846109Z`, `branch: "session"` — el único que pasó
por `/session/{id}/ask` («Seguir conversación →»). `"anonymous"` aparece sin
hashear porque `hash_user_id()` lo devuelve tal cual
([audit.py:98](../packages/fpl-grounded-assistant/fpl_grounded_assistant/audit.py#L98)),
lo que prueba que el header **no llegó**, en vez de haber llegado vacío.

**Where:** [session/[id]/ask/route.ts:38](../packages/fpl-ui/app/api/session/%5Bid%5D/ask/route.ts#L38)
manda `headers: { 'Content-Type': 'application/json' }` y nada más. El proxy
hermano [proxy/route.ts:39](../packages/fpl-ui/app/api/proxy/route.ts#L39) sí lee
`x-user-id` / `x-user-tier` y los reenvía. El middleware los inyecta bien para
ambos ([middleware.ts:38](../packages/fpl-ui/middleware.ts#L38)): se pierden en el
reenvío, no en la inyección.

**Why it happens:** una ruta de proxy se escribió sin el bloque de reenvío que
tiene la otra. `_extract_user_context` cae entonces a sus defaults
(`"anonymous"`, `FPL_DEV_TIER` o `"free"`).

**Consecuencias, las tres visibles en este mismo registro:**

1. **Cuota contra un bucket anónimo compartido.** El middleware documenta
   explícitamente que el sign-in existe *"so each free user gets their own
   per-user quota bucket rather than sharing one anonymous bucket"* — y todo
   turno de continuación cae justo en ese bucket compartido.
2. **El tier premium no aplica** en esos turnos: llegan como `free`.
3. **El audit no puede atribuir el turno** a ningún usuario.

**Fix direction:** copiar el reenvío de headers de `proxy/route.ts` a
`session/[id]/ask/route.ts`, y revisar de paso las otras rutas bajo
`app/api/session/` por el mismo olvido. Fix chico con efecto de facturación, no
cosmético.

---

### 6. El audit de los turnos de sesión reporta coste cero por construcción — severity: med

**What happens:** el turno 5 generó 1.729 caracteres con el LLM y quedó
registrado con `tokens: {}` y `usd_cost_estimate: 0.0`.

**Evidence:** turno `01:10:53`, `"tokens":{}`, `"usd_cost_estimate":0.0`, contra
`total: 44872` / `$0.00212945` del turno 4, que produjo menos texto.

**Where:** [fpl_server.py:2284](../packages/fpl-grounded-assistant/fpl_server.py#L2284)
— `tokens={}` literal dentro del `make_audit_entry` de sesión que empieza en
[2277](../packages/fpl-grounded-assistant/fpl_server.py#L2277).

**Why it happens:** hardcodeado. Nótese que la **cuota** sí usa el valor real
(`_record_turn(_sess_user_id, entry.session.last_tokens, _sess_tier)` unas líneas
antes), así que esto es ceguera del audit y no, por sí solo, fuga de cuota — la
fuga de cuota es el hallazgo 5. Cualquier suma de coste por `usd_cost_estimate`
subestima, y subestima exactamente en los turnos de conversación multi-vuelta.

**Fix direction:** pasar `entry.session.last_tokens` al `make_audit_entry` de
sesión — es el valor que la línea de arriba ya tiene a mano.

---

### 7. `tool_calls: []` en la ruta de sesión no significa que no se llamaron tools — severity: med

**What happens:** el turno 5 registra `tool_calls: []`. Es tentador leerlo como
«esta respuesta se generó sin consultar datos» — y la respuesta en pantalla trae
números muy específicos (xGC de Trafford, xGI/90 de Wissa), así que esa lectura
sería una acusación de alucinación. **La lectura es inválida.**

**Evidence:** el `make_audit_entry` de sesión
([fpl_server.py:2277](../packages/fpl-grounded-assistant/fpl_server.py#L2277))
**no pasa `tool_calls`**, y el default del parámetro es `None → []`
([audit.py:245](../packages/fpl-grounded-assistant/fpl_grounded_assistant/audit.py#L245)).
El campo es constante `[]` en esa rama, pase lo que pase.

**Why it happens:** el mismo olvido de cableado del hallazgo 4, en otra rama.

**Fix direction:** cablearlo, o el audit de sesión no sirve para analizar routing.
Se registra sobre todo como advertencia de lectura: **el instrumento no distingue
«cero tools» de «no lo sé»**, y esa diferencia es la que separa una respuesta
fundamentada de una inventada.

---

### 8. `intent: "unsupported"` conviviendo con `outcome: "ok"` y una respuesta sustantiva — severity: low

**What happens:** el turno 5 sale con `intent: "unsupported"` y a la vez
`outcome: "ok"` y 1.729 caracteres de respuesta que en pantalla se ve completa y
razonada.

**Evidence:** turno `01:10:53`.

**Fix direction:** aclarar en el contrato qué combinación es legal. Si
`unsupported` puede acompañar a una respuesta buena, el campo no sirve para
filtrar y eso hay que decirlo por escrito.

---

### 9. El renderer de chat deja pasar literal `###` y `1.` en vez de darles formato — severity: med

**What happens:** las respuestas de los turnos 4 y 5 vienen del LLM con
encabezados Markdown (`### Leeds en defensa — GW4 vs Newcastle`,
`### Veredicto FPL`) y listas numeradas (`1. **Bogle** — £4.5m`). En pantalla,
los caracteres `###` y `1.` aparecen **literales** como texto plano — sin
jerarquía visual, mezclados con la prosa — mientras que `**negrita**` y las
viñetas `- `/`* ` sí se renderizan bien.

**Evidence:** confirmado por código, no solo por lectura del screenshot.
[`MarkdownLite.tsx`](../packages/fpl-ui/components/MarkdownLite.tsx) — el
renderer compartido por la burbuja de chat, multi-intent y las tarjetas de
búsqueda web — solo reconoce tres construcciones: párrafo, viñeta (`^[*-]\s+`)
y `**bold**` inline. No hay regla para `#`/`##`/`###` ni para listas numeradas
(`^\d+\.\s+`); cualquier línea que empiece así cae al branch de párrafo y se
imprime tal cual, `###` y todo.

**Where:** [MarkdownLite.tsx:49-65](../packages/fpl-ui/components/MarkdownLite.tsx#L49-L65)
— el bucle de líneas solo prueba `bullet = line.match(/^[*-]\s+(.*)$/)`.

**Why it happens:** el propio comentario del archivo lo declara a propósito
("Markdown mínimo sin dependencias... deliberadamente diminuto") pero la
cobertura se quedó corta frente a lo que el LLM efectivamente produce cuando
sintetiza una respuesta larga con estructura (secciones + ranking).

**Fix direction:** dos reglas más en el mismo estilo del archivo —
`^(#{1,6})\s+(.*)$` → encabezado con tamaño relativo, `^\d+\.\s+(.*)$` → mismo
tratamiento que la lista de viñetas pero con `<ol>`/numeración preservada. Es
una extensión local del mismo parser, no requiere una librería nueva.

**Nota de producto (del usuario):** al margen del defecto de render, el
contenido de fondo de los turnos 4 y 5 le gustó — profundidad de análisis
(localía, fuerza relativa, jugadores con forma/xG, veredicto) dentro de lo
esperado para ese tipo de pregunta, sin haber verificado los números
específicos uno por uno. El defecto es de presentación, no de sustancia
percibida.

---

## Anexo: texto completo de los turnos 4 y 5 (capturado por screenshot)

Citado por los hallazgos 9 y por la pregunta abierta sobre `played`/`form`.

**Turno 4** (`01:08:55`, «Hablame de la defensa por equipos...»):

```
### Leeds en defensa — GW4 vs Newcastle

Sí, Leeds es una opción razonable, aunque no la trataría como una defensa premium.

- Rival: Newcastle
- Localía: Leeds juega en casa
- FDR: 2, favorable
- El calendario de Leeds aparece como una racha fácil para la defensa.
- El equipo figura con fuerza defensiva global 3 y fuerza en casa 2.

### Jugadores de Leeds

1. Bogle — £4.5m
- 217 minutos
- 22 puntos, 7.3 por partido
- Forma: 7.3
- Estado: disponible; sin noticias negativas
- Mejor opción por combinación de forma, precio y potencial ofensivo.

2. Justin — £4.5m
- 270 minutos
- 16 puntos, 5.3 por partido
- Estado: disponible; sin noticias negativas
- Alternativa más segura en minutos, pero con menor techo ofensivo.

3. Muharemović — £5.0m
- 270 minutos
- 14 puntos, 4.7 por partido
- Estado: disponible; sin noticias negativas
- Menos atractivo que Bogle por precio y producción.

### Veredicto

- Para alinear: sí, especialmente Bogle.
- Para comprar pensando solo en Newcastle: aceptable, pero no suficiente motivo
  para hacer una transferencia.
- Expectativa: buenas probabilidades de una actuación defensiva sólida por el
  FDR 2 y la localía, pero el dato no garantiza portería a cero.

Recomendación: Bogle > Justin > Muharemović.
```

**Turno 5** (`01:10:53`, «De lo que llevamos del torneo...»):

```
### Lectura del Newcastle–Leeds

Conclusión: los datos apuntan a que Newcastle sí tiene opciones razonables de
marcar, pero no a un partido claramente favorable. La defensa de Leeds parece
competente, aunque no suficientemente sólida como para descartar goles.

- Newcastle juega fuera y el FDR del partido es 3, dificultad media.
- Newcastle tiene fuerza general 3 y Leeds también 3; en la tabla aparecen
  Newcastle 7.º y Leeds 9.º.
- El perfil defensivo de Leeds no es perfecto: su portero Trafford registra
  4,52 xGC y 11 paradas en 270 minutos, señal de que concede ocasiones y puede
  verse exigido.
- El principal argumento ofensivo de Newcastle es Wissa:
  - 261 minutos
  - disponible
  - sin noticias médicas
  - 1,40 xGI
  - 0,49 xGI/90
  - 1,35 xG
- Es el atacante del Newcastle con mejores números de amenaza goleadora.
- Elanga también ofrece cierta amenaza: 232 minutos, disponible, 0,76 xGI y
  0,29 xGI/90.
- Barnes ha jugado 270 minutos, está disponible y suma 0,28 xGI, pero sus datos
  ofensivos son bastante más modestos.

### Veredicto FPL

Esperaría al menos una posibilidad real de gol para Newcastle, pero no lo
trataría como un cruce de alta confianza. Wissa es el jugador más interesante
por datos, mientras que Elanga sería una opción secundaria. No recomendaría
cargar varios atacantes del Newcastle solo por este partido: el FDR medio y la
localía de Leeds moderan el optimismo.

Además, el bootstrap no proporciona resultados acumulados de los equipos
—aparecen con `played: 0` y `form: null`—, así que no hay datos suficientes
para afirmar con precisión cuántos goles se esperan o proyectar un marcador
concreto.
```

---

## Open questions

- **¿Fueron cinco turnos en total?** **Confirmado que no** — el usuario reporta
  que la sesión tuvo más de cinco turnos, pero "los importantes empezaron aquí"
  (el click al calendario). Los turnos anteriores a `01:04` cayeron fuera de la
  ventana de vida del contenedor y no son recuperables (sin volumen, ver
  advertencia al inicio de la nota). Se acepta el recorte: los cinco turnos
  documentados cubren el tramo relevante según quien hizo las preguntas.
- **Texto completo de las respuestas — resuelto por screenshot para los 5
  turnos.** Turnos 1, 4 y 5 se transcribieron completos arriba (hallazgos 1 y 9,
  y el texto del turno 5 en el hallazgo de abajo); los turnos 2 y 3 ya estaban
  completos en el audit — su `final_text_length: 79` es el texto entero, no un
  recorte de preview. El límite de 200 caracteres de
  [audit.py:261](../packages/fpl-grounded-assistant/fpl_grounded_assistant/audit.py#L261)
  ya no oculta nada en esta sesión.
- **La afirmación del turno 5 sobre `played: 0` / `form: null` — matizada, no
  contradicha.** Texto completo: *"el bootstrap no proporciona resultados
  acumulados de los equipos —aparecen con `played: 0` y `form: null`—, así que
  no hay datos suficientes para afirmar con precisión cuántos goles se esperan o
  proyectar un marcador concreto."* Es una afirmación sobre agregados a nivel
  **equipo**, no sobre los jugadores — los 270/261/232 minutos que sí describe
  son estadísticas **por jugador**, de otra parte del bootstrap. No es
  necesariamente una contradicción interna. Sigue sin trazarse a la fuente: no
  se confirmó si el bootstrap realmente trae `played`/`form` nulos a nivel
  equipo en GW4, ni si eso es esperable o es un bug de esos campos
  específicamente. **Abierto**, pero con el marco correcto.
- **¿Cuántas réplicas corre el servicio?** Si es más de una, cada una tiene su
  propio `audit_logs/` y este archivo es parcial por diseño. No se revisó.
- **El audit efímero es en sí mismo un problema de instrumento.** Sin volumen,
  toda la observabilidad de producción vive hasta el próximo deploy. Esta nota
  existe porque la sesión cayó por casualidad dentro de la ventana de vida de un
  contenedor.
