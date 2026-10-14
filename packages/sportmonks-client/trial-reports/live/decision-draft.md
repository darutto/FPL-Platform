# FI-9 — Borrador del informe de decisión GO / NO-GO (Sportmonks)

**Estado:** borrador vivo, abierto el 2026-10-11. Se completa el 23-oct y la decisión queda registrada en
[TRIAL_GO_NO_GO.md](../../TRIAL_GO_NO_GO.md). El trial vence el **2026-10-25 03:09 UTC**; si la decisión es NO-GO hay que
cancelar antes o se cobra la primera cuota.

**Qué se contrataría:** plan Starter (Premier League, FA Cup, Carabao Cup) + Euro Club Tournaments (UCL, UEL, UECL):
**€58/mes + IVA** mensual (€46/mes en anual). Elegir mensual hasta tener datos de uso.

## Los seis criterios (todos necesarios para GO)

| | Criterio (TRIAL_GO_NO_GO.md) | Estado a 2026-10-11 | Evidencia | Falta |
|---|---|---|---|---|
| a | ≥95 % de jugadores PL emparejados automáticamente con FPL (≥99 % tras la cola manual) | **Cumple la parte automática: 413/425 = 97,2 %.** Denominador: jugadores FPL con minutos que siguen en un club PL (las bajas por regla, fuera). Cola manual: 9 confirmaciones de Leo en curso; techo esperado 422/424 ≈ 99,5 % | [mapping](2026-10-11-mapping.md) | Correr el mapping con las confirmaciones; re-medir estabilidad de ids (obj. 18) el 12 y 13 |
| b | Alineaciones confirmadas con formación + grid antes del saque en ≥90 % de los partidos observados | **Semántica validada**: grid y posición detallada en 198/198 titulares de partidos terminados; regla de lados 420/420 (PL) y 58/58 (otras competiciones); lados validados por Leo con Sofascore en Arsenal, Liverpool y City. **Hallazgo:** la alineación provisional no se distingue de la confirmada en la fila (solo por estado del partido y por venir sin banquillo) | [provisional-lineups](2026-10-11-provisional-lineups.md), [grid-check](2026-10-11-grid-check-for-leo.md) | **Lo decisivo:** cuántos minutos antes del saque aparece el once confirmado (vigilante Coventry–Newcastle 12-oct y los 10 partidos de GW7, 16–20 oct) |
| c | Bajas actualizadas ≤48 h tras la noticia pública en casos muestreados | En medición: pasada de bajas por club cada 8 h desde 2026-10-11 04:07 UTC, con huecos registrados. Resolución de la medida: 8 h | TRIAL_STATUS (log) | Casos nuevos durante la semana y comparación con la noticia pública |
| d | La licencia permite guardar datos crudos, puntuaciones derivadas y mostrarlas a suscriptores | **Sin respuesta.** Preguntas enviadas por Leo (licencia y cobertura a comercial; técnicas 13, 15, 16 a soporte) | [checklist](../../TRIAL_LICENSING_CHECKLIST.md) | Respuestas a 3, 4, 5 y 6. Un «no» en cualquiera = NO-GO |
| e | El plan cubre PL + UCL + FA Cup + EFL Cup como mínimo | **Cumple** con Starter + Euro Club Tournaments (7 ligas visibles con el token) | [routes](2026-10-11-routes.md) | — |
| f | M1–M3 producen evidencia sensata (≥20 jugadores revisados) | **Sensato con matices.** M2 acierta el rol 90,5 % y el flanco 92,6 %, pero **no mejora a «repite su último partido»** (94,7 %) como predictor; su valor previsto (estabilidad, cambios, fuera de posición) aún sin medir. M1 mejora la tasa base (Brier 0,178 vs 0,229) pero apenas a la forma bruta (0,185) y se abstiene en fichajes y vueltas de lesión. M3 cuadra 140/140 con el calendario. Revisión de Leo: 8/10 sin objeción, 2 explicados | [m1-m3](2026-10-11-m1-m3.md), [revisión de Leo](2026-10-11-m1-m3-review-for-leo.md) | Repetir con GW6 completa (12-oct) y GW7 (19-oct), con la tabla «módulo vs base» |

## Criterio (f) jornada a jornada (rolling origin, 2026-10-13)

Para cada jornada k = 2…6 se predice GWk con la historia estrictamente anterior al saque de cada partido (GW1 no
tiene historia: no hay base posible). Sin llamadas nuevas; informe completo en
[2026-10-13-rolling-origin.md](2026-10-13-rolling-origin.md). Se añade GW7 el lunes 19.

| GW | M2 rol: módulo vs base (n) | M2 flanco: módulo vs base | M2 abstiene | Donde difieren: base / módulo | M1 Brier: módulo vs constante | M3 vs calendario |
|---|---|---|---|---|---|---|
| 2 | no responde (0 de 220) | — | 220 | — | 0,132 vs 0,133 | 20/20 |
| 3 | no responde (0 de 220) | — | 220 | — | 0,134 vs 0,166 | 20/20 |
| 4 | 92,3 % vs 95,8 % (143) | 91,5 % vs 91,5 % | 77 | 5 / 0 | 0,142 vs 0,191 | 20/20 |
| 5 | 93,6 % vs 94,9 % (157) | 88,0 % vs 90,0 % | 63 | 4 / 2 | 0,166 vs 0,211 | 20/20 |
| 6 | 91,1 % vs 93,5 % (168) | 75,9 % vs 79,6 % | 52 | 7 / 3 | 0,164 vs 0,225 | 20/20 |
| todas | 92,3 % vs 94,7 % (468) | 84,8 % vs 86,8 % | 632 | 16 / 5 | 0,149 vs 0,193 | 100/100 |

Lectura: M2 empieza a poder responder en GW4 (necesita 3 inicios) y **no gana a la base en ninguna jornada**; M1 gana a la
tasa base desde GW3 con margen creciente; M3 cuadra en todas.

## Lo que el trial ya dejó claro, decida lo que decida

- **El dato es bueno y es lo que se compra:** posiciones reales por partido, flancos, minutos, cambios, bajas por club y
  calendario de todas las competiciones. La base simple que gana a M2 está hecha con ese mismo dato.
- **Primera mejora de producto identificada:** defensas de FPL que juegan de carrilero (Meunier, De Cuyper) — la señal
  más valiosa para FPL; hoy mal etiquetados como «extremo». Propuesta FI-10.
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

*Se escribe el 23-oct con todos los datos.*
