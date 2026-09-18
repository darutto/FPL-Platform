# i98 — nombres reales, dato real: qué formas del store no llegaban a su jugador

**Fecha:** 2026-09-17 · **Fuente medida:** los 449 nombres distintos del store Understat
2025-26 (`fpl-tactical/data/tactical/seasons/2025-2026/understat_shots.parquet`, 9 524 tiros)
contra el bootstrap FPL en vivo, a través de `zonal_weakness_tool.resolve_store_player`
(el matcher de la tarjeta zonal: `RANK_EXACT` único, sin prefijo ni substring).
**Datos:** `field-notes/artifacts/i98-store-name-audit-2026-09-17.json`.
**Script:** `packages/fpl-grounded-assistant/scripts/measure_i98_store_name_resolution.py`.

## Causa (a): la entidad HTML en la ingesta

El store 2025-26 trae cuatro nombres con `&#039;` sin desescapar: `Matt O&#039;Riley`,
`Jake O&#039;Brien`, `Nico O&#039;Reilly`, `Luke O&#039;Nien`. Understat sirve los nombres
escapados y soccerdata los pasa tal cual. Ninguno de los cuatro resolvía.

**Arreglo en la causa:** `fpl_tactical/ingest.py::normalize_shots` aplica `html.unescape`
a `player` antes de escribir el parquet. Test con `Luke O&#039;Nien` → `Luke O'Nien`; mutación
(quitar el `unescape`) → muere. Cero apariciones previas de `html.unescape` en `fpl-tactical`.
El cron `tactical-store-refresh` (lunes 06:30 UTC) re-ingesta y corrige el store de prod en
el siguiente ciclo; el matcher NO se toca por esto (`Luke O&#039;Nien` sigue sin resolver, a
propósito — belt and braces).

Con el unescape aplicado en memoria: **296 → 300** nombres resueltos.

## Causa (b): formas del store que `RANK_EXACT` no cubre

De los 153 sin resolver antes del unescape, 44 tienen un candidato plausible en el
bootstrap de hoy (heurística: último token del nombre del store presente en el nombre
completo FPL + inicial coincidente). Revisados uno a uno: 4 son las entidades HTML (las
resuelve el unescape), 1 no es la misma persona (`Jacob Bruun Larsen` ≠ `Strand Larsen`,
descartado a mano) y **39 son la misma persona**. Categorías reales:

| forma del store | FPL `web_name` | por qué no era exacto |
|---|---|---|
| `Bruno Fernandes`, `Gabriel Jesus`, `Nico González`, `Pape Sarr`, `Jorge Cuenca` | `B.Fernandes`, `G.Jesus`, `N.Gonzalez`, `P.M.Sarr`, `J.Cuenca` | web_name con inicial |
| `Dominic Solanke`, `Ben Doak` | `Solanke` (2.º apellido `Solanke-Mitchell`), `Gannon-Doak` | el apellido FPL creció |
| `Ao Tanaka`, `Kaoru Mitoma`, `Wataru Endo` | `Tanaka`, `Mitoma`, `Endo` | FPL guarda apellido-nombre |
| `Rúben Dias`, `Bruno Guimarães`, `Florentino Luís`, `Yeremi Pino`, `Alysson Edward` | `Rúben`, `Bruno G.`, `Florentino`, `Yeremy`, `Alysson` | web_name = nombre de pila |
| `Ben White`, `Dan Ballard`, `Matthew Cash`, `Treymaurice Nyoni` | `White`, `Ballard`, `Cash`, `Nyoni` | forma larga/corta del nombre de pila |
| `Carlos Alcaraz`, `Garnacho`, `Dalot`, `Buendía`, `Carvalho`, `Lerma`, `Ugarte`, `Senesi`, `Zubimendi`, `Cunha`, `Merino`, `Caicedo`, `Neto`, `Muniz`, `Khusanov` | idem | `second_name` FPL lleva el apellido completo (`Alcaraz Durán`, `Garnacho Ferreyra`…) |

**Decisión:** entran en `KNOWN_NICKNAMES` (clave = `web_name` exacto, como toda la tabla)
sólo las formas que la medición confirma que fallaban **y** cuyo `web_name` es único en el
bootstrap tras normalizar. Auditoría de relajación (la lección de
[[feedback_matcher_relaxation_audit]]), con las 35 aplicadas:

- resueltos **300 → 335**;
- nombres que ya resolvían y cambiaron de destino: **0**;
- de los 35 nuevos, resueltos a un jugador distinto del previsto: **0**.

**Rechazados, y por qué** — la tabla no puede ganarlos sin mentir:
- `Joshua King` → `King`: **dos** `King` en el bootstrap (Josh King FUL, Tom King EVE); un alias
  por web_name empata y resuelve a nada (que es lo correcto). Es el «Josh King» de la carta:
  necesita una regla de nombre de pila corto/largo con desempate por club, no un alias — carta
  aparte si se quiere.
- `Joseph Gomez` / `Diego Gómez` → `Gomez`: dos `Gomez` tras normalizar.
- `Daniel Muñoz` → `Muñoz`: `Muñoz` y `Munoz` (Víctor) normalizan igual.
- `Oli McBurnie`: no está en el store 2025-26 ni en el bootstrap de hoy — nada medido falla.

Tests en `tests/test_zonal_weakness_tool.py::TestI98StoreNameForms` con registros con la forma
del bootstrap real: 5 formas resuelven a su `web_name`, la entidad escapada sigue sin
resolver, `Joshua King` con dos King queda `None`, y una forma NO tabulada
(`Bruno Borges`, `Dominic Mitchell`) sigue sin resolver — el matcher no se relajó.
Mutación (quitar los alias) → 4/8 mueren (las 4 que dependen de la tabla).

## Alcance no cubierto, dicho explícitamente

- El store de prod es 2026-27 (no está en disco local); la medición usa 2025-26 porque las
  cadenas de Understat para un mismo jugador no cambian entre temporadas. Los jugadores que
  salieron de la liga (McBurnie) no importan; los que entraron en 2026-27 con forma nueva
  no están medidos — el script se puede reejecutar sobre el parquet de prod.
- 114 nombres siguen sin resolver: jugadores que ya no están en la Premier (la mayoría) y
  formas sin candidato claro. No se inventa nada para ellos: `club_source=store`.

## Texto de carta propuesto (i98 → done)

Medido 2026-09-17 (449 nombres del store vs bootstrap vivo, `RANK_EXACT`): 296 resolvían.
(a) `html.unescape` en la ingesta de `fpl-tactical` (4 nombres `O&#039;…`, test + mutación);
el cron del lunes corrige el store de prod. (b) 35 formas del store añadidas a
`KNOWN_NICKNAMES` con auditoría de relajación: 300 → 335 resueltos, 0 cambios de destino,
0 destinos imprevistos. `Josh King` NO entra: hay dos `King` y un alias por web_name
empataría — necesita regla de nombre corto con desempate por club (carta aparte).
`Oli McBurnie` ya no está en la liga.
