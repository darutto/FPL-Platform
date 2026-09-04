# Slice 3 — el antes/después de la participación, y las dos cosas que encontró

**Fecha:** 2026-09-04 · **Instrumento:** `measure_captaincy_scoring_inputs_with_fixtures.py`
(medición) + regla congelada de `measure_captaincy_scoring_inputs.py compare`
**Snapshot:** `captaincy-scoring-bootstrap-complete-fixtures-2026-09-03.json`
SHA-256 `2f2d43540f3b30b7de92569f914cfd87340854372dd6bc8488cd0d0a9720bd33` ·
282 filas del pool derivado.

Ninguno de los dos scripts se editó después de su corrida pre. Esta nota es el
registro de la inspección; la regla queda tal y como se escribió.

## Primera corrida — el instrumento encontró un defecto, no un resultado

`VERDICT=STOP_AND_INVESTIGATE`, `changed_risk_players=0`. Cero, no pocos: el
post salió idéntico al pre.

La causa no estaba en la derivación sino en su búsqueda. Un bootstrap que ha
pasado por JSON lleva las claves de equipo como cadenas, y la ruta de
participación solo pedía la entera. Los 282 jugadores caían a
`missing_official_fixtures` y conservaban el riesgo de estado — exactamente el
defecto que este slice existe para quitar, reinstalado en silencio en cualquier
sitio donde el bootstrap se cachea o se transporta.

`fixture_outlook.py:305` ya resolvía las dos formas de clave desde antes. La
derivación nueva no. Arreglado y fijado con un test que teclea las fixtures como
cadenas y exige que la participación resuelva en vez de degradar.

**Lo que esto dice del instrumento:** un `N passed` verde no lo habría visto —
los tests unitarios construyen el mapa con claves enteras. Lo vio la medición
contra el snapshot real. Es el mismo patrón que ya está anotado en el repo: la
relajación o el descuido de un matcher convierte un fallo visible en una
respuesta fluida y equivocada.

## Segunda corrida — el cambio real

`changed_risk_players=221`, `VERDICT=STOP_AND_INVESTIGATE` por una sola
cláusula: `Haaland rank changed 13->12`.

Las tres cláusulas sustantivas se cumplen:

| cláusula de la regla | resultado |
|---|---|
| sube el riesgo de al menos uno, y a todos esos les baja la puntuación | 221 subieron, a los 221 les bajó |
| a quien no le cambia el riesgo, no le cambia la puntuación | 61 sin cambio, puntuación idéntica |
| a nadie le baja el riesgo | 0 |
| Haaland conserva el puesto | **falla: 13 → 12** |

### La inspección que pide la regla

La regla dice, literalmente, que un cambio de puesto de Haaland obliga a parar y
buscar «un segundo cambio no intencionado». Se buscó. No lo hay:

- La puntuación de Haaland es **idéntica**: 65.1 antes, 65.1 después, riesgo 0.0
  en ambos lados. Haaland no se movió.
- Se movió el campo a su alrededor. **Isidor** cayó del puesto 10 al 19 (riesgo
  72.8: jugó poco más de una cuarta parte de los minutos disponibles de su
  equipo). Ese descenso, y solo ese, es el que sube a Haaland un puesto.
- La inversión que motivó el encargo se corrigió: **Cherki** (60 % de los
  minutos, 1 titularidad de 2) baja del 2 al 3 y deja de ir por delante de
  jugadores al 100 %.

### Lo que estaba mal escrito era la expectativa, no el código

La expectativa pre-registrada mezcló dos cosas distintas: que **la puntuación**
de Haaland no se moviera —que es lo que el mecanismo garantiza, y se cumple— y
que su **puesto** no se moviera, que depende de terceros. Un jugador al 100 % de
participación sube de puesto exactamente cuando alguien por encima con
participación parcial cae; que es el efecto buscado, no un efecto colateral.

Queda anotado para i59: una regla de decisión sobre un ranking debe fijarse
sobre la magnitud propia del sujeto, no sobre su posición relativa, salvo que el
movimiento de los demás sea justamente lo que se quiere prohibir.

## Lo que este slice NO hizo

Haaland sigue **fuera del podio** (puesto 12 de 282). Reparar los minutos no lo
sube, y nunca se esperó que lo hiciera: su distorsión dominante es `form`, que
son puntos por aparición y además topados. Eso es i59 y exige backtest.

Por tanto **el problema de producto sigue vivo después de este slice**. Lo que
lo resuelve es enseñar los factores (Slice 4): que quien pregunta por Haaland
lea «100 % de los minutos, penaltero, mismo partido que el que va por encima» y
no solo dos cifras.
