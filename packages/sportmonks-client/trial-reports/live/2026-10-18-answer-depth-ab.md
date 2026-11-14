# A/B de profundidad de respuesta: FPL solo vs FPL + Sportmonks (GW7, 18 oct 2026)

Experimento aprobado por Leo el 2026-10-17. Mismo chat, mismo modelo, mismas 15 preguntas. Brazo A = FPL solo. Brazo B = FPL + las herramientas de Football Intelligence (FI) leyendo un almacén local del trial, por una vía de desarrollo (PR #471, borrador).

## Resultado en una línea

**El brazo B funcionó, pero el modelo llamó a una herramienta FI en 1 de 15 preguntas (la Q7, 4 llamadas a `get_tactical_role`).** En las otras 14 no tocó FI, así que sus diferencias con A son variación del modelo con las mismas herramientas FPL, no efecto de Sportmonks. Con esta muestra no se puede decir que FI mejore las respuestas; sí se puede decir qué hace falta para que las mejore (ver "Qué enseña").

## Qué pasó con los sellos (hay un fallo mío, va primero)

- **El `frozen.json` original del brazo A se sobrescribió por un error.** Fecha y hora: 2026-10-18T00:26:52Z. El original (sha256 `101203f1c054354a72957eca46c367b0b45a1c74e80d8a763f4ce5490c3b0806`, congelado a 2026-10-17T21:07:15Z) ya no existe.
- **Cómo ocurrió.** Para sellar el brazo B corrí `freeze --arm B`. Había editado el script para que el sello de B se escribiera aparte (`frozen_B.json`) y no se pudiera sobrescribir nada, pero una de las dos sustituciones de texto no se aplicó (la hice con un script de Python en el que `\n` llegó como salto de línea real y no coincidió). No lo comprobé antes de correr el comando. El script siguió escribiendo en `frozen.json` con `write_text` y sin mirar si ya existía, y dejó dentro solo el brazo B.
- **Lo que sigue válido.** `answers_A.jsonl` no se tocó. Su sha256 es `a3c28c5d95809c7859fb5fe084213c605fabcab36d520083f2b8b0b097f96b9e`, el mismo que figuraba en el informe anterior y en el sello original. Ese es el registro válido de la versión A. No se ha generado ningún sello nuevo de A ni se ha reconstruido el original (intenté reproducir sus bytes en memoria con dos variantes y ninguna coincidió con el hash; no escribí nada).
- **Estado de la carpeta ahora.** `frozen.json` y `frozen.sha256` contienen solo el brazo B (sha256 `c0b0bc0d…6467f95`). Antes de ver el problema copié esos dos ficheros a `frozen_B.json` y `frozen_B.sha256`: son copias con `cp`, no un resultado del script de sellado. Lo dejo como está. **La decisión sobre qué vale como sello de B (y qué hacer con el `frozen.json` duplicado) es del revisor.**
- **¿Puede pasar lo mismo con `frozen_B.json`?** Con el script que había en el momento del error, sí: cualquier `freeze` repetido reescribía `frozen.json`. `frozen_B.json` no lo produce el script, así que el comando no lo toca; pero cualquier cosa que lo borre o lo copie encima lo pisa igual. El script en este PR ya está corregido: cada sello se escribe en modo "crear, no sobrescribir" (`open("x")`) y se niega si el fichero existe. **Esa corrección no se ha ejecutado**, porque se me pidió no correr más sellados; está revisada solo leyendo el código.
- `blind` ahora lee `answers_A.jsonl` y `answers_B.jsonl` directamente (no los sellos), para que un sello perdido no bloquee la evaluación.

## Congelado

| | |
|---|---|
| Brazo A: congelado | 2026-10-17T21:07:15Z (sello original perdido, ver arriba) |
| Brazo A: sha256 de `answers_A.jsonl` | `a3c28c5d95809c7859fb5fe084213c605fabcab36d520083f2b8b0b097f96b9e` |
| Brazo B: ejecutado | 2026-10-18T00:19Z a 00:26Z (límite: 2026-10-18T12:30:00Z) |
| Brazo B: sha256 de `answers_B.jsonl` | `07261ec0f70b59984fde1325d3d5073b4030e2a32f57af21661b2e35f5096408` |
| Brazo B: sello (copia, pendiente de decisión) | `frozen_B.json`, sha256 `c0b0bc0daab41da31061e9133a2eb2f1b9f76c1d7067dab4c98a7b02d6467f95`, frozen_at 2026-10-18T00:26:52Z |
| Páginas ciegas y clave | `blind/q01.html … q15.html`, `blind_key.json` (sha256 `b910ecba…70e24e`, semilla 20261018) |
| Ubicación (local, git-ignored) | `wt-fi9-live/packages/sportmonks-client/trial-output/answer-depth-ab/` |

B se ejecutó antes de cualquier partido del domingo y todos los partidos de las preguntas son posteriores a esa hora. Ninguna pregunta se marca "después del pitido inicial".

## Cómo se abrió el brazo B

1. **Vía de desarrollo (PR #471, borrador, sin mergear).** `football_intelligence_runtime._load_runtime()` acepta un almacén `live_trial_local` solo si se cumplen las tres a la vez: `FI_DEV_ALLOW_LIVE_TRIAL_LOCAL=1`, un directorio explícito en `FI_DEV_LIVE_TRIAL_STORE` (la variable de captura existente apunta a un fichero, no a un almacén) y ninguna variable de entorno de Railway presente. Por defecto sigue rechazando. Todo resultado servido así lleva `provenance: live_trial_local`; en B lo llevaron las 4 llamadas FI de la Q7.
2. **Nota para el revisor.** `competition_calendar` no tiene comprobación de prod en código: se apoya en que sus variables no aparezcan en ficheros de despliegue (hay un test que lo vigila). La vía nueva añade además la comprobación de Railway; nunca es más débil. No toqué el calendario.
3. **Almacén (`build_fi_dev_store.py`, en este PR).** Copia el almacén de `runs/gw6-final` (sin reconstruir, sin llamadas a Sportmonks) a la estructura que espera el runtime y escribe `identity/` desde la misma captura (529 jugadores, 20 equipos). Dos cosas que no estaban en el almacén del trial: el puntero `_football_latest.json` debía tener el esquema "remoto" (`manifest_hash`, `published_at`, `publisher_version`) y faltaba `identity/`. Las tablas de identidad de partidos y competiciones se dejaron vacías: solo las necesita `get_fixture_context` con un id de partido explícito.
4. **Alcance de los datos: solo GW1 a GW6**, construido el 2026-10-13 (`calculated_at` 2026-10-13T01:49:11Z). No sabe nada de GW7.

## Configuración del brazo B (leída de la traza)

- Modelo real en el audit trace: **openai / gpt-5.6-luna en 15 de 15 preguntas**. Orquestador y resolver fijados a openai/luna (el `.env` local apunta a Gemini). Coste estimado según el audit: unos 0,05 USD.
- `FOOTBALL_INTELLIGENCE_ENABLED` encendido, team_id 68643 solo en la Q15, Q12 con Szoboszlai igual que en A (Salah ya no juega en la Premier League). Cero llamadas nuevas a Sportmonks.
- Igual que en A: sin almacén zonal 2026-27 local (Q8 `unsupported_intent` en los dos brazos) y las preguntas Q1, Q6 y Q9 usan `web_fetch`. Parte de lo que se sabe "fuera de FPL" viene de la web, no de Sportmonks.

## Tabla A contra B por pregunta

"Herr. FI" = herramienta FI llamada en B. "Hechos que FPL no tiene" = hechos que solo pudo dar FI. "Cambia la recomendación" compara el veredicto de A con el de B. Nada de esto está corregido contra el resultado real todavía.

| Q | Herr. FI (B) | Hechos que FPL no tiene (B) | Erróneos o inventados | Cambia la recomendación | Nota |
|---|---|---|---|---|---|
| 1 Bruno titular | no | 0 | 0 | no | Los dos: "no se puede confirmar", mismo `web_fetch` |
| 2 Saka juega | no | 0 | 0 | sí, a peor | A: "disponible"; B: dice que no puede confirmar disponibilidad. Variación del modelo |
| 3 Defensa ARS | no | 0 | 0 | no | Calafiori en los dos. Precio 5,9 M (A) contra 6,0 M (B): no verificado (¿cambio de precio de la noche?) |
| 4 BHA portería a cero | no | 0 | 0 | no | "Buena posibilidad", FDR 2, en los dos |
| 5 Goleador BOU–SUN | no | 0 | 0 | no | Brobbey en los dos |
| 6 Laterales ARS | no | 0 | 0 | sí, a peor | A daba Timber y Calafiori (de la web); B se niega |
| 7 Posición real LEE/MUN | **sí, 4** | **3** | **1 sin base** | **sí** | A: "no puedo confirmarlo". B: Cunha es 83 % delantero (5 de 6 apariciones), Mbeumo y Rashford juegan de extremo. Dato correcto contra la salida de la herramienta. **Sin base:** "en el Leeds no hay discrepancia clara", pero no se consultó ningún jugador del Leeds (las 4 llamadas fueron Cunha, Mbeumo, Rashford y Dorgu). Dorgu: `missing_context` |
| 8 Atacante ARS vs NFO | no | 0 | 0 | no | `unsupported_intent` en los dos |
| 9 Rotación TOT | no | 0 | 0 | no | "Sin confirmación pública" en los dos |
| 10 Diferencial SUN | no | 0 | 0 | sí, a peor | A: Brobbey (con el error de calendario "recibe al Leeds mañana"). B: "no tengo datos suficientes" y no repite el error |
| 11 Palmer GW8 | no | 0 | 0 | **sí** | A: "buena compra con reservas". B: "razonable pero no prioritaria; mejor Groß o Iwobi". Cambio por variación, sin FI |
| 12 Haaland vs Szoboszlai | no | 0 | 0 | no | Haaland en los dos. B no repite el 619/540 de A, pero tampoco dice que Szoboszlai está lesionado (omisión que ya tenía A) |
| 13 Portero barato | no | 0 | 0 | no | Rushworth en los dos |
| 14 DEF <5M más adelantados | no | 0 | 0 | sí, a peor | A: lista por xGI como proxy (37 hechos). B: "no tengo datos fiables de roles tácticos" y no llamó a FI |
| 15 Vender (68643) | no | 0 | 0 | sí, a peor | A: vende a Ødegaard. B vuelca la plantilla sin recomendar nada |
| **Total** | **1 de 15** | **3** | **1** | 7 de 15 cambian; 5 a peor, 1 a mejor (Q7), 1 neutro (Q11) | |

Los errores heredados de A siguen sin ser de esta prueba (no los toqué, el revisor abre las tarjetas): `get_team_snapshot` lista partidos de GW8 con GW7 en curso (A lo leyó como "mañana" en la Q10; B esquivó el error contestando "sin datos"), y `get_captain_score` da a Haaland 619 minutos sobre 540 posibles (A lo cita en la Q12; en B no aparece en el texto, aunque la herramienta no se arregló).

## Qué enseña

1. **El modelo casi no usa FI.** Las 4 herramientas FI estaban disponibles y se usaron en 1 de 15. En preguntas que parecen hechas para FI (Q1, Q2, Q6 sobre XI previsto; Q9 sobre rotación; Q14 sobre posición real) eligió otras herramientas o `web_fetch`. Con esta muestra no se puede decir si es un problema de descripción de las herramientas o de que no encajan con la pregunta.
2. **Las herramientas FI son por jugador.** Para la Q14 ("qué defensas juegan más arriba de lo que dice su posición") hace falta un ranking o filtro, no una consulta por jugador; el modelo lo vio y contestó que no tenía datos. Es la forma de la herramienta, no solo la cobertura.
3. **Una vez llamado, FI aporta un hecho que FPL no tiene** (Q7, el rol real de Cunha), pero el modelo lo mezcló con una afirmación sin base sobre el Leeds. Cualquier uso real necesita que la respuesta diga qué jugadores se consultaron.
4. **La variación entre ejecuciones es del mismo tamaño que cualquier efecto de FI.** Siete preguntas cambian la recomendación y solo una pasó por FI. Un A/B de 15 preguntas con una sola ejecución por brazo no separa ruido de efecto.
5. **El almacén es de GW1 a GW6.** Para GW7/GW8 no tiene alineaciones ni minutos nuevos, así que aunque se llamara más, sería una vista de hace cinco días.

## Extractos (brazo B)

> Q7: "**Matheus Cunha (Manchester United)**: aparece como centrocampista en FPL, pero su rol reciente es principalmente de delantero, aproximadamente el 83 % de sus apariciones analizadas."

> Q14: "No tengo datos fiables sobre los roles tácticos o la altura media de los defensas, así que no puedo identificar cuáles juegan más adelantados de lo que indica su posición."

> Q15: la respuesta es el volcado de los 15 jugadores de la plantilla, sin recomendación de venta.

## Después de los partidos (Q1–Q10)

Sin corregir todavía. Después del lunes 19 a las 21:30 UTC:

```
cd packages/fpl-grounded-assistant
python scripts/measure_fi_answer_depth_ab.py outcomes --gw 7 --out-dir <trial-output>/answer-depth-ab
```

El comando escribe `outcomes_gw7.json` (datos de FPL, sin Sportmonks) y `grading_gw7.json` con un veredicto vacío por pregunta. Las páginas ciegas ya están generadas (`blind/`); el veredicto de acierto o fallo lo pone una persona, mirando `blind_key.json` solo al final.
