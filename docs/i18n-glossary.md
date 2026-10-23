# i18n glossary (ES ↔ EN)

Single reference for the English version. Every PR that adds or translates user-visible text checks its wording against this file. Spanish stays the default and its wording does not change.

## Rules
- **British English** spelling: favourable, defence, colour, programme.
- **British football terms**: gameweek, fixture, clean sheet, differential, captaincy.
- **Chip names are always English**, in both locales and in model output: Wildcard, Bench Boost, Free Hit, Triple Captain. Never translate them (comodín, ficha libre, impulso de banca, triple capitán).
- **Positive, opportunity framing** in both languages (see `opportunity_framing.py`). No "must sell / urgent" wording.
- **Less is more**: the shortest label that is still clear (UCL, not Champions League, where it fits).
- Spanish uses *tuteo* (tú), never voseo, in product copy.
- Descriptor: EN "your FPL assistant manager" / ES "tu asistente técnico".
- Unchanged in both locales: BF score, FDR, xG, xGI, xA, GW (as an abbreviation in EN), prices as `£x.xm`, player and team names.

## Terms
| Spanish | English | Notes |
|---|---|---|
| Jornada | Gameweek | Abbreviation: ES `J12`, EN `GW12`. Never "round" or "matchweek". |
| Partido | Match (in prose), Fixture (in lists and calendar) | |
| Calendario | Fixtures | Panel and heading label. |
| Racha favorable | Favourable run | |
| Dificultad ofensiva / defensiva | Attack difficulty / Defence difficulty | FDR keeps its acronym. |
| Portería a cero | Clean sheet | |
| Diferencial | Differential | |
| Capitanía / Capitán | Captaincy / Captain | |
| Vice-capitán | Vice-captain | |
| Fichajes / Transferencia | Transfers / Transfer | A single suggestion is a "transfer". |
| Fichar | Bring in | Avoid "buy". |
| Plantilla | Squad | |
| Banca | Bench | |
| Once inicial | Starting XI | |
| Lesionados / Lesiones | Injuries | Also "injury news". |
| Dudas | Doubts | Status label; FPL's own label is "Doubtful". |
| Forma | Form | |
| Minutos | Minutes | |
| Clasificación / Ranking | Rankings | |
| Más seleccionados | Most selected | |
| Contribución defensiva | Defensive contribution | |
| Penaltis / Tiros libres / Córners | Penalties / Free kicks / Corners | Set-piece takers. |
| Doble jornada | Double gameweek (DGW) | |
| Jornada en blanco | Blank gameweek (BGW) | |
| Gratis | Free | Quota/tier labels. |
| Día / Mes | Day / Month | Quota pill. |
| Hoy | Today | |
| Mejorar plan | Upgrade | |
| Asistente técnico | Assistant manager | |
| Veredicto | Verdict | |
| Evidencia / Fuentes / Confianza | Evidence / Sources / Confidence | |
| Pensando… | Thinking… | |
| Enviar | Send | |

## Commands (EN canonical names in EN mode; Spanish stays accepted in both)
| Spanish | English |
|---|---|
| /capitan | /captain |
| /comparar | /compare |
| /transferencia | /transfer |
| /calendarios | /fixtures |
| /diferenciales | /differentials |
| /chips | /chips |
| /clasificacion | /rankings |
| @lesionados | @injuries |
| @forma | @form |
| @puntos | @points |
| @minutos | @minutes |
| @populares | @popular |

## Patreon tiers
Keep the Patreon proper name and add a short English descriptor so it matches checkout, e.g. "Tribuna · Supporter". The descriptors are decided in the subscribe-page slice (S6).

## Out of scope
- World Cup UI strings.
- Jev router example questions (shadow only).
