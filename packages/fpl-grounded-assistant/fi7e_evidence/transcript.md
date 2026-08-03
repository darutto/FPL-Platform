# FI-7e silent recording action log

The recording has no audio. Each scene is a whole three-second capture segment; the final container is 21.0 seconds at 10 frames per second. Payload hashes below are canonical JSON hashes from `manifest.json`.

| Time | Scenario and operator action | Visible assertion | Machine link |
|---|---|---|---|
| 00:00–00:03 | A — submit `captain score for Saka` with FI OFF | frozen captain recommendation; no evidence heading | `A-off-desktop.png`; `2c0f06dbb1220364a812b6727cd38df29875700cc4b98d07ab0df9aed8c35959` |
| 00:03–00:06 | B — submit `player intelligence for Saka`, desktop | ordered evidence; confidence and source labels; no internal IDs | `B-native-desktop.png`; `39b19538ee76915fac6a07612d87a40365f8df0006740a719878e69c30114075` |
| 00:06–00:09 | B — render the same payload at 390×844 | same items and ordering in one responsive column | `B-native-mobile.png`; same B hash |
| 00:09–00:12 | C — submit `compare Saka and Palmer` with FI ON | real comparison remains Saka then Palmer; evidence is additive | `C-compare-desktop.png`; `4110dd30ec5687184daf382125c0d8976b3d740483bd6bfafcce49e6a24b51c0` |
| 00:12–00:15 | D — submit the frozen multi-intent prompt | child 0 owns FI evidence; child 1 is unchanged; parent has no evidence block | `D-multi-desktop.png`; `48f697e196de23acc6cc3d21f9bc38b69aaa63cffe061496495f4b2fa34be895` |
| 00:15–00:18 | E — render the stored response through the same UI components | replay matches B with no runtime reevaluation | `E-replay-desktop.png`; B/E common hash |
| 00:18–00:21 | F — show containment outputs | primary response remains visible and no evidence is fabricated | `F-failure-desktop.png`; F1 `2c0f06db...`; F2 `314eba4d...` |

F1 and F2 are separate machine assertions in `backend-trace.json` and focused tests: the shared final scene does not claim one failure seam proves the other. Screenshots were captured by a disposable component-level route that mounted the unchanged FI-7d response/evidence components against the loopback fixture server at the required desktop and mobile viewports. The production middleware guard remained intact; no authentication bypass or credential was used.
