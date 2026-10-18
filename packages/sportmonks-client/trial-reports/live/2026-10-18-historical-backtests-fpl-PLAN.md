# Backtests históricos con datos solo de FPL: plan preinscrito (18 oct 2026)

Este fichero se escribe y se sube **antes de mirar ningún resultado**. Solo se han mirado campos y estructura de las tablas (qué columnas existen en cada temporada, cuántas filas, si el equipo de cada fila se puede reconstruir). Ningún resultado de predicción, tasa de titularidad ni diferencia entre métodos se ha calculado. Cualquier desviación respecto a este plan se anota en el informe final como desviación.

Encargo: revisor fpl-platform-b7, aprobado por Leo el 2026-10-18. Solo análisis, sin llamadas a Sportmonks, sin LLM (por tanto sin fuga de conocimiento del modelo).

## Datos

Almacén propio `packages/fpl-historical/data/historical/seasons/<temporada>/parquet_merged/` (`player_gw_stats`, `fixtures`, `players`, `events`), temporadas 2019-20 a 2025-26.

Qué hay por temporada (comprobado, sin mirar resultados):
- `starts` solo existe en **2025-26**. En las otras seis hay que inferir la titularidad.
- `expected_goals`, `expected_assists` con datos solo desde **2022-23**. En 2019-20 a 2021-22 está vacío.
- Las filas antiguas (vaastav) no traen fixture, rival, hora ni propiedad por jornada. Se reconstruyen: el equipo del jugador sale de `players.team_id` y la fila se asigna al fixture de ese equipo en esa jornada (`fixtures`, que sí trae hora). En jornadas dobles las filas se asignan por orden de aparición, comprobando `was_home`. Una fila se descarta si ese equipo no tiene fixture con el mismo lado local o visitante (fichajes a mitad de temporada); se informa la tasa de descarte. En la comprobación de estructura, el número de filas coincide con el de fixtures del equipo en más del 99,5 % de los casos.
- `selected_by_percent`, `now_cost` de `players` son agregados de fin de temporada: **nunca se usan**. La propiedad por jornada (`selected`) solo existe en 2025-26 y no se guarda el total de managers; por eso no se usa propiedad. El precio por jornada sí existe en todas (`value`).
- 2019-20 tiene jornadas 39 a 47 (reanudación tras la COVID, 5 cambios, calendario comprimido).

**Titularidad inferida** (temporadas sin `starts`): titular = `minutes >= 60`. Es imperfecta. Se mide su error en 2025-26, la única temporada con `starts` real, y se informa (exactitud, falsos titulares, falsos suplentes). Sensibilidad en 2025-26: umbrales 46 y 60. **Objetivo "titular" de la evaluación:** `starts` real en 2025-26 y `minutes >= 60` en las demás; en 2025-26 se informa también con el proxy para medir cuánto cambia.

## Puntos de corte

- Universo: todos los pares (temporada, jornada) con jornada >= 4 en las siete temporadas.
- **Semilla fija 20261018.** Se sortean **200 puntos sin reemplazo** de ese universo. Los resultados primarios usan esos 200. Sensibilidad: todos los puntos elegibles.
- Un punto de corte es una jornada g. La historia es **estrictamente** lo anterior a g (jornadas < g). El resultado es lo que pasa en la jornada g. En jornadas dobles, cada fixture es una fila y todos usan la misma historia anterior a g.
- Lista de jugadores fijada solo con datos anteriores al corte: jugadores con al menos 1 titularidad (inferida o real) en los hasta 6 partidos previos de su equipo, que tienen fixture de su equipo en la jornada g.

## T1. Titularidad y minutos

Predictores (sin ajustar ningún coeficiente):
1. **Regla simple**: titularidades de los últimos 3 partidos entre 3; minutos = media de los últimos 3.
2. **M1 con historial FPL**: el módulo `expected_minutes` tal cual (coeficientes a mano de `expected-minutes-hand-tuned-v1`), alimentado con las titularidades y minutos de los últimos 6 partidos del equipo (pesos 1 a 6), partidos con minutos > 0 y no titular = cameo, y congestión a 21 días con los partidos de liga de `fixtures` (21 días atrás completados y 21 adelante programados). Sin disponibilidad.

Métricas: Brier de titular y MAE de minutos, por temporada y agrupado. Referencia: tasa base y media.

**IC:** bootstrap por conglomerados, el conglomerado es el partido de equipo (temporada, fixture, equipo); 2.000 remuestreos. Diferencia emparejada fila a fila.

**Qué cuenta como victoria** (preinscrito):
- M1 gana en titularidad si la diferencia agrupada de Brier (M1 menos simple) es negativa, el IC al 95 % excluye 0 y es negativa en al menos 5 de 7 temporadas.
- La regla simple gana en minutos si la diferencia agrupada de MAE (M1 menos simple) es positiva, el IC al 95 % excluye 0 y es positiva en al menos 5 de 7 temporadas.
- "El resultado de F se sostiene" = se cumplen las dos.
Se informa también por temporada y por rango de jornada (4 a 10, 11 a 25, 26 en adelante).

## T2. Congestión, solo liga

- Titulares habituales fijados antes del partido: al menos el 75 % de titularidades en sus hasta 4 partidos previos de liga (mínimo 3 previos).
- Exposición: días de descanso desde el partido de liga anterior del equipo. Corto = 3 o menos días completos (suelo de horas entre salidas / 24); largo = 6 o más. Se descartan 4 y 5.
- Resultado: el habitual vuelve a ser titular.
- Cada equipo contra sí mismo: por equipo-temporada con ambos grupos, diferencia de tasa de titularidad (corto menos largo). Resumen: media ponderada por n corto. IC: bootstrap por conglomerados de equipo-temporada.
- Umbral práctico preinscrito: se llama "caída" si la media es menor que cero con IC al 95 % que excluye 0 y es al menos de 5 puntos porcentuales; se llama "sin efecto relevante" si el IC cae entero dentro de ±3 puntos.
- Agrupado excluye las jornadas 39 a 47 de 2019-20 (COVID); sensibilidad que las incluye.
- **Limitación declarada:** FPL solo conoce los partidos de liga. No ve ni Europa ni copas: la versión con Europa espera datos de Sportmonks de temporadas pasadas.

## T3. Ausencia y reemplazo, versión solo FPL

- Un titular habitual (misma definición que T2) deja de ser titular en el partido m (el primero sin titularidad tras su racha).
- Candidatos a reemplazo: jugadores del mismo equipo que son titulares en m con como mucho 1 titularidad en los 3 partidos previos a m ("la titularidad acaba de subir").
- **Regla solo FPL:** además, barato: precio por jornada `value` <= 55 (5,5 millones). Es el proxy de baja propiedad porque la propiedad histórica por jornada no existe.
- Resultado: `mantiene_k` = titular en cada uno de los siguientes k partidos (k = 1, 2, 3). Se exige que existan esos partidos.
- Se informa la tasa base por temporada con n, para la regla barata y para todos los candidatos, más el subconjunto en que el habitual sigue sin ser titular en m+1.
- Es la línea base contra la que se comparará la versión con huecos de Sportmonks.

## Fuga

Sin agregados de fin de temporada, sin precios finales, sin propiedad posterior. El equipo del jugador sale de la tabla `players` (equipo de fin de temporada); no es un resultado, pero se descartan las filas con lado incoherente y se informa la tasa. Determinista, sin LLM.

## Qué se entrega

Informe en español `2026-10-18-historical-backtests-fpl.md`, scripts en `packages/football-intelligence/scripts/historical_backtests/`. Borrador de PR, sin mergear.
