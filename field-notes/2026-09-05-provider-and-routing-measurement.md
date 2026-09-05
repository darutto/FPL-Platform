# Medir el proveedor, y descubrir que medía el commit equivocado

2026-09-05. Tres sondas, 240 turnos pagados, ~$2,50. Salieron tres resultados
que no esperaba y un error mío que estuvo horas en pie.

## Resumen

1. **`gemini-3.8-flash` queda descartado como candidato de producción**, por
   enrutado y por coste, contra una regla escrita antes de correr.
2. **PR #210 casi eliminó el atractor de jornada** — el defecto más visible de
   la superficie de capitanía. Réplica pre-registrada en curso.
3. **i52 se cancela por falta de defecto**: el modelo no emite su propia lista
   de candidatos. Cero veces en 106 turnos de ranking.
4. **El coste de las corridas OpenAI estaba inflado 3-4×** por un doble cobro
   de los tokens cacheados.

## El error, primero

El piloto de luna corrió desde un checkout atrasado, sin PR #210. El piloto de
Gemini corrió desde un worktree con #210 dentro. Reporté la diferencia —35%
contra 15% fuera de objetivo— como si fuera **entre proveedores**. No lo era:
comparaba dos versiones del sistema.

Puse la cautela estadística correcta (Fisher p=0,27, no distinguible del azar) y
aun así la conclusión era inválida por una razón distinta y peor: confusión, no
ruido. Un intervalo de confianza no protege de comparar cosas que no son
comparables.

Lo delató que el brazo de luna a n=60 diera 1,7% donde el piloto había dado 35%.
Mismo modelo, misma pregunta, mismo bootstrap: eso no lo explica el muestreo.

**Regla que sale de aquí: una sonda tiene que registrar en qué commit corrió, y
hay que mirarlo antes de comparar dos corridas.** El bootstrap ya se verifica
por SHA en cada fila — el código, no.

## Lo que sí quedó medido

Montaje: pregunta `¿A quién debería dar el brazalete?`, bootstrap congelado
`4cbb9fa1…` verificado en cada fila, controles de producción, 60 repeticiones
por brazo, 0 excepciones del arnés. Regla en
`field-notes/2026-09-05-provider-routing-preregistration.md`, escrita antes.

| | luna | gemini-3.8-flash |
|---|---|---|
| se va a una herramienta de jornada | **1/60 (1,7%)** | 13/60 (21,7%) |
| entra a la ronda de síntesis | 60/60 | 8/60 |
| emite su propia lista de candidatos | 0/59 | 0/47 |
| respuestas vacías de síntesis | 0 | 0 |
| coste real | **$0,105** | $1,969 |

**Fisher exacto bilateral p = 0,00098**, luna menor. Se cumple la rama
pre-registrada: no se cambia de modelo por este eje.

### El coste no es el que dice la tarifa

Por token, Gemini es 3,75× más caro que luna. En la factura de esta carga fue
**19×**. La diferencia entera es la caché: luna reutiliza el 84-89% de su
entrada; **Gemini no reportó un solo token cacheado en 120 turnos**.

Elegir modelo por precio de lista habría errado por un factor de cinco. Para una
carga como esta —prompt de sistema grande y estable, pregunta corta— la tasa de
acierto de caché importa más que la tarifa.

### El atractor de jornada

luna, sin #210: **7/20 (35%)**. Con #210: **1/60 (1,7%)**. Fisher p = 0,00016.

Nadie tocó un prompt de enrutamiento para conseguirlo. Lo que #210 hizo fue
abrir el pool de candidatos y darle a `rank_captain_candidates` algo con que
responder. La lectura que propongo: el modelo no se iba a `get_gameweek_context`
por confusión entre descripciones parecidas, sino porque la herramienta correcta
le devolvía algo pobre. **Se arregló un atractor de enrutamiento mejorando la
herramienta, no la descripción.** Si se sostiene, cambia cómo atacar i40 y el
resto de la matriz de confusión.

#### La réplica, y una corrección de magnitud

60 turnos sobre el commit exacto del piloto (`1b5dfd4`), regla escrita antes:

| | fuera de objetivo |
|---|---|
| sin #210, piloto n=20 | 7/20 (35,0%) |
| **sin #210, réplica n=60** | **9/60 (15,0%)** |
| con #210, n=60 | 1/60 (1,7%) |

**Fisher exacto bilateral p = 0,0166.** Se cumple la rama pre-registrada y i38
queda cerrada.

Pero el efecto es **más pequeño de lo que dijo el piloto**: la mejora real es
15% → 1,7%, no 35% → 1,7%. El 35% fue una muestra corta y desafortunada; el
piloto y la réplica ni siquiera se distinguen entre sí (p = 0,10), así que no
hay contradicción, solo regresión a la media.

Esto es exactamente para lo que servía la cláusula de no agrupar el piloto:
sumarlo habría arrastrado su exageración al resultado final, y habría hecho
parecer que #210 arregló el doble de lo que arregló.

### i52: cancelada por falta de defecto

Cero listas emitidas en 106 turnos de ranking, dos familias de modelos, dos
versiones del código. El veredicto `STOP_AND_REINVESTIGATE` estaba escrito antes
de la primera llamada pagada, y se cumplió.

La obra que esto cancela —descartar la lista del modelo cuando propone jugadores
que el usuario no nombró— **no se aplaza: no hace falta**. La sospecha venía de
dos turnos de producción y no sobrevivió a contarla.

Límite conocido: la pregunta sondeada no menciona jugadores, y los dos turnos
que levantaron la sospecha sí. La sonda que falta es esa.

## El defecto de coste

`measure_tool_routing.cost_usd` cobra dos veces la parte cacheada, y solo en
OpenAI: `input_tokens` de OpenAI ya incluye los cacheados
(`input_tokens_details.cached_tokens` es un subconjunto,
`provider_client.py:1014`), y la fórmula les suma encima la tarifa de caché. En
Anthropic la fórmula es correcta —ahí van aparte, `:976`— y en Gemini es inerte.
**La resta hay que hacerla por proveedor.**

| corrida | reportado | real |
|---|---|---|
| luna n=20 | $0,0796 | $0,0194 |
| luna n=60 | $0,3513 | $0,1052 |
| gemini n=60 | $1,9687 | correcto (caché=0) |

Sesgo conservador —nunca subestima—, así que nadie se quedó corto de
presupuesto. Pero infla justo el brazo que más cachea, y hoy eso torció una
comparación de calidad-por-coste. También infla el $0,9357 registrado en i38.
Encargo pasado al chat de #212.

## Lo que se lleva a las cartas

* [[i52]] entregada: medida y cancelada.
* [[i66]] nueva: Gemini 3.8 Flash evaluado y descartado, con el guion para la
  próxima rotación.
* [[i38]] cerrada por la réplica pre-registrada (p = 0,0166).
* [[i46]] confirmada en vivo: 0 respuestas vacías en 120 turnos.
