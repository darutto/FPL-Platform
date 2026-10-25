# Reportes de partido y de equipo FPL: plan de integración refinado

**Fecha:** 2026-10-25. **Autor:** el cerebro (revisor). **Base:** `FOOTBALL_MATCH_AND_SQUAD_REPORTS_VISION.md` (Leo, a partir de una discusión con ChatGPT; **solo local**, en la raíz del checkout compartido, no está en el repo público) cotejado con el estado real del repositorio y de producción.
**Para:** Leo, builders (Claude y Codex) y revisores. **Estado:** plan propuesto; ninguna etapa está aprobada para construir salvo las marcadas "en curso".

## 1. Veredicto sobre la visión

La tesis es correcta y encaja con lo que ya decidimos: **explicar, no predecir** (la conclusión del trial), con hechos trazables y sin inventar causas ni "puntos esperados". Se acepta tal cual: las restricciones de la sección 8 (identidad, no confundir cero con ausente, provisional ≠ confirmado, nada de heatmaps ni causalidad), y la regla de que el renderer/LLM solo expresa hechos con evidencia.

Se refina en seis puntos.

1. **El reporte de plantilla FPL no necesita Sportmonks para empezar.** La API de FPL entrega los picks de cualquier jornada ya cerrada de cualquier equipo (`entry/{id}/event/{gw}/picks`, más los puntos en directo y el historial). La visión dice que hoy solo hay picks de la GW actual: eso es de la **ruta de la UI** (`fpl-squad`), no del proveedor. Un reporte **retrospectivo** de cualquier GW pasada se puede construir solo con FPL. Sportmonks añade la capa táctica (casillas, quién sustituye a quién) encima. Esto cambia el orden: el primer entregable no espera a la ingesta.
2. **"Lo que sabíamos antes" requiere captura en el momento.** Los snapshots pre-deadline no se pueden reconstruir después. Hay que empezar a capturarlos cuanto antes (barato: un paso del job del deadline), aunque el reporte que los consuma llegue más tarde. Cada semana sin capturar es un historial que no existirá.
3. **El ledger de hipótesis es la idea diferencial, pero no el MVP.** Empezar con un registro de **eventos observados y dos tipos de hipótesis** (cambio de casilla; compañero fuera del once), append-only, en R2 privado. Sin motor genérico de hipótesis.
4. **Persistencia:** Railway no tiene volumen (los logs de auditoría son efímeros) y no hay base de datos por decisión. Los hechos por partido y el ledger viven en **R2 privado, append-only**, escritos por un job de GitHub Actions, como la ingesta licenciada. Los snapshots por usuario son datos personales (aunque los picks sean públicos): **MVP solo con el equipo de Leo y con consentimiento explícito para otros**; ninguna lista de usuarios en logs públicos.
5. **Stats individuales (toques, pases, pases clave, pases atrás, últimos tercio):** el inventario dice que están en Starter, pero Sportmonks no lo confirmó por escrito (pregunta 12) y la ingesta 3b no las descarga. Se confirma con una lectura mínima en la primera prueba real y se añade en un PR aparte (3c). No hay pases progresivos como campo.
6. **Valor de marketing:** el reporte de partido (Slice 1) es lo más compartible y verificable; el "registro de aciertos" (el ledger evaluado de forma pública, con fallos incluidos) es la mejor palanca de credibilidad a medio plazo. La frase citable segura es "empezó en otra casilla", nunca "se movió en el partido".

## 2. Matriz de estado real (auditada el 2026-10-25)

| Capacidad | Estado | Nota |
|---|---|---|
| FPL: puntos, minutos, fixtures, históricos | **operativo** | 7 temporadas en `fpl-historical` |
| Picks de cualquier GW cerrada, por API de FPL | **disponible, no usado por reportes** | la UI solo usa la GW actual |
| Understat (tiros por zona) | **operativo** (tarjeta zonal) | no es xG por jugador por partido |
| Sportmonks: ingesta licenciada (B3) | **parcial** | piezas en main: almacén, derivación, crosswalk, familia LICENSED_V1, rutas (#503–#507); **falta el job (3b)**, que construye Codex |
| Datos de Sportmonks en producción | **no hay** | sin token en GitHub, flujo desactivado; `live_trial_local` rechazado |
| B4 (herramienta "cambios de posición / quién sustituye a quién") | **no existe** | primera función visible prevista |
| M1/M2/M3 | descriptivos; no superan reglas simples | no publicar como producto |
| M4/M5 | esqueletos no operativos | no afirmar |
| Stats individuales y de equipo | **solo trial** | sin ingesta; entitlement Starter sin confirmar por escrito |
| Heatmaps / XY por jugador | **no existe** | no dibujar |
| Report composer, snapshots pre-deadline, ledger | **no existe** | este plan |
| Puntos FPL esperados | **no existe** | fuera de alcance |
| Resolución de nombres | **bug conocido** | "João Pedro" se resolvió a Costinha (BHA) por subcadena; en FPL actual Rogers y João Pedro son del Chelsea. Unir siempre por id, club y fecha |

## 3. Orden de construcción (PRs acotados)

| # | Etapa | Depende de | Quién | Valor |
|---|---|---|---|---|
| R0 | **Bug de identidad** (subcadena en resolución de jugadores) | nada | builder Claude/Codex | evita respuestas erróneas hoy |
| R1 | **Reporte retrospectivo de una jornada FPL** (picks reales de esa GW, once efectivo, capitán, banca, puntos oficiales reconciliados; 2–5 historias con evidencia; sin Sportmonks) | nada | Codex o Claude | primer reporte real; retención |
| R2 | **Ingesta 3b** (job licenciado, desactivado tras variable) | token en GitHub, variable `LICENSED_INGEST_ENABLED` | Codex (en curso) | desbloquea todo lo táctico |
| R2b | **Prueba real ~70 llamadas, sin publicar**; confirmar entitlement de stats con 1 lectura | R2 mergeado, token | cerebro | decide R3/R4 |
| R3 | **B4: cambios de posición y quién sustituye a quién** (herramienta + tarjeta; ES/EN desde el inicio). **Decisión de Leo (2026-10-25): B4 va primero y lo está construyendo Copilot; se deja terminar, ningún otro builder lo toca.** | R2 + primer publish | Copilot | la pregunta de Leo; contenido de tuits |
| R4 | **Reporte de partido factual** (resultado, XI, casillas iniciales, minutos, hechos FPL; sin interpretación espacial) | R2, R0 | builder | compartible, verificable |
| R5 | **Captura pre-deadline + ledger mínimo** (R2 privado, append-only; dos tipos de hipótesis; solo el equipo de Leo al inicio) | R2 (job del deadline) | builder | empezar a acumular historia cuanto antes |
| R6 | **Stats individuales (3c)** y destacados por categorías | R2b confirma entitlement | builder | toques/pases/tiros por jugador |
| R7 | **Evaluación A/B** FPL-only contra FPL+Sportmonks (arnés del PR #470) | R1, R3/R4 | cerebro | decide si seguir pagando el plan |
| R8 | Registro público de aciertos (ledger evaluado, con fallos) | R5 con ≥2 GW | decisión de Leo | credibilidad |

**Nota de capacidad:** Claude está cerca del límite de uso del fin de semana. R1, R2 y R0 son buenos encargos para Codex; los demás esperan al reinicio del límite.

## 4. Reglas que aplican a todas las etapas

- **Temporalidad:** guardar `fpl_deadline`, `fixture_kickoff`, `observed_at`, `report_as_of`. Un dato posterior al deadline nunca respalda "lo sabíamos antes". Los reportes retrospectivos se llaman retrospectivos.
- **Provisional ≠ confirmado; casilla inicial ≠ movimiento en el partido; ausente ≠ cero** salvo semántica validada por campo.
- **Identidad por id canónico, club a la fecha del partido.** Nada de subcadenas.
- **Licencia:** nada crudo en git, en logs ni detrás de un endpoint; R2 privado; los datos de Sportmonks de producción llevan procedencia `licensed_starter`.
- **Bilingüe desde el principio:** claves de catálogo ES/EN, nombres de chips en inglés, lenguaje de oportunidad, sin "debilidad" (ver [glosario](i18n-glossary.md)).
- **El LLM no calcula:** el compositor produce hechos y evidencia; el modelo solo redacta con ellos, y cada cifra debe estar en la evidencia.
- **Honestidad de resultados:** si falta cobertura, la sección se degrada de forma visible; nunca se rellena.

## 5. Decisiones de Leo (2026-10-25)

1. **Reporte de plantilla:** para las pruebas, **solo el equipo de Leo**. Otros usuarios solo con consentimiento explícito, más adelante.
2. **Orden:** **B4 primero**, en curso con Copilot; se deja terminar. R1 (reporte retrospectivo) queda detrás, sin pisar a B4.
3. **El documento de visión se queda solo local** (no se publica en el repositorio).
4. Pendiente: ¿publicar el registro de aciertos (R8) con sus fallos? Y preguntar a Sportmonks por escrito si Starter incluye las estadísticas individuales.
