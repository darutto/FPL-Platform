# Cierre del encargo de entradas de capitanía — qué entró y qué sigue vivo

**Fecha:** 2026-09-04 · **Encargo:** `CAPTAINCY_SCORING_INPUTS_HANDOFF.md`
**Continuación de:** `CAPTAINCY_SCORING_INPUTS_CODEX_HANDOFF.md` (Codex agotó
su cuota con las olas 0 y 1A hechas y B/C/D sin commitear)

Todo lo de abajo está en `main` **local**. **Nada se ha publicado**: el push
sigue necesitando autorización explícita del dueño.

## Lo que entró

| ola | trabajo | estado |
|---|---|---|
| 0 | Slices 0 y 1 · resolver de jornada, los dos caminos | ya venía hecho por Codex |
| 1A | Slice 2 · ventanas de chip desde el bootstrap | ya venía hecho por Codex |
| 1B | Slice 3 · minutos reales | terminado, medido y fusionado |
| 1C | prosa + tarjeta en una superficie | terminado y fusionado |
| 1D | i53 · `pool_source` al contrato | terminado y fusionado |
| 2E | Encargo 3 · pool abierto, listas cortas, hipster | terminado y fusionado |
| 2F | Slice 4 · enseñar el factor | terminado y fusionado |
| 3G | i52 · sonda de `caller` vs `derived` | escrita, **sin correr** (cuesta dinero) |

## Los tres hallazgos que no salieron de un test

**1 · La medición encontró un defecto, no un resultado.** El primer post del
Slice 0 dio `changed_risk_players=0`. La derivación de participación solo pedía
la clave de equipo entera, y un bootstrap que ha pasado por JSON las lleva como
cadenas: los 282 jugadores caían a `missing_official_fixtures` y conservaban el
riesgo de estado. Es decir, el defecto que el slice existe para quitar,
reinstalado en silencio donde el bootstrap se cachea o se transporta. Los tests
unitarios no podían verlo: construyen el mapa con claves enteras.

**2 · La expectativa estaba peor escrita que el código.** Con el arreglo, 221
jugadores cambiaron y la regla falló por una sola cláusula: Haaland 13 → 12. La
inspección que la propia regla exige no encontró ningún segundo cambio — su
puntuación es idéntica (65.1, riesgo 0.0) y lo que se movió fue Isidor, al 27 %
de participación, cayendo nueve puestos. La cláusula mezclaba su **puntuación**,
que el mecanismo sí fija, con su **puesto**, que depende de terceros. Detalle en
`2026-09-04-slice3-participation-measurement.md`.

**3 · Dos lanes correctos por separado se estropeaban juntos.** Esto solo se ve
mirando la lista entera con ojos de producto, que es para lo que existe la
puerta final. E acortó la lista a cinco más hipster; F ancla una nota al jugador
cuyos factores contradicen su puesto. Contra los datos congelados de la GW3,
**Haaland cae al puesto 8, queda fuera de los cinco mostrados, y la nota escrita
justamente para evitar esa lectura no se renderizaba en ninguna parte.**

Arreglado surfaciendo bajo «Conviene saber» la fila cortada de mayor rango que
lleva nota. No añade ningún umbral nuevo: reutiliza la regla de la propia nota.

## Cómo responde hoy la pregunta que originó el encargo

    B) Mejores candidatos globales:
    1. B.Fernandes (MUN, MID) [seg] 82.2 (jugó 180 de 180 minutos posibles,
       2 titularidades · lanza los penaltis)
    2. Cherki (MCI, MID) [baj] 81.67 (jugó 108 de 180 minutos posibles,
       1 titularidad)
    3. Hinshelwood (BHA, MID) [evit] 78.5 (jugó 63 de 180 minutos posibles,
       1 titularidad)
    4. De Cuyper (BHA, DEF) [seg] 76.77 (jugó 167 de 180, 2 titularidades)
    5. Gakpo (LIV, MID) [seg] 73.08 (… · penaltis, 3º en la lista)
    Hipster: 7. Lewis-Potter (BRE, MID) 71.12 — 2.0 % de propiedad
    Conviene saber: 8. Haaland (MCI, FWD) 71.1 (jugó 180 de 180 minutos
       posibles, 2 titularidades · lanza los penaltis)
    Sobre Haaland: Juega todos los minutos y lanza los penaltis, y aun así
       puntúa por debajo: lo que más mueve la puntuación es la forma reciente,
       no el minutaje.

Un defensa entra cuarto y un portero llega al doce, ambos con su posición
visible. Ninguno de ellos sube con participación parcial, que era el riesgo
concreto que había que vigilar al fusionar.

## Lo que sigue vivo — no se cerró y no se disimuló

- **Haaland sigue octavo.** Reparar los minutos nunca iba a subirlo: su
  distorsión es `form`, que son puntos por aparición y además topados. Eso es
  **i59** y exige backtest, no una corazonada. Lo que evita hoy la conclusión
  equivocada es que los factores se vean, no que el número cambie.
- **La sonda de i52 no se ha corrido.** Hace llamadas de pago contra un
  proveedor en vivo; esa es una decisión del dueño. Su regla está escrita y
  todas sus ramas verificadas sin gastar un céntimo.
- **Hinshelwood sale tercero con tier `evitar` y el 35 % de los minutos.** El
  factor se ve, así que no engaña, pero un `evitar` en el podio es material para
  **i54**, que ya iba a revisar qué significan los tiers.
- **`fixture_outlook` con `current_gw` desconocido** recorre ahora las jornadas
  más tempranas disponibles, que desde el Slice 3 incluyen las pasadas. Solo
  ocurre a final de temporada o sin datos; anotado, no arreglado.

## Verde, y de qué

Suites por paquete sobre el checkout de integración: **fpl-grounded-assistant
1598**, **fpl-tool-contract 98**, **fpl-api-client 47**, **fpl-captain-engine
103**, **fpl-pipeline 6**, **fpl-ui 503**, y el resto en verde.

`football-intelligence` (29 fallos) y `sportmonks-client` (2) fallan también
**sobre `origin/main` sin ninguno de estos cambios**, con recuentos idénticos, y
este trabajo no toca ninguno de los dos paquetes. Son de entorno (parquet y
directorio temporal), no de este encargo.

Y como siempre: un recuento local no dice nada sobre CI, en ninguna dirección.
Nada de esto está publicado, así que CI todavía no ha opinado.
