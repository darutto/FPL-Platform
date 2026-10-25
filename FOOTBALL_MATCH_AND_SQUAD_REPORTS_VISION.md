# Bendito Fantasy — Visión técnica de reportes de partido y de equipo FPL

**Estado:** brief direccional de producto y arquitectura, **no** implementación aprobada.  
**Fecha:** 2026-10-25.  
**Para:** Claude, Codex, revisores y responsables de producto.  
**Alcance:** Premier League, Fantasy Premier League y fuentes existentes de Bendito Fantasy.

## 1. Tesis de producto

Bendito Fantasy debe conectar **lo conocido antes de una jornada**, **lo ocurrido en el terreno de juego** y **lo que eso cambia para las jornadas siguientes**. Dos reportes usan un mismo conjunto de hechos y evidencias:

1. **Reporte de partido:** resultado, formaciones, posiciones de inicio, minutos, contribuciones ofensivas y defensivas y cambios observables de contexto; explicación futbolística rigurosa.
2. **Reporte del equipo FPL del usuario:** evaluación de sus quince picks y su once efectivo, distinción entre señales pre-jornada y desempeño observado, y seguimiento de hipótesis sobre rol, titularidad y participación hacia las próximas jornadas.

El producto no debe inventar causas ni transformarse automáticamente en recomendador de compras. Su valor es construir **explicaciones trazables, contextualizadas y longitudinales**. Un jugador con pocos puntos puede haber creado buenas ocasiones; otro puede sumar puntos sin repetir esa producción; otro pudo perder minutos o cambiar de rol. Estas son interpretaciones que deben justificarse con datos, no etiquetas automáticas.

> **Restricción esencial:** hoy Bendito Fantasy **no calcula una proyección propia y calibrada de puntos FPL**. No publicar “6,2 puntos esperados”, “rendimiento frente a puntos proyectados” ni gráficas predicted-vs-actual hasta que exista explícitamente ese modelo. xG/xA son estadísticas de eventos futbolísticos, **no** puntos esperados de FPL. M1 estima minutos y M2 evalúa rol, pero no proporcionan puntos FPL esperados.

## 2. Estado actual: confirmado, parcial y ausente

Las referencias siguientes se inspeccionaron en el repositorio; antes de ejecutar, Claude debe volver a auditar HEAD, los PRs recientes y el despliegue. La existencia de un archivo, contrato o PR no demuestra que una capacidad esté activa en producción.

| Capacidad | Estado evidenciado | Límite para los reportes |
|---|---|---|
| Datos FPL, puntos reales, minutos, GW, fixtures e históricos | Ecosistema FPL y herramientas del asistente existentes | No implica puntos proyectados |
| Picks FPL de un manager: 15 futbolistas, orden, once/banca, capitán y puntos | Ruta `packages/fpl-ui/app/api/fpl-squad/[teamId]/route.ts`: picks y live de la **GW actual** | **No** equivale a snapshots de picks predeadline ni a un histórico persistido y verificado para reportes de todas las GW |
| Understat / producción ofensiva | Integración disponible en el proyecto | Auditar qué métricas exactas, con qué granularidad y frescura están accesibles al compositor |
| Sportmonks: formación, casilla inicial, XI, bajas y cruzamiento de identidades | Cliente e inventarios FI; 97,2 % de jugadores FPL con minutos identificados automáticamente en el trial 2026-27 | `formation_field` es posición **inicial anunciada**, no posición media, mapa de calor ni movimiento intrapartido |
| M1 minutos, M2 rol, M3 contexto del calendario | Evaluadores y contratos en `packages/football-intelligence/MODULE_CONTRACT.md` | Ni puntos proyectados ni superioridad predictiva demostrada contra reglas simples; M3 es descriptivo |
| M4 disrupción por bajas; M5 flanco frente al rival | **Esqueletos no operativos** según el contrato FI | No afirmar que esas explicaciones zonales o causales estén implementadas |
| B3 ingesta licenciada, B4 exposición y wiring | `packages/football-intelligence/PROD_INGESTION.md` documenta arquitectura y etapas separadas | Confirmar qué PRs están mergeados, desplegados y consumidos por el asistente en producción |
| Stats individuales `lineups.details`: toques, pases, tiros, duelos, pases clave, recuperaciones | Observadas con **token del trial** en 60 partidos (`2026-10-14-field-coverage.md`) | **Sin entitlement de Starter confirmado por escrito**; B3 no las ingiere; nuevo trabajo requerido |
| Estadísticas de equipo: posesión, tiros, córners y pases | Observadas durante el trial | Confirmar si Starter incluye los endpoints/campos reales |
| Mapas de calor de jugadores / acciones XY | **No hay evidencia suficiente**; `ballCoordinates` de prueba no prueba asociación XY con cada futbolista | No dibujar áreas de influencia como medidas reales |
| Report composer, snapshots predeadline y ledger longitudinal de hipótesis | **No identificados como subsistema operativo** | Diseño e implementación por etapas |
| Modelo de puntos FPL esperados | **No existe** | Fuera de alcance del MVP |

**Documentos y código de referencia:**

- `packages/sportmonks-client/trial-reports/live/2026-10-24-trial-conclusions.md`
- `packages/sportmonks-client/trial-reports/live/2026-10-14-field-coverage.md`
- `packages/football-intelligence/PROD_INGESTION.md`
- `packages/football-intelligence/MODULE_CONTRACT.md`
- `packages/football-intelligence/CONTRACT.md` y `FEATURE_CONTRACT.md`
- `packages/fpl-ui/app/api/fpl-squad/[teamId]/route.ts`
- `packages/fpl-grounded-assistant/fpl_grounded_assistant/football_intelligence_tools.py`

## 3. Reporte de partido: cómo y por qué funcionaría

**Grano de análisis:** un fixture canónico y sus dos clubes, con estatus final o parcial explícito.

### Hechos de primer nivel

Marcador, fecha, adversarios, XI inicial, formación y casilla inicial, suplentes, minutos, goles y hechos FPL. Registrar fuente, versión, fecha de observación y calidad. La formación inicial es **una fotografía táctica del once anunciado**, no un mapa de movimientos reales.

### Métricas opcionales

Si los permisos y los campos reales lo permiten, añadir posesión, tiros, tiros a puerta, remates dentro del área, córners, pases y otras estadísticas de equipo; para jugadores, toques, tiros, pases clave, recuperaciones, duelos, centros, etc. No depender de estas métricas para que el reporte básico sea útil. El trial muestra que el proveedor a menudo omite estadísticas con valor cero: **validar la semántica por campo y no confundir `0` con `null`/no entregado**.

### Interpretación respaldada

Contrastar posiciones iniciales y métricas con encuentros previos para detectar: nuevo rol, titularidad recuperada o perdida, suplente ocupando un hueco, aumento/disminución de remates o participación. Mantener separación entre **observado** (casilla distinta), **asociado** (coincidió con ausencia de un compañero), **hipótesis** (posible repetición) y **causal confirmado** (solo con soporte específico).

### Jugadores destacados

En el MVP, seleccionar líderes por criterios **transparentes** (más tiros, pases clave, recuperaciones, ocasiones) según el rol. No fabricar una puntuación general de «influencia» con pesos arbitrarios ni copiar sin crítica el rating de otro proveedor. Un futuro índice debería versionar fórmula, rangos, pesos por posición, calidad de datos y comparaciones basales.

### Espacialidad

Se puede representar el **diagrama del XI inicial**. No se debe dibujar un heatmap personal, zona de toques, dirección exacta de pases ni cambios durante el partido sin eventos espaciales vinculados a futbolistas. `ballCoordinates` a nivel de partido no demuestra seguimiento individual.

## 4. Reporte del equipo FPL: unidad y tres horizontes

**Grano:** `(season, entry_id, gameweek)` más las fixtures asociadas a cada pick. Considerar blank GW, double GW, capitán, vicecapitán, auto-sustituciones, banca y chips según las reglas oficiales. No recalcular puntos oficiales usando una simplificación no validada.

### Antes del deadline: postura congelada

Crear un snapshot con quince picks, once y banca, capitán, fecha límite, rivals, minutos recientes, historial de roles iniciales, estados de disponibilidad y señales descriptivas. Guardar cuándo se supo cada cosa y la ventana utilizada. Si el manager cambia de picks antes del deadline, versionar o definir cuál es el último snapshot válido. **No inventar una instantánea previa si no fue capturada a tiempo.** No llamar «predicción propia» al once provisional de Sportmonks.

### Después de la jornada: diagnóstico de hechos

Calcular puntos **reales** conciliados con FPL para el once efectivo y capitán; agregar minutos, posición inicial y métricas ofensivas disponibles. Priorizar **dos a cinco historias no genéricas**: no titular esperado, rol diferente, participación ofensiva mantenida pese a pocos puntos, caída real de remates, sustituto que gana el hueco. «Menos puntos que su media de las últimas N GW» es comparación histórica, **no** «menos de lo esperado según un modelo».

### Hacia próximas jornadas: seguimiento condicionado

Continuar señales pertinentes para el usuario con estado `vigilar`, `fortalecida`, `debilitada`, `inconclusa`, `caducada`. Relacionar cambio de rol, disponibilidad y siguiente calendario sin declarar probabilidades calibradas ni dar recomendaciones automáticas. Un aviso sobre un jugador debe mostrar la evidencia, fecha, tamaño de muestra y condiciones que podrían invalidarlo.

**Caso conceptual — Morgan Rogers y João Pedro:** comprobar por IDs canónicos en qué casilla comenzó Rogers con/sin João Pedro en el XI, si cambió su producción y cuánto aportan rivales y muestras. Si existe asociación, decir «comenzó en otra casilla coincidiendo con la ausencia de João Pedro». No decir «se movió en el partido», «fue por la lesión» o «rendirá más» sin evidencia independiente. Una ausencia del XI no prueba lesión. El bug observado de resolución del nombre «João Pedro» exige unión por ID, club y fecha, nunca substring ambiguo.

## 5. Núcleo transversal: registro persistente de hipótesis

La idea diferencial es preservar lo que Bendito Fantasy **realmente sabía y sospechaba ANTES** de un partido, evaluarlo después y mantener continuidad entre GW. Proponer ledger **append-only** versionado. Campos conceptuales (no esquema aprobado):

- `hypothesis_id`, `subject_id/type`, `fixture_id`/`gw`, `statement_template`, `created_at`, `as_of`, `valid_until`.
- `evidence_refs` y versión de fuente/manifest, `basis` observed/inferred_proxy, `sample_size`, `missingness`, `counter_evidence`.
- `trigger_conditions`, `status`, `evaluated_at`, `supersedes_event_id`.

Cada revisión registra un evento adicional, no reescribe lo pensado antes. **Un insight retrospectivo no se etiqueta como señal predeadline.** Separar hechos de partido compartidos entre managers de snapshots privados de picks y reportes personalizados.

El seguimiento puede decir: «Antes de GW7 se marcó como posible cambio de casilla; tras GW7 observamos X; antes de GW8 mantenemos/retiramos la señal». Nunca inventar confianza porcentual si no está calibrada.

## 6. Arquitectura conceptual (respetando contratos)

```text
FPL picks/results/history ──────┐
Understat (si disponible) ───────┼─> identity + temporal validation + provenance
Sportmonks licensed Starter ────┘                      │
                                              facts canónicos
                                                    │
                     ┌──────────────────────────────┴─────────────────────┐
                     │                                                    │
                match composer                                      squad composer
                     │                                                    │
              post-match facts                                   snapshots predeadline
                     └──────────────── hypothesis ledger ────────────────┘
                                                    │
                                   next-GW watch / assistant / UI
```

**Separación de responsabilidades:** clientes actuales ingieren y gobiernan fuentes; FI-5/FI-6 mantienen sus contratos; una nueva capa de ensamblaje produce un reporte derivado y reproducible; renderer/LLM **solo** expresa hechos e hipótesis con evidencia (no calcula datos implícitos). Salida conceptual: `report_kind`, `status`, `scope`, `as_of`, `facts`, `insights`, `evidence_refs`, `unavailable_sections`, `report_version`.

**Tiempo:** guardar `fpl_deadline`, `fixture_kickoff`, `source_event_time` si existe, `observed_at/ingested_at`, `report_as_of`. Replay con el mismo corte y versiones debe dar igual resultado. Datos de alineación confirmada, aparecidos después del deadline, no justifican una expectativa anterior.

**Licencia:** mantener el feed Sportmonks y R2 privados; no exponer filas crudas o reconstruibles por API/UI, logs o GitHub. Comprobar entitlement Starter y permiso para derivados estadísticos antes de publicar métricas del trial. Degradar la sección opcional si falla la cobertura/derecho, nunca inventar datos.

## 7. Validación y construcción incremental propuestas

**Gate 0. Auditoría del estado real.** Claude inspecciona HEAD y producción, B3/B4, FI-7, picks históricos, tablas de FPL y Understat, contratos y derechos de stats Starter. Matriz `operativo | implementado no desplegado | solo trial | no existe` con refs a archivos/PRs. Ningún cambio de contrato antes de validar.

**Slice 1. Reporte factual de un partido ya jugado.** Construir salida estructurada con resultado, XI, casillas iniciales, minutos y hechos FPL; estadísticas adicionales si derecho y cobertura confirmados. Verificación de datos y narración sin espacios inventados.

**Slice 2. Reporte retrospectivo de una plantilla FPL real.** Con `entry_id` autorizado y GW específica, obtener los picks de **esa GW** (no los actuales), puntos oficiales, banca y capitán; escribir 2–5 insights con evidencia. Si no hay snapshot predeadline, llamarlo **retrospectivo**, no evaluación de predicciones previas.

**Slice 3. Una hipótesis persistente.** Capturar una a tres señales verificables *antes* del siguiente deadline, evaluarlas tras la GW y continuar el estado en la siguiente. Empezar por cambio de casilla observado y compañero fuera del XI; no atribuir causa.

**Slice 4. Evaluación A/B.** A igual fecha/corte y pregunta, comparar reporte FPL-only vs FPL+Sportmonks: exactitud, hechos nuevos, trazabilidad, utilidad, incertidumbre, fallos de identidad y utilidad del seguimiento. No medir causalmente puntos ganados sin diseño experimental.

**Más adelante, por separado:** stats detalladas, destacados por categorías, reportes de jornada, exportes podcast, un eventual índice calibrado de influencia o un eventual modelo propio de proyecciones FPL. **No** convertir estos elementos en dependencias del MVP.

## 8. Gates de exactitud y no alucinación

- Identidad por IDs canónicos y club correcto **a fecha del partido**; homónimos y transferencias; no substring como clave de join.
- `not_started` != `did_not_play` != `unavailable`; lesión confirmada con fecha != no apareció en XI.
- XI provisional != XI confirmado; posición inicial anunciada != movimiento dentro del partido.
- Muestra pequeña no implica tendencia estable; correlación de cambio de rol y xGI no demuestra causa.
- Ausencia de estadística != cero salvo semántica validada; timestamp de ingesta != momento en que fuente publicó dato.
- GW doble/blanca, capitán, autosubs, chips y conciliación de puntos contra la API oficial.
- Replay sin datos del futuro; datos luego del deadline jamás sustentan «lo sabíamos antes».
- Entitlement/licencia insuficiente produce degradación visible, nunca datos crudos abiertos.

## 9. Criterios de éxito del MVP

1. Un partido genera reporte fiel, trazable y sin interpretación espacial falsa.
2. Un equipo FPL muestra los quince picks correctos de una GW histórica y sus puntos reconciliados.
3. Genera dos a cinco conclusiones individualizadas con evidencia (no párrafos genéricos).
4. Puede mostrar «esto se conocía antes» **solo** cuando existe snapshot anterior al deadline.
5. Registra y revisa al menos una hipótesis entre dos GW consecutivas.
6. La variante Sportmonks aporta información táctica verificable frente a FPL-only, aunque no mejore M1/M2.
7. Casos sin identidad, fuente, licencia o cobertura degradan honradamente.

## 10. Encargo de lectura para Claude

Este documento **orienta** la solución; no autoriza construir todo ni modifica contratos por sí mismo. Entregar primero: (a) auditoría real por archivo, PR y deployment; (b) contratos propuestos para match facts, squad snapshot y hypothesis ledger; (c) plan de 2–4 PRs acotados; (d) un reporte **real, sin cifras inventadas**, con missingness visible; (e) riesgos de temporalidad, identidad, licencia y datos no operativos. No presentar expected FPL points, mapas de calor individuales, causalidad por lesiones ni predictor de rotación validado como capacidades actuales.
