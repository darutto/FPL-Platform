# i96 + i37 — la entrega del reintento del evaluador: qué audita y qué entrega

**Fecha:** 2026-09-17 · **Prod medido:** `/version` = `d76cadb3` (= `origin/main` #288),
`gpt-5.6-luna`, evaluador activo, `loop_enabled=false`.
**Datos crudos:** `field-notes/artifacts/i37-retry-population-pre-2026-09-17.jsonl` (10 turnos
mixtos por `/ask`, `debug=true`, respuestas enteras) y
`field-notes/artifacts/i99-quota-cut-2026-09-17.jsonl` (16 turnos zonales orquestados, misma
fecha, medidos para i99). **Script:**
`packages/fpl-grounded-assistant/scripts/measure_i37_retry_population.py`.

## i37 — medir antes de decidir

La carta pedía medir cuántos turnos llegan de verdad al camino «el evaluador rechaza, el
reintento llama a una herramienta y se entrega el `render()` crudo» antes de pagarle una
llamada de síntesis. #160 lo había medido en 1/40 por endpoint.

| # | pregunta | outcome | tool | retry | synthesis | render crudo |
|---|---|---|---|---|---|---|
| 1 | ¿A quién capitaneo esta jornada? | ok | rank_captain_candidates | **True** | **False** | **sí** |
| 2 | ¿Quién es mejor capitán, Haaland o Salah? | unsupported_intent | None | **True** | **False** | **sí** |
| 3 | ¿Qué tal pinta el calendario del Arsenal…? | ok | get_team_schedule | False | True | no |
| 4 | Dame el resumen de Bruno Fernandes | ok | get_player_snapshot | — (determinista) | — | no |
| 5 | ¿Qué jugadores pueden explotar la zona… del Chelsea? | ok | get_zonal_opportunity | False | True | no |
| 6 | ¿Quiénes son los 5 máximos goleadores…? | ok | rank_players_by_metric | False | True | no |
| 7 | ¿Qué defensas baratos tienen buen calendario? | ok | get_transfer_suggestion | False | True | no |
| 8 | ¿Cómo está el Liverpool defensivamente? | ok | get_fixture_outlook | False | True | no |
| 9 | ¿Qué zonas débiles tiene el Tottenham? | ok | get_zonal_weakness | False | True | no |
| 10 | Compara a Palmer con Saka | ok | compare_players | **True** | **False** | **sí** |

Más los 16 turnos zonales de i99 (misma fecha): 4 con `retry_attempted=true`, los 4 con
`synthesis_turn=false` y el `render()` crudo («Rivales de Chelsea J5–J9: … in-box / central
(+0.321 vs media): Thierno Barry, …»).

**Total: 25 turnos orquestados → 7 rechazados por el evaluador (28 %) → 7/7 reintentos
llamaron a una herramienta en vez de escribir texto → 7/7 entregaron el render crudo.** No es
un residual de 1/40: es más de un cuarto de los turnos, y en todos el usuario recibe un
volcado en vez de una respuesta.

**Coste de la tercera llamada.** El reintento costó 11.6K de entrada en los turnos zonales
(`debug.tokens.retry_input`) sobre ~61K totales por turno; una síntesis del reintento pesa
lo mismo más la salida de la herramienta (~12–20K). Sobre el 28 % de turnos afectados:
≈ +20 % por turno afectado, ≈ +6 % del gasto total. **Decisión: se arregla.** El reintento
recibe UNA llamada de síntesis sobre sus propios resultados de herramienta (misma
`_build_multi_tool_follow_up` que el camino principal), sin re-parsear llamadas a
herramienta (no es el loop), sin segunda evaluación (el tope de un reintento sigue). El
render crudo queda como *fallback* solo si esa llamada falla o no trae texto. Tokens de la
síntesis van al cubo `retry_*` (se cobran aunque no haya texto — la lección de i46).

## i96 — el audit decía «cero» donde hubo dos

El turno #2 es la forma exacta que la carta vio en prod: `tool_sequence=['compare_players']`,
`retry_attempted=true`, `synthesis_turn=false`, `selected_tool=None`, `tool_calls=[]` en el
audit. Mecanismo, confirmado línea por línea:

1. El primario llama a `compare_players(Haaland, Salah)` → `status=not_found` (Salah no está
   en el bootstrap 2026-27). El evaluador rechaza.
2. El reintento vuelve a llamar a `compare_players` → mismo `not_found` →
   `OUTCOME_TOOL_RESULT_ERROR`.
3. `harness.ask_v2` cae en la rama «sin herramienta fundamentada»: `selected_tool=None`.
4. `audit.tool_calls_from_ask_v2` proyectaba desde `selected_tool` → `[]`.
5. Además, `tool_calls_trace` describía solo las llamadas del primario (el decorador
   `_attaches_tool_calls_trace` lo decía explícitamente: «an evaluator-retry's own tool calls
   are not appended»), así que ni el trace sabía del segundo `compare_players`.

**Arreglo (dos capas):**
- `orchestrator.py`: las llamadas que el reintento EJECUTA se añaden al `tool_calls_trace`
  con la misma forma de `_trace_entry` más `retry=True`, como la ronda siguiente a la última
  del primario (también la que lanza excepción). `tool_call_count` conserva su semántica de
  payload retenido.
- `harness.py`: las DOS ramas del orquestador proyectan `tool_calls_trace` compacto
  (`name/args/output_status/round/retry`, sin el `output` entero) al dict de `ask_v2`.
- `audit.py`: `tool_calls_from_ask_v2` proyecta desde `tool_calls_trace` cuando está
  presente — una entrada por llamada ejecutada — y cae a `selected_tool` solo para los dicts
  sin trace (ramas deterministas: router, resource, prompt, lookup; ahí la herramienta
  seleccionada ES la única llamada). Las dos superficies HTTP usan la misma proyección.

**Mutaciones (cada una por separado, cada una mata):** ignorar el trace en la proyección
(6 tests); la rama sin herramienta deja de proyectar el trace (3); el orquestador deja de
añadir las llamadas del reintento (1); ignorar el texto de la síntesis del reintento (1).

## Efectos colaterales revisados

- `routing_trace.tool_sequence` / `tool_args_sequence` ahora incluyen las llamadas del
  reintento (son «lo ejecutado»). Los verificadores y analizadores que leen `tool_sequence`
  (`scripts/analyze_*`, `verify_i93_composed_prod.py`) usan pertenencia (`in`) o el primer
  elemento (`seq[0]`); las entradas del reintento van al final — siguen válidos.
- `composed_primary_call` (i93) lee el trace: un reintento que añada un
  `get_fixture_outlook` a un primario `get_team_snapshot` promueve la llamada de calendario
  al slot singular; antes ese mismo turno ya entregaba `get_fixture_outlook` como
  `tool_chosen` del reintento, con la misma salida. Sin cambio de resultado.
- `is_single_distinct_tool_turn`: en una entrega de reintento `tool_call_count` es el del
  reintento (1) y decide solo; el trace no entra. Sin cambio.

## Fuera de alcance

- El test `test_evaluator_retry_render_is_a_known_residual_bare_render_path` documentaba el
  residual como aceptado; se reemplaza por tres tests que pinean el camino nuevo (síntesis
  con texto, fallback sin texto, tokens al cubo del reintento).
- La medición *post* en prod (mismo script, `post`) queda para después del deploy: se
  espera que los 3/9 turnos de reintento vuelvan con `synthesis_turn=true`.

## Texto de carta propuesto

**i96 → done.** Localizado y arreglado 2026-09-17: el reintento re-ejecutaba
`compare_players` con estado no-ok, la rama sin herramienta ponía `selected_tool=None` y el
audit proyectaba `[]`; además el trace excluía las llamadas del reintento por diseño. Ahora
`tool_calls_trace` lleva primario + reintento (`retry=True`), las dos ramas del orquestador
lo proyectan y `tool_calls_from_ask_v2` audita una entrada por llamada ejecutada (nombre,
args, estado), con `selected_tool` solo como fallback sin trace. Un turno multi-herramienta
también audita todas. 4 mutaciones separadas, cada una mata.

**i37 → done.** Medido 2026-09-17 en prod (25 turnos orquestados, luna): 7 rechazos del
evaluador, 7/7 reintentos llamaron herramienta, 7/7 render crudo — 28 % de los turnos, no
1/40. Coste de la síntesis del reintento ≈ +6 % total. Arreglado: el reintento recibe una
llamada de síntesis (sin loop, sin segunda evaluación); el render crudo queda como fallback.
Medición *post* pendiente de deploy.
