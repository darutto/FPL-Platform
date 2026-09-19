# i99 — "cinco turnos orquestados y luego silencio": el corte localizado

**Fecha:** 2026-09-17 · **Prod:** `/version` = `d76cadb3` (= `origin/main` #288) ·
`/healthz.orchestrator` = `{enabled: true, loop_enabled: false, max_rounds: 3, provider: openai, model: gpt-5.6-luna}`
antes y después de cada variante (sin reinicio de proceso entre corridas: los
`routing_counters` crecieron 0 → 5 → 9 → 16 de forma acumulada).
**Datos crudos:** `field-notes/artifacts/i99-quota-cut-2026-09-17.jsonl` (20 turnos, respuestas
enteras con `debug=true`, snapshot de `/healthz` + `/version` antes y después de cada variante).
**Script:** `packages/fpl-grounded-assistant/scripts/measure_i99_quota_cut.py`.

## Protocolo

Pregunta fija en las tres variantes: *«¿Qué jugadores pueden explotar la zona más débil de
la defensa del Chelsea?»*. Sin `X-User-Tier` (→ `free`, igual que la medición de la carta).
Identidad = `X-User-Id` fresco por corrida (`i99-<variante>-<hex>-user`), hasheado por
`_extract_user_context` antes de tocar la cuota.

| Variante | Identidad | Sesión | Turnos | Resultado |
|---|---|---|---|---|
| A | 1 usuario fresco | ninguna (`/ask`) | 7 | #1–#5 `ok` + `selected_tool=get_zonal_opportunity`; **#6 y #7 `outcome=quota_exceeded`**, `llm_used=false`, `supported=false`, `debug={}`, texto de upgrade |
| B | 1 usuario fresco | 1 sesión reusada (`/session/{id}/ask`) | 6 | #1–#4 `ok`; **#5 y #6 `quota_exceeded`** (¡antes del 5.º mensaje!) |
| C | usuario rotado por turno | 1 sesión reusada | 7 | **7/7 `ok`**, orquestador en todos |

## Hallazgos

1. **El corte es `quota.py` y NO es silencioso.** La 6.ª respuesta lleva
   `outcome="quota_exceeded"`, `intent="unsupported"`, `llm_used=false`, `supported=false` y
   `final_text` = mensaje de upgrade («Llegaste a tu límite de 5 mensajes al día…»). Un
   cliente que mire `outcome` lo distingue de un éxito sin ambigüedad; no hace falta
   `orchestration_absent` ni un outcome nuevo. La premisa «degrada al camino legado sin
   decirlo» de la carta es falsa: no hay camino legado, hay bloqueo con texto propio.
2. **El contador vive en el `X-User-Id` (hasheado), no en la sesión ni en el proceso.**
   Variante C (misma sesión, id rotado) da 7/7 orquestados; variante B (mismo id, sesión
   reusada) se corta igual que A. Coincide con `_redis_key(user_id, …)`.
3. **El «final_text distinto ("Rivales de Chelsea J4-J8…")» que la carta atribuye al 6.º
   turno es otra cosa: es el residual de i37.** Aparece en A#1, A#2, B#1 y B#4 — turnos 1.º,
   2.º y 4.º, no 6.º — siempre con `retry_attempted=true`, `synthesis_turn=false`,
   `evaluator_verdict.approved=false` (feedback: «verifica minutos jugados y
   disponibilidad») y **con** `selected_tool=get_zonal_opportunity`. Es el render crudo
   del reintento del evaluador. 4 de 16 turnos orquestados en esta muestra (25 %) lo
   entregaron; ese número va a la medición de i37 en el PR siguiente.
4. **Lo único que sí mentía: el texto del bloqueo por tokens.** En B el corte llegó tras
   4 mensajes porque los turnos de sesión pesan 51–64K tokens cada uno
   (`debug.tokens.total`: 61 489 + 51 195 + 54 128 + 63 819 = 230 631 ≥ 220 000 =
   `free.daily_token_cap`), y `_upgrade_prompts` decía igualmente «límite de 5 mensajes al
   día» a alguien que mandó cuatro (mientras el indicador de cuota de la UI le mostraba un
   mensaje disponible). `_upgrade_prompts(tier, reason)` elegía la ventana por `reason`
   pero no el tipo de tope. **Arreglado en este PR:** cuando `reason` es un tope de tokens
   el mensaje dice «límite de uso … por volumen de consultas» y no afirma un conteo de
   mensajes; tests nuevos en `tests/test_quota_upgrade_message.py`, mutados (ignorar el
   tipo de tope) → 3/4 mueren.

## Descartado (grep amplio del camino de `/ask`)

Ningún otro límite numérico cercano a 5: `_BOOTSTRAP_RETRY_DELAYS`, `horizon`/`top_n`
por defecto en `harness.py`, `FPL_ORCH_MAX_ROUNDS` (clamp 1–5, prod=3) — ninguno cuenta
turnos por usuario. Flags `FPL_*` leídos en el camino: `FPL_ORCH_{ENABLED,LOOP_ENABLED,
LOOP_PROMPT,MAX_ROUNDS,MAX_RETRIES,MODEL,PROVIDER,TIMEOUT_S,EVAL_VERDICT_ONLY,
EXPERIMENT_OUTPUT}`, `FPL_EVAL_MODEL`, `FPL_DEV_TIER`, `FPL_SESSION_ENABLED`; ninguno
introduce un contador. `check_quota` se llama exactamente en dos sitios (`/ask` y
`/session/{id}/ask`) y ambos devuelven `OUTCOME_QUOTA_EXCEEDED` con texto — no hay chequeo
duplicado que bloquee sin texto.

## Nota de coste para las mediciones que siguen

Con tier `free`, un id fresco rinde **5 turnos por `/ask` y sólo ~4 por sesión** (los
turnos de sesión pesan más). Los verificadores de prod que ya rotan el id cada 5 turnos
(`verify_i93_composed_prod.py`) deben rotarlo cada 4 si miden por sesión (i100).

## Texto de carta propuesto (i99 → done)

> Localizado y medido 2026-09-17 (`d76cadb`, 20 turnos, 3 variantes): el corte es
> `quota.py` (tier free: 5 mensajes/día ó 220K tokens/día, contador por `X-User-Id`
> hasheado — rotar el id lo evita, reusar sesión no). NO es silencioso:
> `outcome=quota_exceeded`, `llm_used=false`, texto de upgrade. El «final_text distinto»
> que se vio era el render crudo del reintento del evaluador (i37), que sale en cualquier
> turno rechazado (4/16 aquí), no en el 6.º. Único defecto real: el bloqueo por TOKENS
> (que en sesión llega al 5.º mensaje, tras 4 turnos de 51–64K) decía «límite de 5
> mensajes». Arreglado: el mensaje nombra el tope que disparó. Sin cambio en
> `orchestration_absent`: no hace falta.
