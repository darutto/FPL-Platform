"""
FPL question bank for catalog_runner.py.

Each question has:
  - text: the raw Spanish prompt
  - category: broad topic bucket
  - expected_intent: what the router *should* route to, or None if unknown
  - notes: short description of the user need

expected_intent values match INTENT_* constants in dispatcher.py:
  captain_score | rank_candidates | current_gameweek | player_summary |
  player_resolve | compare_players | transfer_advice | chip_advice |
  player_fixture_run | differential_picks | unsupported
"""

QUESTIONS = [
    # ── Already covered — should pass ─────────────────────────────────────────
    {
        "text": "¿a quién debería capitar esta semana?",
        "category": "Captain / Vice-Captain",
        "expected_intent": "rank_candidates",
        "notes": "Generic captaincy ranking — should be handled",
    },
    {
        "text": "dame el ranking de capitanes para esta jornada",
        "category": "Captain / Vice-Captain",
        "expected_intent": "rank_candidates",
        "notes": "Explicit ranking ask — should be handled",
    },
    {
        "text": "¿debería capitar a Haaland?",
        "category": "Captain / Vice-Captain",
        "expected_intent": "captain_score",
        "notes": "Named captain score — should be handled",
    },
    {
        "text": "dame un resumen de Salah",
        "category": "Player Info / Stats",
        "expected_intent": "player_summary",
        "notes": "Basic player summary — should be handled",
    },
    {
        "text": "¿en qué jornada estamos?",
        "category": "Gameweek Info",
        "expected_intent": "current_gameweek",
        "notes": "Current GW — should be handled",
    },
    {
        "text": "¿debería vender a Saka y fichar a Palmer?",
        "category": "Transfer Planning",
        "expected_intent": "transfer_advice",
        "notes": "Named swap transfer — should be handled",
    },
    {
        "text": "¿debería usar el wildcard esta semana?",
        "category": "Chip Strategy",
        "expected_intent": "chip_advice",
        "notes": "Wildcard chip — should be handled",
    },
    {
        "text": "dame los próximos fixtures de Haaland",
        "category": "Fixture Difficulty / Schedule Analysis",
        "expected_intent": "player_fixture_run",
        "notes": "Player fixture run — should be handled",
    },
    {
        "text": "dame picks diferenciales para esta jornada",
        "category": "Player Pick / Start Recommendation",
        "expected_intent": "differential_picks",
        "notes": "Differentials — should be handled",
    },
    {
        "text": "compara a Salah y Haaland",
        "category": "Captain / Vice-Captain",
        "expected_intent": "compare_players",
        "notes": "Direct comparison — should be handled",
    },

    # ── Fixture calendar ───────────────────────────────────────────────────────
    {
        "text": "que equipo tiene el mejor calendario de ahora a la ultima fecha",
        "category": "Fixture Difficulty / Schedule Analysis",
        "expected_intent": None,
        "notes": "Team-level FDR ranking for remaining GWs",
    },
    {
        "text": "¿qué equipo tiene los mejores fixtures que le quedan?",
        "category": "Fixture Difficulty / Schedule Analysis",
        "expected_intent": None,
        "notes": "Variation of season-run-in calendar question",
    },
    {
        "text": "¿qué defensas tienen buen calendario las próximas 5 jornadas?",
        "category": "Fixture Difficulty / Schedule Analysis",
        "expected_intent": None,
        "notes": "Position-filtered fixture run — DEF assets with easy fixtures",
    },
    {
        "text": "¿hay algún equipo con doble jornada próximamente?",
        "category": "Fixture Difficulty / Schedule Analysis",
        "expected_intent": None,
        "notes": "Double gameweek detection",
    },
    {
        "text": "¿qué equipos tienen blank gameweek esta jornada?",
        "category": "Fixture Difficulty / Schedule Analysis",
        "expected_intent": None,
        "notes": "Blank GW detection",
    },

    # ── Recent form / match stats ──────────────────────────────────────────────
    {
        "text": "dame las stats de los ultimos 5 partidos de cherki",
        "category": "Player Info / Stats",
        "expected_intent": "player_summary",
        "notes": "Per-game history — routed to player_summary but data is missing",
    },
    {
        "text": "¿cómo ha estado Salah en los últimos 3 partidos?",
        "category": "Player Info / Stats",
        "expected_intent": None,
        "notes": "Form last N games for named player",
    },
    {
        "text": "¿cuántos puntos ha sacado Palmer en las últimas 4 jornadas?",
        "category": "Player Info / Stats",
        "expected_intent": None,
        "notes": "FPL points history for named player",
    },
    {
        "text": "¿qué jugador ha subido más puntos últimamente?",
        "category": "Player Info / Stats",
        "expected_intent": None,
        "notes": "Form table / in-form players ranking",
    },
    {
        "text": "dame el historial de puntos de Mbeumo esta temporada",
        "category": "Player Info / Stats",
        "expected_intent": None,
        "notes": "Full season point history",
    },

    # ── Player pick / start recommendation ────────────────────────────────────
    {
        "text": "es un buen pick para esta semana gibbs-white",
        "category": "Player Pick / Start Recommendation",
        "expected_intent": None,
        "notes": "Start recommendation for named player",
    },
    {
        "text": "¿debería poner a Isak de titular esta jornada?",
        "category": "Player Pick / Start Recommendation",
        "expected_intent": None,
        "notes": "Start/bench decision for named player",
    },
    {
        "text": "¿vale la pena fichar a Mbeumo ahora?",
        "category": "Player Pick / Start Recommendation",
        "expected_intent": None,
        "notes": "Transfer-in worthiness for named player (not a direct swap)",
    },
    {
        "text": "¿me recomiendas algún portero barato?",
        "category": "Player Pick / Start Recommendation",
        "expected_intent": None,
        "notes": "Budget GKP recommendation by position + price filter",
    },
    {
        "text": "¿qué delantero debería fichar si tengo 6 millones?",
        "category": "Player Pick / Start Recommendation",
        "expected_intent": None,
        "notes": "Position + budget filtered player recommendation",
    },

    # ── Captain / Vice-Captain gaps ───────────────────────────────────────────
    {
        "text": "compara a haaland con cherki en capitania esta semana",
        "category": "Captain / Vice-Captain",
        "expected_intent": "compare_players",
        "notes": "Spanish 'a' preposition before name causes name extraction bug",
    },
    {
        "text": "¿quién debería ser mi vicecapitán?",
        "category": "Captain / Vice-Captain",
        "expected_intent": None,
        "notes": "Vice-captain specific recommendation — distinct from captain",
    },
    {
        "text": "si capianto a Salah y no juega, ¿quién es la mejor alternativa?",
        "category": "Captain / Vice-Captain",
        "expected_intent": None,
        "notes": "Conditional captain fallback planning",
    },
    {
        "text": "¿qué capitán diferencial me recomiendas esta semana?",
        "category": "Captain / Vice-Captain",
        "expected_intent": None,
        "notes": "Differential captain — low-owned captain pick",
    },

    # ── Transfer planning gaps ────────────────────────────────────────────────
    {
        "text": "¿vale la pena hacer un hit esta semana?",
        "category": "Transfer Planning",
        "expected_intent": None,
        "notes": "Transfer hit (-4) evaluation — no specific swap in mind",
    },
    {
        "text": "¿debería guardar mi transferencia libre para la próxima semana?",
        "category": "Transfer Planning",
        "expected_intent": None,
        "notes": "Free transfer banking decision",
    },
    {
        "text": "¿a quién debería sacar de mi equipo esta semana?",
        "category": "Transfer Planning",
        "expected_intent": None,
        "notes": "Transfer-out recommendation without a target named",
    },
    {
        "text": "tengo 1.5 millones en banco, ¿qué puedo hacer?",
        "category": "Transfer Planning",
        "expected_intent": None,
        "notes": "Budget-constrained transfer planning",
    },
    {
        "text": "¿a quién debería tener de cara al final de temporada?",
        "category": "Transfer Planning",
        "expected_intent": None,
        "notes": "Season-end asset targeting",
    },

    # ── Chip strategy gaps ────────────────────────────────────────────────────
    {
        "text": "¿cuándo debería usar el triple capitán?",
        "category": "Chip Strategy",
        "expected_intent": None,
        "notes": "Timing advice for TC chip — not a yes/no this GW",
    },
    {
        "text": "¿me conviene usar el bench boost ahora o guardarlo?",
        "category": "Chip Strategy",
        "expected_intent": None,
        "notes": "BB timing with explicit trade-off framing",
    },
    {
        "text": "no he usado ningún chip todavía, ¿cuál uso primero?",
        "category": "Chip Strategy",
        "expected_intent": None,
        "notes": "Chip sequencing strategy from scratch",
    },

    # ── Squad / Bench management ──────────────────────────────────────────────
    {
        "text": "¿cómo ordeno mi banquillo para esta jornada?",
        "category": "Squad / Bench Management",
        "expected_intent": None,
        "notes": "Bench ordering — expected points optimization",
    },
    {
        "text": "¿cuál es mi mejor once posible?",
        "category": "Squad / Bench Management",
        "expected_intent": None,
        "notes": "Optimal starting XI from user's squad — needs squad context",
    },
    {
        "text": "¿qué formación me recomiendas usar esta semana?",
        "category": "Squad / Bench Management",
        "expected_intent": None,
        "notes": "Formation recommendation",
    },
    {
        "text": "¿debería dejar a Salah en el banquillo esta semana?",
        "category": "Squad / Bench Management",
        "expected_intent": None,
        "notes": "Bench vs start for expensive asset — rotation risk",
    },

    # ── Price changes / ownership ─────────────────────────────────────────────
    {
        "text": "¿va a subir de precio Mbeumo?",
        "category": "Player Info / Stats",
        "expected_intent": None,
        "notes": "Price rise prediction",
    },
    {
        "text": "¿quién está subiendo de precio esta semana?",
        "category": "Player Info / Stats",
        "expected_intent": None,
        "notes": "Price risers list",
    },
    {
        "text": "¿qué jugadores han bajado de precio últimamente?",
        "category": "Player Info / Stats",
        "expected_intent": None,
        "notes": "Price fallers list",
    },

    # ── Injury / availability ─────────────────────────────────────────────────
    {
        "text": "¿está lesionado Rashford?",
        "category": "Player Info / Stats",
        "expected_intent": None,
        "notes": "Injury/availability check for named player",
    },
    {
        "text": "¿hay dudas para esta jornada?",
        "category": "Player Info / Stats",
        "expected_intent": None,
        "notes": "Doubts/injury list for the GW",
    },
    {
        "text": "¿cuáles son los jugadores en duda para esta semana?",
        "category": "Player Info / Stats",
        "expected_intent": None,
        "notes": "Availability list — yellow flag players",
    },

    # ── Deadline / schedule ────────────────────────────────────────────────────
    {
        "text": "¿cuándo es el deadline de la próxima jornada?",
        "category": "Gameweek Info",
        "expected_intent": None,
        "notes": "Deadline time — not covered by current_gameweek intent",
    },
    {
        "text": "¿cuántas jornadas quedan?",
        "category": "Gameweek Info",
        "expected_intent": None,
        "notes": "Remaining GW count",
    },

    # ── Manager / league context ──────────────────────────────────────────────
    {
        "text": "¿cómo voy en mi liga privada?",
        "category": "Meta / App Behavior",
        "expected_intent": None,
        "notes": "Private league standings — requires user auth/team ID",
    },
    {
        "text": "¿cuántos puntos llevo esta temporada?",
        "category": "Meta / App Behavior",
        "expected_intent": None,
        "notes": "User's own season total — requires team context",
    },

    # ── Compound / multi-intent ───────────────────────────────────────────────
    {
        "text": "¿debería hacer una transferencia y usar el wildcard esta semana?",
        "category": "Transfer Planning",
        "expected_intent": None,
        "notes": "Multi-intent: transfer + chip in one question",
    },
    {
        "text": "dame los fixtures de Salah y dime si es buen capitán",
        "category": "Captain / Vice-Captain",
        "expected_intent": None,
        "notes": "Multi-intent: fixture run + captain assessment",
    },
    {
        "text": "¿quién tiene mejor fixture, Salah o Mbeumo, y a quién capianto?",
        "category": "Captain / Vice-Captain",
        "expected_intent": None,
        "notes": "Multi-intent: fixture comparison + captain decision",
    },
]
