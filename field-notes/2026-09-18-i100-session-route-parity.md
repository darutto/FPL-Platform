# i100 — paridad `/ask` vs `/session/{id}/ask` para las frases canónicas del calendario

**Fecha:** 2026-09-18 · **Código:** `origin/main` d76cadb (+ el test determinista corrido también
sobre una fusión temporal de #292 y #294). · **Modelo:** `openai/gpt-5.6-luna` (pin de
`measure_tool_routing.py`, = Railway) · **Evaluador:** OFF (`FPL_EVAL_DISABLED=1`, paridad con el
`_eval_client=None` de i78-A) · **Bootstrap:** `field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json`
(J1 = próxima, el de i78-A) · **Corpus:** las 20 frases canónicas de
`i78a-canonical-phrases.json` tal como está hoy en el repo (i93-b lo regeneró: 4 equipos × {2 ejes,
celda, celda DGW sintética, celda futura}) + los 10 controles de i78-A · **R = 3**, orden fijo ·
**Tope declarado $3**, estimación previa $0.354 (fórmula de i78-A); el coste real no queda sellado
porque el camino HTTP no expone el gasto por turno (`/ask` ni siquiera devuelve tokens en `debug`) · **Datos crudos:**
`field-notes/artifacts/i100-session-route-parity-2026-09-18.jsonl` (cuerpos enteros de las dos rutas
por fila, `debug=true`) · **Scripts:** `scripts/measure_i100_session_route_parity.py`,
`scripts/analyze_i100_session_route_parity.py`.

Dos niveles, como pedía el plan.

## Nivel 1 — determinista: la misma vuelta serializada por las dos rutas

`tests/test_i100_route_parity_serialization.py`: UN `OrchestratorResult` por familia (salidas
reales de `run_tool` sobre `STANDARD_BOOTSTRAP` para captain ranking, comparación, ranking por
métrica, sugerencia de fichaje, lesionados; los payloads sintéticos de i97/i102 para zonal y
calendario), servido por `/ask` y por una sesión recién abierta, y los dos JSON aplanados a rutas
con punto y comparados **en presencia y valor**. Únicas claves excluidas, por nombre y con un test
que pinea que son exactamente esas: `session_id`, `rewritten_question` (sesión), `web_search`
(`/ask`), `debug` (formas distintas por diseño).

| estado del código | resultado |
|---|---|
| `origin/main` d76cadb | 7/8: **zonal falla** nombrando las rutas que la sesión pierde (`exploiters[0].club_source`, `n_shots`, `team_filter`, …) — es i97 (#292) |
| main + #292 + #294 (fusión temporal, limpia) | **8/8**, y los 17 tests de i97+i102+i100 juntos |

Punto ciego declarado: paridad no detecta «falta en las dos» — `fixture_outlook` era `None` en las
dos rutas en main y el test pasaba; la presencia la pinea i102.

## Nivel 2 — ruteo en vivo (smoke, no gate)

Cada frase se envía a `/ask` y, acto seguido, como PRIMER turno de una sesión recién abierta
(sin historial que justifique una diferencia legítima), mismo proceso, mismo bootstrap, mismo
modelo, id fresco por llamada.

**180 llamadas, 0 excepciones, 0 volcados de `get_fixtures_for_gw` fuera del control que lo pide
(`sh-c04`, 3/3 en las dos rutas).**

| familia | `/ask` acierta (3/3 → `get_fixture_outlook`, nunca el volcado) | sesión acierta | paridad (3/3 reps iguales en `selected_tool` + secuencia) |
|---|---|---|---|
| `teamOutlookQuestion` (8) | **7/8** | **5/8** | 4/8 |
| `fixtureCellQuestion` (12) | **12/12** | **4/12** | 4/12 |
| controles (10) | 0 migran | **1 migra** (`sh-c08` → `get_player_snapshot`) | 6/10 |

Reps que coinciden entre rutas: **60/90**. Tabla R×N completa y las 30 reps discrepantes:
`python scripts/analyze_i100_session_route_parity.py field-notes/artifacts/i100-session-route-parity-2026-09-18.jsonl`.

**Atribución de las 30 discrepancias, leída de `rewritten_question` en cada fila:**

| | con reescritura de sesión | sin reescritura |
|---|---|---|
| rutas discrepan | **28** | 2 |
| rutas coinciden | 2 | 58 |

Las 2 sin reescritura son ruido del modelo del lado de `/ask` (`fc-tot-def-team` r1: `/ask` fue a
`get_position_fixture_run` primero; `fc-mci-cell-dgw` r0: `/ask` añadió un `get_team_schedule`) —
el mismo ruido que i78-A ya conocía. **Las 28 restantes tienen todas la misma forma:** la sesión
reescribió la frase a «tell me about Newcastle / Man City / Liverpool / Spurs» (y dos veces a
**«tell me about null»** — el resolver devolvió la cadena `"null"` y `_build_canonical_question` la
tomó por un jugador) y el orquestador respondió a ESA pregunta con `get_team_snapshot`
(`intent=unsupported`, sin tarjeta de calendario) o con nada. Reescrituras en total: 30/90
(canónicas 18/60 = 30 %, controles 12/30); en 24 de las 30 cambió la herramienta elegida. El
único acierto de `/ask` que la sesión no reproduce sin reescritura no existe: cuando el resolver
deja la frase en paz, las dos rutas coinciden.

Los controles muestran lo mismo desde el otro lado: `sh-c02` («…Haaland…») se reescribe 3/3 a
«tell me about Haaland» y baja al router determinista (`intent=player_snapshot`, sin orquestador —
correcto en contenido, distinto en camino), `sh-c08` a «tell me about Salah» 3/3 (→ snapshot en vez
de forma), `sh-c03` a «what is the current gameweek» 3/3 (2 de ellas terminan `unsupported`).

### Mecanismo, confirmado línea por línea

El camino de sesión NO ve otro catálogo ni otro prompt: ve **otra pregunta**.
`ConversationSession.respond` (`conversation_state.py:1335`) llama a `resolve_reference` en TODOS
los turnos, también en el primero de una sesión vacía, y `resolve_reference` va primero al
resolver LLM (`reference_resolver.resolve_reference_llm`, proveedor `DEFAULT_PROVIDER` =
`gemini`, modelo `llm_layer.DEFAULT_MODEL` = `gemini-2.5-flash`). Ese resolver está diseñado para
seguimientos con pronombre y solo conoce *jugadores* (`resolved_query: "<player name string, or
null>"`); ante «Newcastle vs LIV (en casa) y Newcastle vs SUN …, J1 (doble jornada): ¿qué tal
pinta…?» a veces devuelve `resolved_query="Newcastle"` con confianza ≥ 0.5 e intent desconocido,
y `_build_canonical_question` lo convierte en **«tell me about Newcastle»** — que es lo que
recibe el orquestador. Con esa pregunta luna elige `get_team_snapshot`. Es no determinista (mismo
texto, distinta salida del resolver entre reps) y es exactamente la muestra de 1 de la carta
(Brentford → `get_team_snapshot` por sesión).

En prod el mismo resolver corre (`debug.resolver = {resolver_used: true, resolver_source: "llm",
resolver_confidence: 0.9}` en los 3 turnos de la sonda
`i100-prod-session-rewrite-probe-2026-09-18.jsonl`, sin reescritura en esos 3).

### Qué NO es

- No es el catálogo ni el prompt: `ask_v2` recibe el mismo bootstrap y el mismo registro por las dos
  rutas; cuando el resolver no reescribe (`rewritten_question == pregunta`), las dos rutas coinciden.
- No es el desvío que vio la sonda de prod para la frase DGW sintética (`orchestrator_outcome=
  tool_result_error`, «la J1 ya figura como pasada»): eso es la frase de J1 contra un bootstrap
  en J5 y le pasaría igual a `/ask`.

### Carta propuesta (nueva; no se arregla aquí a ciegas, como pedía el plan)

> **El resolver de referencias reescribe el primer turno de una sesión a «tell me about \<equipo\>».**
> `ConversationSession.respond` pasa TODA pregunta por `resolve_reference` (LLM, gemini-2.5-flash),
> incluido el primer turno de una sesión sin estado ni historial. El resolver solo entiende
> jugadores; ante una frase de calendario con un equipo, a veces (18/60 frases canónicas en esta corrida, 30 %) devuelve el
> equipo como `resolved_query` y la pregunta llega al orquestador como «tell me about Newcastle»
> → `get_team_snapshot`. Por `/ask` no pasa (no hay resolver). Opciones a decidir con medición: (a)
> no invocar el resolver LLM cuando la sesión no tiene estado ni historial (nada que resolver);
> (b) no construir «tell me about X» cuando X no resuelve a un jugador del bootstrap — y tratar la
> cadena `"null"` del resolver como `None` (hoy produce «tell me about null», 2/90); (c) las dos.
> Y el modelo `gemini-2.5-flash` está deprecado desde 2026-06-17 — el día que muera, el resolver
> cae a `llm_unavailable` en silencio (ya se vio 1 vez en esta corrida) y el problema desaparece
> por accidente, no por diseño.

## Texto de carta propuesto (i100 → done)

Medido 2026-09-18 con el protocolo de i78-A (28 canónicas + 10 controles, R=3, luna, tope $3,
JSONL crudo) por las dos rutas en el mismo proceso. Nivel determinista: test de serialización sobre
el mismo resultado por las dos rutas, payload anidado completo, 8/8 con #292+#294 (7/8 en main: la
zonal, = i97). Nivel vivo: `/ask` 7/8 + 12/12 vs sesión 5/8 + 4/12; paridad 8/20; 28 de las 30 reps discrepantes llevan una reescritura del resolver de la sesión («tell me about <equipo>», 2× «tell me about null») y las 2 restantes son ruido del modelo en `/ask`. La diferencia no es de catálogo ni de prompt: es
el resolver de referencias LLM de la sesión, que reescribe algunas frases de calendario a «tell me
about \<equipo\>» antes de `ask_v2` — carta nueva propuesta arriba.
