# i104 + i105 — el audit persiste donde diga el env y nombra el modelo que corrió

**Fecha:** 2026-09-20 · **Base:** `origin/main` = `5df06a7` · **Origen:** audit de prod del
2026-09-19 (`prod-audit-snapshot.ndjson`: 6 líneas, todas `provider=gemini` mientras
`/healthz.orchestrator` decía `openai / gpt-5.6-luna`).

## Qué había (verificado en código, no en las cartas)

1. `audit.py` escribía en `<paquete>/audit_logs/` sin ninguna variable de entorno para
   moverlo. En Railway ese filesystem es efímero: cada deploy tira el log.
2. `fpl_server.py` estampaba `provider=os.environ["DEFAULT_PROVIDER"]` (la variable del
   clasificador de presentación, `_try_init_classifier_from_env`) en las cuatro líneas de
   audit (`/ask`, `/session/{id}/ask` y los dos `quota_exceeded`). El orquestador corre con
   `FPL_ORCH_PROVIDER`/`FPL_ORCH_MODEL`; nadie leía eso al auditar. No existía campo `model`.
3. Tres tablas de precios: `audit.PROVIDER_PRICING_PER_1M` (por PROVEEDOR, gemini a
   $0.075/M input — desactualizada), `scripts/measure_tool_routing.PRICING_PER_1M_BY_MODEL` y
   `scripts/run_agentic_loop_experiment.DEFAULT_MODEL_PRICING_PER_1M` (por modelo, copiadas a
   mano, con un test que las mantenía iguales en las claves compartidas). El audit costeaba cada
   turno de prod a tarifa "gemini" de la tabla vieja; ninguna estimación de costo de prod era
   correcta.

## Qué hay ahora (PR de esta carta)

- `AUDIT_LOG_DIR` (absoluto, o relativo a `packages/fpl-grounded-assistant`), leído en el
  momento de escribir, no al importar. Sin la variable: el default de siempre, sin cambio.
- `OrchestratorResult.provider` (nuevo, `None` por defecto): la etiqueta con la que
  `ask_orchestrated` despachó a `call_orch_provider` (`provider` explícito, o `anthropic` en
  auto-detección), estampada una sola vez en el wrapper público y sólo si `llm_used`.
  `harness.ask_v2` proyecta `orchestrator_provider` / `orchestrator_model` en las dos ramas
  del orquestador (con herramienta y sin herramienta grounded — la segunda no llevaba modelo
  antes). El audit lee de ahí; en turnos sin LLM (`resource`, `prompt`, `router`,
  `quota_exceeded`, orquestador inalcanzable, sesión legada) `provider=None`, `model=None`,
  `usd_cost_estimate=0.0`.
- Una sola tabla por modelo: `fpl_grounded_assistant/model_pricing.py`. `audit.py` y los
  dos scripts la importan. Modelo fuera de la tabla → `usd_cost_estimate=None` + warning;
  nunca la tarifa de otro modelo. La convención del share cacheado (openai lo cuenta dentro
  del input; anthropic aparte) viaja con la tabla, así que el audit ya no cobra dos veces el
  cache de openai.
- `run_phase_p3_tests.py` actualizado a la API nueva. Nota: ese checker ya estaba roto en
  `main` por dos motivos ajenos (`football_data_contract` fuera de su `sys.path`, y
  `quota._store` que ya no existe); no está en CI. Lo dejé consistente con la API pero no lo
  reparé.

Lo que NO cambió: `fpl_server.py:175` sigue leyendo `DEFAULT_PROVIDER` para el clasificador
(uso legítimo de presentación). `tier_sync` sigue estampando `provider="system"` (no es un
turno; sin tokens → costo 0.0).

## Puerta de infra que queda para Leo (los constructores no pueden ejecutarla)

El código ya acepta el directorio; falta que en Railway ese directorio sobreviva al deploy.
Dos opciones, una basta:

**A. Volumen Railway (recomendada, sin código nuevo).**
1. Railway → servicio backend → *Volumes* → montar uno en, por ejemplo, `/data/audit`.
2. Variable `AUDIT_LOG_DIR=/data/audit` en el mismo servicio.
3. Redeploy. Verificación: `railway ssh -- ls -la $AUDIT_LOG_DIR` muestra un
   `<YYYY-MM-DD>.ndjson` del día; tras un **segundo** deploy (uno o más días después), el
   mismo `ls` sigue mostrando el archivo del día anterior. Eso es lo que prueba persistencia;
   un solo deploy no lo prueba.
4. Verificación de contenido, primera línea orquestada tras el deploy:
   `railway ssh -- tail -1 $AUDIT_LOG_DIR/$(date -u +%F).ndjson` debe llevar
   `"provider":"openai","model":"gpt-5.6-luna"` (o lo que diga `/healthz.orchestrator` en ese
   momento — comparar contra `/healthz`, no contra la variable) y `usd_cost_estimate` no nulo.

**B. Push diario a R2** con las credenciales `OWNED_STORE_R2_*` ya presentes. Requiere un job
(cron de Railway o GitHub Action con `railway run`) que suba `audit_logs/*.ndjson` al bucket.
Más piezas móviles; sólo si el volumen no aplica al plan.

Yo no puedo correr `railway ssh` ni tocar el dashboard: esta puerta queda abierta hasta que
Leo la cierre y pegue el `ls` de después del segundo deploy en la carta.

## Evidencia de este PR

- pytest `packages/fpl-grounded-assistant` (`--basetemp` fuera de `AppData\Local\Temp`):
  antes 2203 passed / 1 skipped → después 2221 passed / 1 skipped (+18 nuevos).
- Mutaciones, una por vez, sobre `tests/test_i104_i105_audit_dir_provider_model.py`
  (18 tests): M1 `/ask` vuelve a `DEFAULT_PROVIDER` → 6 mueren; M2 harness deja de proyectar
  provider/model → 5; M3 audit tarifa por defecto para modelo desconocido → 3; M4
  `resolve_log_dir` ignora el env → 10; M5 wrapper no estampa `provider` → 5; M6 reaparece
  una fila literal de precio en un script → 1.
- Los tests de turno orquestado corren el `ask_orchestrated` real con `call_orch_provider`
  falso en el cable (registra con qué `provider_name`/`model` lo llamaron) y
  `DEFAULT_PROVIDER=gemini` puesto como trampa; `provider`/`model` se leen de vuelta de la
  línea NDJSON escrita en el directorio que fijó `AUDIT_LOG_DIR`.
