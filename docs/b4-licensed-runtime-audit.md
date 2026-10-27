# B4, PR 1: auditoría de la lectura en producción de `football-licensed/`

**Fecha:** 2026-10-26. **Alcance:** qué llega hoy a Railway de la familia licenciada, qué faltaba para leerla en runtime y qué cablea este PR (solo lectura, apagado por defecto). Lo que no se puede ver desde el repositorio (variables de Railway, contenido del bucket) está marcado como **no verificado**.

## 1. Lo que sí está en el repositorio (verificado leyendo el código)

| Pieza | Estado |
|---|---|
| Publicación | `licensed-ingestion.yml` publica la familia `LICENSED_V1` al prefijo privado `football-licensed/` con puntero `_football_licensed_latest.json`. Mapea `OWNED_STORE_R2_*` a `FPL_FOOTBALL_REMOTE_*` y fuerza el prefijo `football-licensed`. El cron queda apagado salvo `LICENSED_INGEST_ENABLED=true`. |
| Procedencia | El almacén se sella `licensed_starter` (normalizador `licensed-starter-v1`, fuente `licensed-sportmonks-starter`). `sync_build` rechaza `live_trial_local` para toda familia; el validador licenciado solo acepta `licensed_starter`. |
| Dependencias de runtime | El `Dockerfile` ya copia `packages/football-intelligence` (donde vive el almacén licenciado) y `requirements.txt` trae `pandas`, `pyarrow` y `boto3`. `licensed-ingestion` **no** hace falta en el contenedor. |
| Tablas | `lineup_snapshots`, `lineup_slots` (casilla, posición detallada, lado), `sidelined`, `squad_membership`, `cup_snapshots`, `cup_records`, `crosswalk`; todas con ids FPL salvo `crosswalk`, que guarda ids del proveedor. |

## 2. Qué llegaba a Railway antes de este PR: nada

- El único sincronizador del servidor era `startup_sync()` (`fpl_server.py`, arranque), que llama `sync_build(...)` con la familia **canónica** (`CANONICAL_V1`). Esa familia no puede tocar el prefijo licenciado: `football-licensed` es un segmento reservado (`keys.RESERVED_PREFIX_SEGMENTS`), la canónica lo rechaza y cada familia tiene su propio puntero.
- Resultado: aunque el bucket tenga la primera build licenciada, el backend no la descargaba ni la leía. No había lector licenciado.

## 3. Qué añade este PR (solo lectura, apagado)

- `football_intelligence/distribution/licensed_runtime.py`:
  - `licensed_startup_sync()`: sincronización acotada y que nunca lanza, con `LICENSED_V1` y el prefijo fijo `football-licensed`. **Apagada** salvo `FPL_FOOTBALL_LICENSED_SYNC_ENABLED` en `1/true/yes`; las credenciales solas no la encienden. Devuelve solo estado y código de motivo (`disabled/sync_not_enabled`, `disabled/not_configured`, `ready/synchronized`, `degraded/…` con la última build buena, `unavailable/…`).
  - `LicensedRuntimeHandle`: valida la build en cada lectura (manifiesto exacto, hashes, filas), re-ejecuta la negativa de trial y exige `licensed_starter`. Sirve las tablas derivadas como DataFrames; **`crosswalk` no es legible** (contiene ids del proveedor) y un nombre de tabla fuera de la lista se rechaza.
- `fpl_server.py`: llamada tolerante a fallos tras la sincronización canónica; deja el estado en `app.state.football_licensed_status` y escribe **una línea** con estado y motivo. No se amplía `/ready` (su contrato está bajo el gate de drift).
- Tests (`test_licensed_runtime.py`, almacén en memoria y datos sintéticos, sin red): apagada por defecto aunque haya credenciales; sin configuración no es error; sincroniza y lee; `crosswalk` no se sirve; una build marcada de trial se rechaza al leer; un refresco fallido conserva la última buena como `degraded`; ningún contenido en el estado; el prefijo canónico no se puede usar con esta familia.

## 4. Lo que falta para que funcione en producción (config de Leo, no verificado desde aquí)

1. **Variables en Railway** (mismo bucket privado y credenciales que `OWNED_STORE_R2_*`): `FPL_FOOTBALL_REMOTE_ENDPOINT`, `FPL_FOOTBALL_REMOTE_BUCKET`, `FPL_FOOTBALL_REMOTE_ACCESS_KEY_ID`, `FPL_FOOTBALL_REMOTE_SECRET_ACCESS_KEY`, y **`FPL_FOOTBALL_LICENSED_SYNC_ENABLED=true`**. El comentario de `railway.toml` solo lista `OWNED_STORE_R2_*`; no consta que las `FPL_FOOTBALL_REMOTE_*` existan en el panel de Railway.
2. **Efecto lateral a conocer:** esas mismas `FPL_FOOTBALL_REMOTE_*` activan también la sincronización **canónica** existente, que buscará un puntero en el prefijo `football` (por defecto). Es tolerante a fallos (si no hay build, queda `unavailable` o `degraded` sin afectar al arranque), pero hay que saberlo antes de ponerlas.
3. **Disco efímero:** Railway no tiene volumen; la caché (`data/football-licensed-runtime`, o `FPL_FOOTBALL_LICENSED_CACHE_ROOT`) se descarga en cada arranque. La build crece durante toda la temporada (se conservan todas las instantáneas); el límite por defecto es 128 MiB por parquet y 512 MiB por build.
4. **Cómo verlo:** busca en los logs de Railway la línea `football licensed sync: state=… reason=…` tras un arranque.
5. **Confirmar con `inspect-r2-stores.yml` o una lectura de Leo** que el puntero `football-licensed/_football_licensed_latest.json` existe y que el bucket no tiene acceso público. No se puede comprobar desde el código.

## 5. Flags

| Flag | Dónde | Estado | Efecto |
|---|---|---|---|
| `FPL_FOOTBALL_LICENSED_SYNC_ENABLED` | Railway | apagado (no existe) | descarga la familia licenciada al arrancar |
| `FOOTBALL_INTELLIGENCE_ENABLED` | Railway | apagado | registra y despacha las herramientas FI; **sigue apagado** hasta que el cerebro lo apruebe |
| `LICENSED_INGEST_ENABLED` | GitHub (variable) | según cerebro | el cron del job de ingesta |

## 6. Observaciones fuera de B4 (no se tocan aquí)

- El runtime FI canónico (`football_intelligence_runtime._load_runtime`) lee `FPL_FOOTBALL_ROOT` (por defecto `data/football`) mientras `startup_sync` escribe en `FPL_FOOTBALL_CACHE_ROOT` (por defecto `data/football-runtime`), y las builds v2 (`_football_v2_latest.json`, `features/`) que exige no las sincroniza `startup_sync`. Mientras las herramientas FI estén apagadas no importa, pero encenderlas tal cual no encontraría datos. La herramienta de B4 lee el almacén licenciado directamente y no depende de esto.
- Resolución de nombres ("João Pedro" → Costinha por subcadena): ver el PR 2; la herramienta de B4 une por id canónico, club y fecha y no usa subcadenas.
