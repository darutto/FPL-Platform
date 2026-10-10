# i152 — mini-canchita en la sección «Zonas» de PlayerCard

Solo UI, sin datos nuevos (`zones[].share` y `fixtures[].matches` ya llegan en `player_snapshot.zonal`). **No fusionar hasta que Leo cierre el gate de i148 en prod.**

## Qué cambia
- `PitchGeometry.tsx` (nuevo): la geometría del área (contorno, área pequeña, portería, guías de tercios, punto y arco) extraída **tal cual** de `DefensiveZonesCard`, junto con `ZONE_X/ZONE_WIDTH/ZONE_CENTER_X`.
- `PlayerZonesPitch.tsx` (nuevo): dibuja las **seis** zonas del motor. El SVG original solo cubría los tres tercios del área; aquí se añade debajo la franja frontal (borde del área) con los mismos tercios, así caben las seis (Área/Frontal × izq/centro/der). Ninguna zona queda fuera.
- `pitchCell` (en `lib/defensive-zones.ts`): clave del motor → celda (fila área/frontal, columna izq/centro/der); claves desconocidas → `null` y no se dibujan.
- `PlayerZonasSection.tsx`: la canchita (116 px) a la izquierda de los chips; una línea de leyenda («Turquesa: coincide con la zona débil de un rival favorable») solo si hay algún cruce favorable.

## Reglas
- Turquesa = la zona del jugador coincide con `matches` de un partido `favorable`; gris neutro = zona del jugador sin coincidencia; nada en rojo; las zonas que no son del jugador no se pintan.
- Sin zonas (o ninguna colocable) → sin canchita (ni su contenedor). Sin favorables → solo las zonas del jugador, todas neutras. `matches` de partidos no favorables nunca resaltan.
- `share` (0–1) solo gradúa el tono; el texto de cada celda usa la única conversión `sharePercent`.
- `aria-label`: «Área centro: 59% de su xG (coincide con un cruce favorable) · Frontal der: 26% de su xG».

## Verificación
- **DefensiveZonesCard idéntica:** `__tests__/defensive-zones-markup.test.tsx` (3 snapshots de `innerHTML`: zonas mixtas, todas medias, todas oportunidad con procedencia). El snapshot se grabó **antes** de extraer la geometría y pasa sin cambios después.
- `player-zones-pitch.test.tsx` (18 tests): las seis zonas distintas y bien colocadas, solo las del jugador, con y sin coincidencias, sin favorables, coincidencia en zona ajena, matches de partido no favorable, sin zonas, zonas no colocables, aria, % una sola vez, sin rojo, graduación del tono, integración en `PlayerCard`.
- Mutaciones (`artifacts/i152-mutation-report.txt`): 15 mutantes (fila/columna intercambiadas, no favorables resaltan, colores, guardas de «sin zonas»/«no colocable», % sin convertir, aria sin coincidencia o sin porcentajes, leyenda siempre, contenedor sin guarda, geometría compartida alterada ×2, tono sin escala): **15 muertos, 0 vivos**.
- `tsc --noEmit` limpio; jest completo 49 suites / 676 tests / 3 snapshots en verde.
- Capturas (misma receta de harness que `2026-10-09-b10-ui-report.md`, puerto 4317; móvil = iframe de 390 px reales):
  - `i152-pitch-palmer-prod-{desktop,mobile}.png`: payload real de prod de Palmer (`b10-prod-ask-palmer.json`): una zona, «Área centro 59 %», coincide con J8 Tottenham → turquesa.
  - `i152-pitch-three-zones-synthetic-{desktop,mobile}.png`: **sintético** (el payload de Palmer con tres zonas coherentes —34 %, 27 %, 26 %: suman 87 %— y dos coincidencias, una de ellas frontal); no son datos reales.

## Salvedades
- Con el payload real hoy el jugador tiene una sola zona, así que la canchita luce sobria. El backend solo lista zonas con ≥ 25 % del xG sin penalti, así que en datos reales caben como mucho 4 zonas a la vez (y nunca suman más de 100 %); las seis celdas están cubiertas por los tests, no por una captura, porque una captura con seis zonas visibles no sería coherente con los datos.
- Ajuste tras la revisión: el porcentaje de la celda del área baja 24 unidades del centro (antes 9) para no quedar pegado a la portería.
- La canchita es pequeña a propósito (116 px): los porcentajes van dentro de las celdas y los chips al lado repiten los números.
