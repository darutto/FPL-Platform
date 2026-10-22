# FI-9 — Borrador del informe de decisión GO / NO-GO (Sportmonks)

**Estado:** borrador vivo, abierto el 2026-10-11; **GW7 incorporada el 2026-10-19** (secciones nuevas más abajo). Se completa el 23-oct y la decisión queda registrada en
[TRIAL_GO_NO_GO.md](../../TRIAL_GO_NO_GO.md). El trial vence el **2026-10-25 03:09 UTC**; si la decisión es NO-GO hay que
cancelar antes o se cobra la primera cuota.

**Qué se contrataría (decidido por Leo el 2026-10-21):** plan **Starter solo** (Premier League), **€29/mes + IVA**,
**mensual primero** (el anual da −20 % recurrente; se decide más adelante con datos de uso). **Sin Euro Club Tournaments.**
Antes se contemplaba Starter + Euro Club Tournaments (€58/mes); ver «Respuestas de Sportmonks» más abajo.

## Los seis criterios (todos necesarios para GO)

| | Criterio (TRIAL_GO_NO_GO.md) | Estado a 2026-10-11 | Evidencia | Falta |
|---|---|---|---|---|
| a | ≥95 % de jugadores PL emparejados automáticamente con FPL (≥99 % tras la cola manual) | **Cumple la parte automática: 413/425 = 97,2 %.** Denominador: jugadores FPL con minutos que siguen en un club PL (las bajas por regla, fuera). Cola manual: 9 confirmaciones de Leo en curso; techo esperado 422/424 ≈ 99,5 % | [mapping](2026-10-11-mapping.md) | Correr el mapping con las confirmaciones; re-medir estabilidad de ids (obj. 18) el 12 y 13 |
| b | Alineaciones confirmadas con formación + grid antes del saque en ≥90 % de los partidos observados | **Semántica validada** (198/198 titulares con grid y posición; regla de lados 420/420 y 58/58; lados validados por Leo en Arsenal, Liverpool y City). **GW7 medida:** en los **8 partidos observables** el once confirmado no figuraba en lecturas de 72 min o más antes del saque y **ya figuraba entre 15 y 59 minutos antes** (8 de 8); la llegada real cae entre ambas lecturas (4 de los 8 con la medida limitada por un reinicio del vigilante, así que 15–59 son cotas). El marcador `lineup_confirmed` pasa de falso a cierto justo entonces: **la señal fiable existe**. Llegó **siempre después de la fecha límite de FPL** (17-oct 10:00 UTC), y la alineación provisional ya difería de la confirmada: 1 a 6 jugadores (media 2,9) o 3 a 9 de 22 puestos (media 5,5). **Dos partidos no se pueden certificar** (ver límites): la regla «≥9/10» no es demostrable con GW7 (8 de 8 observados, 2 sin observación) | [provisional-lineups](2026-10-11-provisional-lineups.md), [grid-check](2026-10-11-grid-check-for-leo.md), sección «GW7: llegada de la alineación» más abajo | Decidir si 8 de 8 observados basta, o repetir con GW8 y un vigilante sin huecos |
| c | Bajas actualizadas ≤48 h tras la noticia pública en casos muestreados | En medición: pasada de bajas por club cada 8 h desde 2026-10-11 04:07 UTC, con huecos registrados. Resolución de la medida: 8 h | TRIAL_STATUS (log) | Casos nuevos durante la semana y comparación con la noticia pública |
| d | La licencia permite guardar datos crudos, puntuaciones derivadas y mostrarlas a suscriptores | **PASA (2026-10-21).** Respuesta escrita de soporte de Sportmonks: se puede guardar, conservar tras cancelar (lo obtenido mientras había suscripción), combinar con otras fuentes, derivar y mostrar a suscriptores; solo está prohibido revender o redistribuir el feed crudo | [checklist](../../TRIAL_LICENSING_CHECKLIST.md) (Q2–Q8, Q14) | — |
| e | El plan cubre PL + UCL + FA Cup + EFL Cup como mínimo | **Sustituido por decisión de Leo (2026-10-21):** PL con Starter; UCL/UEL/UECL y copas con datos públicos programados ([propuesta](2026-10-21-otras-competiciones-fuentes-publicas.md)); las copas de Sportmonks, como best-effort. Motivo: Starter cubre solo la Premier League, UCL/UEL/UECL exigen Euro Club Tournaments (no se contrata) y FA Cup/Carabao llegan con cobertura sin garantía de completitud. Es una desviación de la regla preregistrada en TRIAL_GO_NO_GO.md, que no se modifica; este borrador la registra. Antes (2026-10-11): cumplía con Starter + Euro Club Tournaments | [routes](2026-10-11-routes.md), [checklist](../../TRIAL_LICENSING_CHECKLIST.md) (Q9, Q10) | — |
| f | M1–M3 producen evidencia sensata (≥20 jugadores revisados) | **Sensato con matices, y se mantiene con GW7.** M2 sigue sin mejorar a «repite su último partido»: rol 91,0 % contra 92,9 % y flanco 81,4 % contra 82,8 % (GW2–7). GW7 es la semana más difícil (21 cambios de rol frente a 6–11 antes) y el módulo predijo el rol nuevo en 7 de 21. M1 mejora claramente la tasa base (Brier 0,149 contra 0,203) y solo roza la forma bruta (0,156); cobertura 53 %. M3 cuadra el 100 % con el calendario en todas las jornadas (120/120). Revisión de Leo: 8/10 sin objeción, 2 explicados (sobre GW6; la validación de Arsenal también es de GW6) | [m1-m3](2026-10-11-m1-m3.md), [revisión de Leo](2026-10-11-m1-m3-review-for-leo.md), [rolling origin](2026-10-13-rolling-origin.md) | Nada nuevo que medir con estos módulos; la revisión humana de GW7 queda en `review_for_leo.md` (local) |

## Respuestas de Sportmonks (2026-10-21) y decisión del plan

Fuente: respuesta escrita de soporte de Sportmonks (Kim), recibida el 2026-10-21; el contenido relevante está volcado en el
checklist y aquí. Detalle pregunta a pregunta en [TRIAL_LICENSING_CHECKLIST.md](../../TRIAL_LICENSING_CHECKLIST.md).

- **Licencia (criterio d, pasa):** guardar en base propia y usar en la app; conservar tras cancelar lo obtenido con suscripción activa
  (sujeto a los ToS); combinar con otras fuentes (p. ej. datos públicos de FPL) y calcular puntuaciones, modelos e insights propios;
  mostrar insights derivados a suscriptores de pago; mostrar campos sueltos e ids de Sportmonks dentro del producto. **Prohibido:**
  revender o redistribuir el feed crudo como producto de datos, exponer la API o dejar que clientes reconstruyan el feed.
  Reglas de diseño que se siguen: ningún endpoint (público o autenticado) devuelve payloads crudos de Sportmonks y no se publican
  exportaciones masivas de tablas de origen Sportmonks.
- **Plan decidido por Leo:** GO **solo con Starter, €29/mes, mensual primero**; **sin Euro Club Tournaments**. Starter incluye sin
  add-on: alineaciones, formaciones, `formation_field`/grid, posiciones detalladas, alineaciones predichas, `lineup_confirmed`, bajas
  (lesiones y sanciones) y plantillas, de la Premier League; últimas 3 temporadas (más antiguas, add-on Historical Data). No hay
  descuento ni paquete solo-PL más barato.
- **Límite de peticiones:** **2.000 por entidad y hora** en Starter. Los 2.500/h del trial vienen del paquete Euro, no de Starter:
  las medidas de ritmo del trial se transfieren de forma conservadora (Starter es un 20 % menor; las ejecuciones planeadas son ~250
  llamadas).
- **Copas:** FA Cup y Carabao pueden devolver los mismos tipos de alineación y calendario, pero la cobertura varía por partido y
  temporada, sin garantía: **best-effort**, degradar sin romper cuando falten. La respuesta no dice que estén incluidas en el precio
  de Starter ni que se puedan elegir por separado.
- **Acciones de Leo (suyas, en el panel de Sportmonks) antes del vencimiento del trial, 2026-10-25 03:09 UTC:** quitar **todos los
  add-ons del trial** (Match Facts, Pressure & xG, Predictions, Odds) **y Euro Club Tournaments**. El código no debe depender de
  includes de esos add-ons. Decidido ya: facturación mensual.
- **Sin respuesta:** la pregunta 1 (cobertura completa del trial) y, dentro de la 12, entrenadores, sustituciones y estadísticas de
  partido; no se asumen.
- **Cobertura de las demás competiciones (Champions, Europa League, Conference, FA Cup, Carabao):** decisión de Leo, consultas
  públicas programadas. Propuesta, sin construir nada:
  [2026-10-21-otras-competiciones-fuentes-publicas.md](2026-10-21-otras-competiciones-fuentes-publicas.md).

## Criterio (f) jornada a jornada (rolling origin, GW2–7)

Para cada jornada k = 2…7 se predice GWk con la historia estrictamente anterior al saque de cada partido (GW1 no
tiene historia: no hay base posible). Sin llamadas nuevas; informes en
[2026-10-13-rolling-origin.md](2026-10-13-rolling-origin.md) (GW2–6) y la ejecución local `rolling-origin-gw7` (GW2–7,
`rolling_origin.md`; local, no se publica).

| GW | M2 rol: módulo vs base (n) | M2 flanco: módulo vs base | M2 abstiene | Donde difieren: base / módulo | Cambios de rol: n / detectados / rol nuevo predicho | M1 Brier: módulo vs constante vs forma bruta | M3 vs calendario |
|---|---|---|---|---|---|---|---|
| 2 | no responde (0 de 220) | — | 220 | — | — | 0,132 vs 0,133 vs 0,157 | 20/20 |
| 3 | no responde (0 de 220) | — | 220 | — | — | 0,134 vs 0,166 vs 0,138 | 20/20 |
| 4 | 92,3 % vs 95,8 % (143) | 91,5 % vs 91,5 % | 77 | 5 / 0 | 6 / 0 / 0 | 0,142 vs 0,191 vs 0,147 | 20/20 |
| 5 | 93,6 % vs 94,9 % (157) | 88,0 % vs 90,0 % | 63 | 4 / 2 | 8 / 0 / 2 | 0,166 vs 0,211 vs 0,175 | 20/20 |
| 6 | 91,1 % vs 93,5 % (168) | 75,9 % vs 79,6 % | 52 | 7 / 3 | 11 / 1 / 3 | 0,164 vs 0,225 vs 0,168 | 20/20 |
| 7 | 87,8 % vs 88,3 % (180) | 73,4 % vs 73,4 % | 37 | 8 / 7 | 21 / 2 / 7 | 0,149 vs 0,234 vs 0,151 | 20/20 |
| todas | 91,0 % vs 92,9 % (648) | 81,4 % vs 82,8 % (215) | 669 | 24 / 12 | 46 / 3 / 12 | 0,149 vs 0,203 vs 0,156 | 120/120 |

Lectura: M2 empieza a poder responder en GW4 (necesita 3 inicios) y **no gana a la base en ninguna jornada**; en GW7 casi
empata (87,8 % contra 88,3 %) y, de los 21 cambios de rol de la semana, predijo el rol nuevo en 7 y detectó el cambio en 2.
M1 gana a la tasa base en todas las jornadas salvo un empate en GW2, pero **solo roza la forma bruta** (0,149 contra
0,156) y responde en el 53 % de los casos (se abstiene en fichajes y vueltas de lesión). M3 cuadra con el calendario en
todas; en la ejecución de GW7, el módulo M3 resuelve 158 de 160 equipos-partido (2 `missing_context` por banda de posición
en liga desconocida).

## GW7: llegada de la alineación (vigilante)

Medido sobre `lineup-watch/gw7.ndjson` (solo agregados; sin alineaciones ni identificadores en este documento).

| Partido(s) | Última lectura sin confirmar (min antes del saque) | Primera lectura con confirmado (min antes del saque) | Nota de la medida | Provisional vs confirmado: jugadores distintos / puestos distintos (de 22) |
|---|---|---|---|---|
| Sábado 14:00 (3 partidos) | 127 | 55 | hueco de 71 min entre lecturas | 6 / 9, 3 / 3, 4 / 8 |
| Sábado 16:30 | 72 | 15 | vigilante reiniciado a las 16:15; 15 es una cota | 3 / 9 |
| Domingo 13:00 (3 partidos) | 80 | 24 | vigilante reiniciado a las 12:36; 24 es una cota | 1 / 4, 1 / 3, 3 / 4 |
| Domingo 15:30 | 79 | 59 | lecturas cada ~20 min | 2 / 4 |

- **Resumen de los 8 partidos observables:** el once confirmado **no figuraba 72 minutos o más antes del saque** y **ya
  figuraba 15 a 59 minutos antes**; la llegada real cae entre las dos lecturas, es decir, **en la última hora y media**.
  La provisional difiere en **1 a 6 jugadores (media 2,9)**, o en **3 a 9 puestos de 22 (media 5,5)** si se cuenta quién
  ocupa cada casilla.
- **Siempre después de la fecha límite de FPL** (17-oct 10:00 UTC): la alineación confirmada no puede alimentar una
  decisión de FPL antes del deadline; la provisional sí, con unos 3 jugadores de error medio por partido.
- **Límites (no cuentan como observación):** Tottenham–Coventry (lunes) sin observación de llegada, vigilante caído de
  00:18 a 22:30 UTC del 19-oct; Everton–Chelsea (sábado 11:30), primera lectura 23 min **después** del saque. Los
  reinicios del vigilante (sábado 16:15, domingo 12:36, esta última tras el reinicio del PC) hacen que los tiempos del
  sábado 16:30 y del domingo 13:00 sean cotas y no llegadas exactas. La sonda de plazo del lunes 19 de los add-ons no
  llegó. `leo_validated_arsenal` (validación de Leo) es solo de GW6.

## Lo que el trial ya dejó claro, decida lo que decida

- **El dato es bueno y es lo que se compra:** posiciones reales por partido, flancos, minutos, cambios, bajas por club y
  calendario de todas las competiciones. La base simple que gana a M2 está hecha con ese mismo dato.
- **Primera mejora de producto identificada:** defensas de FPL que juegan de carrilero (Meunier, De Cuyper) — la señal
  más valiosa para FPL; hoy mal etiquetados como «extremo». Propuesta FI-10.
- **Lo que añade GW7:** la alineación confirmada llega tarde para decidir (en la última hora y media antes del saque, siempre tras la
  fecha límite de FPL) y los módulos no superan a las bases simples; lo que sí funciona es **explicar** a posteriori
  quién ocupa qué puesto y desde cuándo (ver los informes de relaciones y de backtests: #472, #475, #478, #480, #482).
- **El cliente se escribió contra mocks y la API real es distinta** (8 de 15 familias son includes); ya está remapeado
  y documentado.

## Riesgos registrados (TRIAL_STATUS)

R1 techo post-cola · R2 latencia de bajas con resolución de 8 h y crons que caducan · R3/R9 lados de centrales y
alineaciones provisionales · R4 estabilidad de ids entre días · R5 listas con tope de páginas · R6 supuestos de
calendario (aplazamientos invisibles) · R7 cobertura de M1 · R8 coste de cómputo · R10 bajas no localizables en
Sportmonks.

## Regla de decisión propuesta

- **GO** si: (a) ≥99 % tras la cola, (b) once confirmado antes del saque en ≥9/10 partidos de GW7 con una señal fiable
  para distinguirlo, (c) sin bajas con retraso >48 h en los casos muestreados, (d) «sí» a 3–6, y (f) se mantiene con
  GW6 completa y GW7.
- **NO-GO / aplazar** si (d) dice «no» a mostrar derivados a suscriptores, o si el once confirmado llega tarde o no es
  distinguible (sin eso, M2 y M1 no sirven para decidir antes del deadline de FPL).
- **GO parcial:** si (b) y (d) pasan pero M1/M2 no aportan sobre las bases, contratar por el **dato** (posición real,
  flancos, bajas, calendario) y tratar los módulos como trabajo de FI-10.

## Recomendación

*Se cierra el 23-oct con todos los datos. Estado a 19-oct, con GW7 medida:* **GO parcial**: contratar por el **dato** y
por la **explicación**, no por la predicción. Lo que dicen los números:
- **No cambia con GW7.** M2 no gana a «repite su último partido» (91,0 % contra 92,9 % en GW2–7; en GW7, 87,8 % contra
  88,3 %), M1 solo roza la forma bruta (0,149 contra 0,156) y la alineación confirmada llega en la última hora y media
  antes del saque (vista entre 15 y 59 minutos antes), siempre después de la fecha límite de FPL. Ninguno de esos números empuja hacia un GO completo.
- **Tampoco hay un número que empuje a NO-GO** por la parte técnica: el dato es bueno (posición, flanco, minutos,
  calendario de todas las competiciones), M3 cuadra con el calendario al 100 % y el marcador de alineación confirmada
  sí distingue la confirmada de la provisional.
- **Pendiente de decisión humana:** (d) la licencia (un «no» en cualquiera = NO-GO), (c) la latencia de bajas, y si
  8 de 8 partidos observados con once confirmado antes del saque bastan para el criterio (b), dado que 2 de 10 no se
  pudieron observar.

**Si se contrata:** mensual hasta tener datos de uso; los módulos M1/M2 como trabajo de FI-10, no como producto.

**Actualización 2026-10-21:** el criterio (d) pasa (respuesta de soporte) y Leo decidió el plan: **GO con Starter solo, €29/mes,
mensual primero, sin Euro Club Tournaments**, con los add-ons del trial retirados antes del 25-oct 03:09 UTC (acción de Leo). Sigue
vigente la lectura «contratar por el dato y la explicación, no por la predicción». El criterio (e) queda sustituido por decisión de Leo (ver su fila): PL con Starter; UCL/UEL/UECL y copas con datos públicos
programados, y las copas de Sportmonks como best-effort. Las secciones de arriba conservan el estado a 2026-10-11/19 como histórico.
