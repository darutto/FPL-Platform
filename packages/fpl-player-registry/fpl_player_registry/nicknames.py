"""
fpl_player_registry.nicknames
==============================
Known nickname / alias table for FPL players.

Source: fpl-video-repurposer/build_fpl_kb.py::KNOWN_NICKNAMES (lines 73-100)
        Predominantly Spanish community nicknames used in video commentary.

Keys are FPL web_names (exact, case-sensitive).
Values are lists of aliases that resolve to that player.

Do not add fuzzy patterns here — see Phase 2+ for fuzzy matching.
To extend: add more web_name → [alias, ...] entries and re-run tests.
"""

from __future__ import annotations

KNOWN_NICKNAMES: dict[str, list[str]] = {
    "Salah":            ["Mo", "el Salah", "el Faraón"],
    "Haaland":          ["Erling", "el Vikingo", "el Haaland"],
    "De Bruyne":        ["KDB", "el De Bruyne"],
    "Palmer":           ["el Palmer", "Cole"],
    "Saka":             ["el Saka", "Bukayo"],
    "Son":              ["Sonny", "el Son", "Heung-Min"],
    "Mbappé":           ["Kylian", "el Mbappé"],
    "Foden":            ["Phil", "el Foden"],
    "Trippier":         ["el Trippier", "Kieran"],
    "Alexander-Arnold": ["TAA", "el Alexander-Arnold", "Trent"],
    "Rashford":         ["el Rashford", "Marcus"],
    "Martinelli":       ["el Martinelli", "Gabi", "Gabriel Martinelli"],  # i98: store form
    "Watkins":          ["el Watkins", "Ollie"],
    "Gordon":           ["el Gordon", "Anthony"],
    "Isak":             ["el Isak", "Alexander"],
    # Community initialisms for multi-part / hyphenated names (see WebSearch
    # 2026-08: VVD, DCL, etc. are standard FPL shorthand on r/FantasyPL & FPL
    # glossaries). Keyed on the exact FPL web_name. "De Bruyne"/"Alexander-Arnold"
    # already carry KDB/TAA above.
    "Van Dijk":         ["VVD"],
    "Calvert-Lewin":    ["DCL"],
    "Gibbs-White":      ["MGW", "MGG"],
    "Hudson-Odoi":      ["CHO"],
    "Smith Rowe":       ["ESR"],
    "Ward-Prowse":      ["JWP"],
    # i98: the forms the Understat store (fpl-tactical) uses for players FPL
    # lists under a short, initialled or family-name web_name. Measured
    # 2026-09-17 over the 449 distinct names of the 2025-26 store against the
    # live bootstrap through zonal_weakness_tool.resolve_store_player
    # (RANK_EXACT only): 300 resolved, these 35 did not and now do; no name
    # that resolved before changed target; none of the 35 lands on an
    # unintended player. Keyed on the exact FPL web_name like every entry
    # above; a form whose web_name is shared by two players after
    # normalisation ("King" x2, "Gomez" x2, "Muñoz"/"Munoz") is deliberately
    # NOT here -- the alias would tie and resolve to nothing, which is the
    # right answer for a table that cannot say which one.
    "Khusanov":         ["Abduqodir Khusanov"],
    "Garnacho":         ["Alejandro Garnacho"],
    "Alysson":          ["Alysson Edward"],
    "Tanaka":           ["Ao Tanaka"],
    "Gannon-Doak":      ["Ben Doak"],
    "White":            ["Ben White"],
    "B.Fernandes":      ["Bruno Fernandes"],
    "Bruno G.":         ["Bruno Guimarães"],
    "Alcaraz":          ["Carlos Alcaraz"],
    "Ballard":          ["Dan Ballard"],
    "Dalot":            ["Diogo Dalot"],
    "Solanke":          ["Dominic Solanke"],
    "Buendía":          ["Emiliano Buendía"],
    "Carvalho":         ["Fabio Carvalho"],
    "Florentino":       ["Florentino Luís"],
    "G.Jesus":          ["Gabriel Jesus"],
    "Lerma":            ["Jefferson Lerma"],
    "J.Cuenca":         ["Jorge Cuenca"],
    "Mitoma":           ["Kaoru Mitoma"],
    "Ugarte":           ["Manuel Ugarte"],
    "Senesi":           ["Marcos Senesi"],
    "Zubimendi":        ["Martín Zubimendi"],
    "Cunha":            ["Matheus Cunha"],
    "Cash":             ["Matthew Cash"],
    "Merino":           ["Mikel Merino"],
    "Caicedo":          ["Moisés Caicedo"],
    "N.Gonzalez":       ["Nico González"],
    "P.M.Sarr":         ["Pape Sarr"],
    "Neto":             ["Pedro Neto"],
    "Muniz":            ["Rodrigo Muniz"],
    "Rúben":            ["Rúben Dias"],
    "Nyoni":            ["Treymaurice Nyoni"],
    "Endo":             ["Wataru Endo"],
    "Yeremy":           ["Yeremi Pino"],
}




#: Interchangeable given names: the formal form, its diminutives and its
#: foreign spellings. Entries are single words, already in the comparison form
#: of ``normalize_player_name`` (lowercase, no accents). Used by the resolver to
#: read a colloquial "Nico Jackson" against the full name "Nicolas Jackson":
#: FPL's ``web_name`` ("N.Jackson", "Jackson") never carries the first name, so
#: the ``KNOWN_NICKNAMES`` table above (keyed on web_name) cannot express it.
#: A group only widens which *given names* are treated alike; the surname still
#: has to match, and a tie still goes to the pick wizard.
GIVEN_NAME_GROUPS: tuple[frozenset[str], ...] = tuple(
    frozenset(group.split())
    for group in (
        "nicolas nico nick nicholas nicola nicolo nik",
        "alexander alexandre alejandro alex alexandr",
        "christopher chris kit",
        "matthew matt matty matthias",
        "william will willy willian bill billy",
        "thomas tom tommy tomas",
        "joseph joe joey josef",
        "james jamie jim jimmy",
        "benjamin ben benji benny",
        "samuel sam sammy",
        "daniel dan danny daniele",
        "david dave davy",
        "michael mike mikey",
        "robert rob robbie bobby bob",
        "richard rick ricky richie",
        "anthony antony tony",
        "edward ed eddie eddy ted",
        "frederick fred freddie fredrick",
        "jonathan jon jonny",
        "joshua josh",
        "jacob jake",
        "philip phillip phil",
        "steven stephen steve stevie",
        "gabriel gabi gabby",
        "leonardo leo leonard",
        "francisco paco fran",
        "rodrigo rodri",
        "sebastian sebastien seb",
        "timothy tim timmy",
        "andrew andy drew",
        "patrick pat paddy",
        "kenneth ken kenny",
        "ronald ron ronnie",
        "dominic dominik dom",
        "mohamed mohammed mohammad muhammad mohamad mo",
        "emmanuel manu manny",
        "maximilian max maxi",
        "oliver ollie olly oli",
        "henry harry",
        "bernardo bernie",
        "zachary zach zack zak",
        "ignacio nacho",
        "enrique kike quique",
        "jeremy jeremie",
        "lewis lew",
        "theodore theo",
    )
)
