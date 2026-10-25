# Conclusiones del trial de Sportmonks (FI-9) y qué compra el contrato de €29

**Fecha:** 2026-10-24 (el trial vence el 2026-10-25 03:09 UTC). **Autor:** el cerebro (revisor), a petición de Leo.
**Para quién:** cualquier agente que trabaje en football-intelligence, la ingesta licenciada o decisiones de producto/proveedor, y Leo.
**Estado de la decisión:** Leo decidió el 2026-10-21 **GO solo con Starter (€29/mes + IVA, mensual)**. Sin Euro Club Tournaments. Los complementos del trial ya se retiraron.
Sin nombres de jugadores salvo ejemplos públicos ya citados en los informes enlazados; sin ids de proveedor ni cargas crudas.

## 1. En una frase

**Sportmonks Starter vale lo que cuesta por el DATO y la EXPLICACIÓN** (qué posición ocupa cada jugador, cuándo cambia, quién está de baja, cómo se ve el calendario), **no por la PREDICCIÓN**: los módulos que construimos (M1/M2) no superaron claramente a reglas simples hechas con ese mismo dato, y la alineación confirmada llega tarde para decidir en FPL.

## 2. Qué incluye hoy el contrato (Starter, solo Premier League)

Fuente: respuesta escrita de soporte del 2026-10-21 ([checklist](../../TRIAL_LICENSING_CHECKLIST.md), [borrador de decisión](decision-draft.md)).

| Incluido sin complemento | Detalle |
|---|---|
| Alineaciones | once inicial con formación, casilla de la rejilla (`formation_field`) y posición detallada |
| Alineaciones provisionales y marcador `lineup_confirmed` | llegan antes del saque; distinguibles de las confirmadas |
| Bajas | lesiones y sanciones (`sidelined`) |
| Plantillas (squads) | por club |
| Calendario y resultados | Premier League |
| Historia | últimas 3 temporadas (más antiguas, complemento Historical Data) |
| Límite | 2.000 peticiones por hora y entidad (los 2.500 del trial venían del paquete Euro) |
| Copas inglesas (FA Cup, Carabao) | best-effort, sin garantía; Carabao tuvo 22/22 onces en el trial; FA Cup no se pudo ver hasta enero |

**No incluido** (se probó en el trial y se apagó): Match Facts, Pressure Index & xG, Predictions, Odds, Euro Club Tournaments. **Licencia (todo SÍ):** guardar, conservar tras cancelar, combinar con FPL, derivar puntuaciones y mostrar derivados a suscriptores; **prohibido** revender o redistribuir el feed crudo o dejar que se reconstruya. Los datos leídos en el trial se pueden conservar (confirmado por escrito el 2026-10-23).

## 3. Lo que nos da hoy, con números

- **Identidad:** 413/425 = **97,2 %** de los jugadores FPL con minutos emparejados automáticamente en 2026-27 (techo ≈99,5 % tras 9 confirmaciones manuales de Leo). En temporadas pasadas: 2025-26 llega a 97,2 % tras recaptura con nombre y fecha de nacimiento; 2024-25 solo 70,5 % (peor calidad).
- **Posición real por partido:** formación + casilla + posición detallada para el 100 % de los titulares observados (198/198 en la validación; lados validados por Leo en Arsenal, Liverpool y City). La "posición" es una función exacta de formación, casilla y lugar del partido: es un hecho del once anunciado, **no un mapa de calor ni una posición media medida**.
- **Hallazgo de producto más valioso (FPL):** defensas de FPL que juegan de carrilero o más adelantados (12 estables de 131 en GW1–7: De Cuyper, Bogle, N.Williams, Muñoz, Mitchell, Khalaili, etc.). FPL los etiqueta como defensas; el dato los separa. Su xGI/90 mediana fue 0,21 contra 0,07 del resto.
- **Cambios de rol:** 9 de 127 jugadores cambiaron de rol/banda en la ventana medida; 5 individuales. Los 9 tienen delta de xGI/90 positivo (asociación, no efecto).
- **Quién gana los minutos:** 23 de 33 salidas de titulares tienen sustituto directo en el mismo hueco, casi todos con <3 % de propiedad (señal de diferenciales).
- **Calendario (M3):** cuadra con el calendario real en 120/120 equipos-jornada (GW2–7).
- **Alineación confirmada (criterio b):** en los 8 partidos observables de GW7 el once confirmado **no estaba 72 min antes del saque y ya estaba entre 15 y 59 min antes** (la llegada cae en la última hora y media). **Siempre después del deadline de FPL.** El marcador `lineup_confirmed` pasa de falso a cierto justo entonces: la señal fiable existe. La provisional difiere de la confirmada en 1–6 jugadores (media 2,9).
- **Pre-carga europea (87 llamadas, local, congelada):** 825 partidos europeos 2026-27, 537/537 jugados con once completo; para clubes de la PL: 25 jugados 2026-27 (UCL 15, UEL 6, UECL 3, Supercopa 1), 116 en 2025-26, 90 en 2024-25 (calidad de rejilla 116/116 en 2025-26; 78/90 en 2024-25). Calendarios completos hasta el fin de la fase de liga (UCL 2027-01-27, UEL 2027-01-28, UECL 2026-12-17). Las eliminatorias 2026-27 no están sorteadas. **Congelado:** hace falta una política "congelado pero final" antes de usarlo en producción (`public_calendar` marca "stale" tras 8 días).
- **Cosecha final de presión y xG (local):** 830 partidos jugados de 3 temporadas de la PL + **75 de 2026-27** (cosecha del 2026-10-24 22:00 UTC, 18 llamadas) con presión por minuto (≈2 filas/minuto) y xG de equipo; xG por jugador solo para quien disparó (1.102 filas de alineación con xG en 2026-27). Solo en `trial-output/` (git-ignorado). Uso interno y derivado.

## 4. Lo muy positivo

1. **El dato es bueno y estable:** cobertura casi total de posición/rejilla en PL, ids de jugador estables, 97 % de identidad automática sin aflojar el emparejador.
2. **Licencia clara y amplia** (criterio d): se puede derivar y mostrar a suscriptores. Es el riesgo que más temíamos y salió bien.
3. **Es barato y predecible:** €29/mes fijos, 2.000/h, sin descuentos ni paquetes ocultos; nuestras ejecuciones planeadas son ~250 llamadas (≈62/día en producción, ver [PROD_INGESTION](../../../football-intelligence/PROD_INGESTION.md)).
4. **Explica lo que FPL no puede:** qué papel juega alguien, desde cuándo, quién lo reemplaza. Alimenta tarjetas visibles ("cambios de posición", "quién sustituye a quién").
5. **El proceso funcionó:** rúbrica preregistrada, informes honestos que reportan baselines y límites, y un cliente reescrito contra la API real (8 de 15 "familias" eran includes) con tests.
6. **Sostenibilidad:** las condiciones permiten conservar lo ya descargado aunque cancelemos.

## 5. Lo negativo (contras)

1. **Los módulos predictivos no ganan a bases simples.** M2 (rol): 91,0 % frente a 92,9 % de "repite su último partido" (GW2–7); M1 (titularidad): Brier 0,149 frente a 0,156 de la forma bruta y 0,203 de la tasa base, con cobertura 53 %; M1 pierde en minutos frente a la regla simple de FPL (MAE 26,9 vs 23,2 en 7 temporadas de FPL). Lo mismo en backtests históricos de Sportmonks: H1 (detector de cambio de rol), H2 (relevo por hueco) y H3 (rotación tras Europa) no superan los criterios preinscritos; H4 solo mejora la titularidad, no los minutos.
2. **La alineación confirmada llega tarde** (última hora y media; siempre tras el deadline de FPL). Sirve para explicar y para avisos de partido, no para decisiones previas al deadline. La provisional sí llega antes (≈3 jugadores de error medio).
3. **Starter es solo Premier League.** Europa exige Euro Club Tournaments (+≈€29); copas inglesas, best-effort.
4. **Estadísticas por jugador y partido: sin confirmar para Starter.** La tabla de estadísticas por jugador de la captura salió con 0 filas (usamos xG/xA/amenaza de FPL), pero una lectura aparte con el token del trial (`lineups.details`, 60 partidos) sí trajo valoración (97 % de las apariciones), pases clave, entradas, intercepciones, duelos, etc. **No sabemos si eso entra en Starter** (la pregunta 12 de licencia/plan quedó sin respuesta): comprobarlo en el primer día de producción antes de diseñar nada con ello. Ojo: el proveedor solo envía las estadísticas distintas de cero (ausente = cero, no "falta").
5. **Los complementos probados tenían límites que habrían decepcionado:** Match Facts solo en inglés, ~20–25 % de las filas con frase y solo ≈2 días antes del partido (GW8 a 6–8 días: 0 filas); Predictions parcheadas (sin Champions) y con baja fiabilidad justo donde queríamos apoyarnos; Pressure/xG sin xG por disparo ni coordenadas y sin xA por jugador (solo xG, xGOT y rendimiento de tiro).
6. **La "posición" es nominal**, no medida: no distingue cuánto sube un lateral; no hay mapas de calor.
7. **Ruido de identidad en históricos:** 2024-25 queda en 70,5 % (se necesita recaptura con `lineups.player`, ≈32 llamadas, con visto bueno de Leo).
8. **Latencia de bajas:** la medición del criterio (c) tuvo resolución de 8 h y huecos del vigilante; no consta un cierre numérico limpio en el borrador. No asumir <48 h sin volver a medir en producción.
9. **Coste interno:** el trial consumió mucho tiempo de sesión (vigilantes, reinicios del PC, topes de uso); producción exige un job programado en GitHub Actions con logs públicos (solo agregados).

## 6. Lo que nos faltó (huecos de la evaluación)

- **Valor para el usuario no medido:** la columna "valor" de los informes la rellena Leo y nunca se cerró; el A/B de profundidad de respuesta (PR #470, sin mergear) tiene el brazo con datos de Sportmonks bloqueado por diseño. **No hay evidencia medida de que el dato mejore las respuestas del asistente**, solo de que el dato es bueno y explicativo.
- **Una sola ventana corta en vivo:** ≈GW1–GW8, con parón de selecciones; la FA Cup y las eliminatorias europeas no se vieron.
- **Preguntas sin respuesta del proveedor:** cobertura completa del trial (Q1), entrenadores, sustituciones y estadísticas de partido (Q12).
- **Aplazamientos invisibles:** el calendario puede no reflejar aplazamientos (R6).
- **Sin comparación directa con otro proveedor** (esto es lo que pide la sección 8).
- **Latencia de bajas** y **estabilidad de ids a largo plazo** solo medidas en semanas.

## 7. Lo que desearíamos

- Alineación confirmada **antes** del deadline de FPL (hoy es imposible: el club la anuncia ~1 h antes del saque).
- Posición **medida** (media de acciones/posición) y no solo nominal; xA por jugador; xG por disparo con coordenadas.
- Bajas con marca de tiempo de publicación para medir latencia real.
- Cobertura europea y de copas con garantía a precio razonable (Euro Club Tournaments ≈ doblaría el coste).
- Una base de usuarios que pague, para que el gasto tenga retorno medible (hoy 0 suscriptores nuevos: ver memoria del proyecto).

## 8. ¿Deberíamos explorar otros proveedores?

**Recomendación: no hacerlo ahora como proyecto; sí una prueba barata y acotada, más una reevaluación en 2027 con disparadores claros.** Razones: ya existe el cliente, el emparejador de identidad y el almacén para Sportmonks; la licencia es buena; el coste es bajo; y el hallazgo principal (la predicción no gana) es del dato, no del proveedor: otro proveedor con el mismo tipo de dato probablemente da el mismo resultado.

Comparación orientativa (**precios y coberturas de páginas de terceros y de la competencia: verificar en cada proveedor antes de decidir**):

| Proveedor | Qué aporta | Coste orientativo | Para nosotros |
|---|---|---|---|
| **Sportmonks Starter (actual)** | rejilla, posiciones, once provisional/confirmado, bajas, plantillas, calendario PL, 3 temporadas | €29/mes | Base actual |
| **API-Football (api-sports)** | alineaciones, eventos, estadísticas, lesiones, predicciones y cuotas en ligas top; en su documentación no encontré rejilla/`formation_field` explícita | plan gratis (≈100 llamadas/día) y ≈$19/mes (Pro), según comparativas de terceros | **Candidato a prueba barata:** comparar latencia de once y de bajas durante una jornada sin gasto |
| **Opta / Stats Perform** | referencia de la industria, eventos y posiciones | a cotización; ≈€250+/mes según la comparativa de Sportmonks (sesgada) | Solo si hubiera ingresos que lo justifiquen |
| **StatsBomb / Wyscout (eventos)** | posición **medida** (mediana de acciones) y avance reales | a cotización | Lo que cambiaría la posición nominal por medida; pedir PL, post-partido, derivados, sin redistribución |
| **SkillCorner / Opta Vision (tracking)** | XY real | enterprise | Más adelante, con ingresos |
| **Otros baratos** (TheStatsAPI desde ≈$50; Highlightly desde ≈$9,5/mes; football-data.org) | cobertura y licencias variables | bajo | No investigados a fondo; solo si fallan los anteriores |
| **Fuentes públicas** (Understat para tiros por zona, ya en uso; FPL) | base gratuita | €0 | Seguir usándolas |

**Prueba barata propuesta (opcional, €0):** durante una jornada, registrar con el plan gratuito de API-Football la hora a la que aparece el once confirmado y las bajas, y compararla con Sportmonks. Solo agregados, sin guardar datos crudos y respetando sus términos. Decide si hay un proveedor con mejor latencia, no si hay mejor dato.

**Disparadores para volver a mirar proveedores (2027):** (1) ≥N suscriptores de pago que justifiquen más gasto; (2) una función concreta que necesite posición medida o cobertura europea garantizada; (3) cambios de precio o de licencia de Sportmonks; (4) incidencias de latencia o de cobertura en producción.

## 9. Qué hacer con el contrato de €29 a partir de hoy

1. **Producir lo que sí aporta valor visible**, en este orden (ya planificado en [PROD_INGESTION](../../../football-intelligence/PROD_INGESTION.md)): cambios de posición y "quién sustituye a quién" en la ficha del jugador; después la alineación predicha/confirmada (con la fecha del deadline clara); defensas "carrilero" como señal de FPL. **No** publicar M1/M2 como producto (FI-10).
2. **Mantener la regla de diseño:** ningún endpoint devuelve payloads crudos de Sportmonks; sin exportaciones masivas; procedencia `licensed_starter` en producción; `live_trial_local` sigue rechazado; R2 privado (sin dominio público ni r2.dev).
3. **Medir el uso y el retorno:** dejar el plan mensual, registrar llamadas reales por día y qué funciones consumen el dato; revisar en 2027 (¿anual −20 %? ¿seguir?).
4. **Reevaluar** con los disparadores de la sección 8.
5. **Cierre de costes:** confirmar que solo queda Starter y que no hay complementos activos.

## 10. Fuentes en el repositorio

[decision-draft.md](decision-draft.md) · [data-capability Q1–Q8](2026-10-18-data-capability-q1-q8.md) · [backtests FPL](2026-10-18-historical-backtests-fpl.md) · [backtests Sportmonks](2026-10-18-historical-backtests-sportmonks.md) · [campos y cobertura](2026-10-14-field-coverage.md) · [Match Facts](2026-10-17-extra-matchfacts.md) · [Predictions y Odds](2026-10-17-extra-predictions-odds.md) · [Pressure y xG](2026-10-17-extra-pressure-xg.md) · [rolling origin](2026-10-13-rolling-origin.md) · [otras competiciones](2026-10-21-otras-competiciones-fuentes-publicas.md) · [TRIAL_GO_NO_GO](../../TRIAL_GO_NO_GO.md) · [TRIAL_LICENSING_CHECKLIST](../../TRIAL_LICENSING_CHECKLIST.md) · [PROD_INGESTION](../../../football-intelligence/PROD_INGESTION.md).

Fuentes externas (comparativas de terceros, no oficiales; verificar): [Sportmonks: planes y precios](https://www.sportmonks.com/football-api/plans-pricing) · [Sportmonks: alternativas a Opta](https://www.sportmonks.com/football-api/alternatives/opta/) · [Sportmonks: alternativa a API-Football](https://www.sportmonks.com/football-api/alternatives/api-football/) · [TheStatsAPI: mejores APIs de fútbol 2026](https://www.thestatsapi.com/blog/best-football-api) · [Highlightly: mejores APIs 2026](https://highlightly.net/blogs/best-football-apis-in-2026).
