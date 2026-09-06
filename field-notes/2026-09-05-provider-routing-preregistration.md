# Pre-registro: ¿la elección de proveedor cambia el enrutado de herramientas?

Escrito el 2026-09-05 **antes** de lanzar las corridas de 60 reps, y después de
ver los pilotos de 20. Esa asimetría es justo la razón de escribirlo: la
hipótesis nació de los pilotos, así que el criterio tiene que fijarse ahora o el
resultado no vale.

## Por qué existe este documento

Los pilotos dieron 7/20 (35%) fuera de objetivo en `gpt-5.6-luna` y 3/20 (15%)
en `gemini-3.8-flash`. Fisher exacto bilateral: **p = 0,273**. Es compatible con
que no haya diferencia. Subir reps después de ver eso es parada opcional, y sin
regla previa cualquier número posterior se puede leer como uno quiera.

## Montaje

* Pregunta (exacta): `¿A quién debería dar el brazalete?`
* Bootstrap congelado, `sha256 = 4cbb9fa18a5852c73a54fbe24a03b34e0c33ae5b3c549171cbcb02568d8b2aae`
  (el mismo de los dos pilotos; se verifica en cada fila).
* Brazos: `openai/gpt-5.6-luna` y `gemini/gemini-3.8-flash`.
* **n = 60 por brazo, corridas frescas.**
* Controles de muestreo: los de producción, vía `measure_tool_routing.run_one`.

**Los 20 pilotos NO se agrupan con estas corridas.** Generaron la hipótesis;
reusarlos para probarla es contar la misma evidencia dos veces. Quedan como
observación previa y se reportan aparte.

## Métrica primaria y regla de decisión

Métrica primaria: **tasa fuera de objetivo** = proporción de turnos cuya
herramienta elegida no es `rank_captain_candidates`.

Contraste: Fisher exacto bilateral sobre las dos tasas, alfa = 0,05.

* **p < 0,05 y Gemini menor**: el proveedor influye en el enrutado.
  `gemini-3.8-flash` pasa a ser candidato en este eje. No lo convierte en
  ganador: todavía tiene que pasar el criterio de coste.
* **p < 0,05 y luna menor**: el proveedor influye a favor del modelo que ya
  corre en producción. No se cambia de modelo por este eje.
* **p >= 0,05**: no hay diferencia distinguible con este n. Se trata el atractor
  de jornada como defecto de superficie y se arregla el prompt o el conjunto de
  herramientas. **No se elige modelo sobre esta base.**
* Cualquier excepción del arnés en cualquiera de los dos brazos: **INVÁLIDA**,
  con independencia de los conteos.

**Se analiza una sola vez, al terminar los 120 turnos.** No se mira a mitad y no
se amplía n si el resultado queda cerca del umbral.

### Lo que ninguna rama de la regla cambia

Las dos tasas son mayores que cero. La superficie hay que arreglarla igual; lo
único que está en juego aquí es si además hay una diferencia de proveedor.

## Métricas secundarias (se reportan, no deciden)

1. Candidatos emitidos por el modelo — réplica de i52. Los pilotos dieron 0 de
   30 turnos de ranking en dos familias de modelos.
2. Tasa de entrada a la ronda de síntesis. En los pilotos, luna 11/20 y Gemini
   2/20: los cero fallbacks de síntesis vacía de Gemini están confundidos con
   que casi no pasa por ahí, y con n=60 se puede separar.
3. Tokens y coste.

## Aviso sobre los costes registrados

`measure_tool_routing.cost_usd` cobra dos veces la parte cacheada en OpenAI:
`input_tokens` ya incluye los cacheados y la fórmula les suma encima la tarifa
de caché. Los dólares de los brazos OpenAI están **sobreestimados** (piloto de
luna: $0,0796 reportado contra $0,0194 reales, 4,1x). Gemini no reporta caché,
así que su cifra es correcta. El defecto no toca la métrica primaria, que se
cuenta en herramientas y no en dólares.

---

# Addendum: réplica del efecto de PR #210 (pre-registrado 2026-09-05, antes de correr)

El brazo de luna con #210 dio 1/60 fuera de objetivo. El piloto sin #210 había
dado 7/20. Esa comparación **no estaba pre-registrada** y las dos corridas están
separadas en el tiempo, así que no sirve como evidencia. Este addendum fija el
criterio antes de la réplica.

## Montaje

* Idéntico al de arriba: misma pregunta, mismo bootstrap
  (`4cbb9fa1...`), controles de producción.
* Brazo único: `openai/gpt-5.6-luna` sobre el commit **`1b5dfd4`**, que es
  exactamente el código en el que corrió el piloto — sin PR #210.
* **n = 60.** Se contrasta contra el brazo ya medido de luna con #210 (1/60),
  que no se vuelve a correr.
* Worktree dedicado. El script de ese commit no tiene `--provider/--model`, y no
  hace falta: sus valores fijados ya son `openai`/`gpt-5.6-luna`.

**El piloto de 20 no se agrupa.** Generó la hipótesis. Se reporta aparte.

## Métrica primaria y regla de decisión

Misma métrica: tasa fuera de objetivo. Fisher exacto bilateral, alfa = 0,05,
contra 1/60.

* **p < 0,05 y la tasa sin #210 es mayor**: #210 redujo el atractor de jornada.
  i38 se cierra como resuelto, citando esta medición.
* **p >= 0,05**: el piloto de 7/20 no se replica. i38 sigue abierta y el 35%
  pasa a considerarse ruido de una corrida, no un defecto medido. En ese caso
  hay que revisar también qué más cambió entre las dos corridas.
* **p < 0,05 con la tasa sin #210 menor**: resultado incoherente con el piloto.
  No se cierra nada; se investiga el arnés antes que el producto.
* Cualquier excepción del arnés: **INVÁLIDA**.

Se analiza una sola vez, al terminar los 60 turnos.

## Lo que esta réplica NO controla

El tiempo. Las dos corridas ocurren con horas de diferencia y contra un
proveedor que no controlamos. Un cambio del lado de OpenAI en esa ventana es
indistinguible del efecto de #210. Es la limitación conocida y aceptada de
medir contra un servicio ajeno; se registra aquí para que nadie la descubra
después leyendo la conclusión.
