"""
worldcup_assistant.locale_es
=============================
Deterministic English → Spanish localization for World Cup API values.

Two-layer localization contract (plan, cross-cutting requirement 1):

* **Free text** is localized by the LLM (system prompt rules in
  ``context_builder``).
* **Structured values** (country names, match statuses, stages, positions)
  are localized HERE, deterministically, before they reach any structured
  response field — cards must render Spanish without depending on LLM
  phrasing, and raw enums (``in_progress``) must never leak to the UI.

Lookups are case-insensitive on a normalised key.  Unknown values pass
through unchanged (fail-open: better an English name than a crash), and the
system prompt instructs the LLM to translate any unmapped survivor in prose.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Country / team names (FIFA English name → Spanish)
# ---------------------------------------------------------------------------

COUNTRY_ES: dict[str, str] = {
    # Hosts
    "united states": "Estados Unidos",
    "usa": "Estados Unidos",
    "mexico": "México",
    "canada": "Canadá",
    # UEFA
    "spain": "España",
    "england": "Inglaterra",
    "france": "Francia",
    "germany": "Alemania",
    "netherlands": "Países Bajos",
    "belgium": "Bélgica",
    "croatia": "Croacia",
    "switzerland": "Suiza",
    "denmark": "Dinamarca",
    "sweden": "Suecia",
    "norway": "Noruega",
    "poland": "Polonia",
    "portugal": "Portugal",
    "italy": "Italia",
    "austria": "Austria",
    "scotland": "Escocia",
    "wales": "Gales",
    "turkey": "Turquía",
    "turkiye": "Turquía",
    "türkiye": "Turquía",
    "ukraine": "Ucrania",
    "serbia": "Serbia",
    "czechia": "Chequia",
    "czech republic": "Chequia",
    "slovakia": "Eslovaquia",
    "slovenia": "Eslovenia",
    "romania": "Rumania",
    "hungary": "Hungría",
    "greece": "Grecia",
    "finland": "Finlandia",
    "republic of ireland": "Irlanda",
    "ireland": "Irlanda",
    "northern ireland": "Irlanda del Norte",
    "iceland": "Islandia",
    "albania": "Albania",
    "north macedonia": "Macedonia del Norte",
    "bosnia and herzegovina": "Bosnia y Herzegovina",
    "montenegro": "Montenegro",
    "kosovo": "Kosovo",
    "georgia": "Georgia",
    "armenia": "Armenia",
    "israel": "Israel",
    "russia": "Rusia",
    # CAF
    "morocco": "Marruecos",
    "senegal": "Senegal",
    "tunisia": "Túnez",
    "algeria": "Argelia",
    "egypt": "Egipto",
    "nigeria": "Nigeria",
    "ghana": "Ghana",
    "cameroon": "Camerún",
    "ivory coast": "Costa de Marfil",
    "cote d'ivoire": "Costa de Marfil",
    "côte d'ivoire": "Costa de Marfil",
    "south africa": "Sudáfrica",
    "cape verde": "Cabo Verde",
    "cabo verde": "Cabo Verde",
    "dr congo": "RD del Congo",
    "congo dr": "RD del Congo",
    "mali": "Malí",
    "burkina faso": "Burkina Faso",
    "guinea": "Guinea",
    "gabon": "Gabón",
    "benin": "Benín",
    "zambia": "Zambia",
    "kenya": "Kenia",
    "mozambique": "Mozambique",
    "angola": "Angola",
    # AFC
    "japan": "Japón",
    "south korea": "Corea del Sur",
    "korea republic": "Corea del Sur",
    "saudi arabia": "Arabia Saudita",
    "iran": "Irán",
    "ir iran": "Irán",
    "qatar": "Catar",
    "iraq": "Irak",
    "jordan": "Jordania",
    "uzbekistan": "Uzbekistán",
    "united arab emirates": "Emiratos Árabes Unidos",
    "china": "China",
    "china pr": "China",
    "australia": "Australia",
    # OFC
    "new zealand": "Nueva Zelanda",
    # CONMEBOL
    "argentina": "Argentina",
    "brazil": "Brasil",
    "uruguay": "Uruguay",
    "colombia": "Colombia",
    "ecuador": "Ecuador",
    "paraguay": "Paraguay",
    "peru": "Perú",
    "chile": "Chile",
    "bolivia": "Bolivia",
    "venezuela": "Venezuela",
    # CONCACAF
    "panama": "Panamá",
    "costa rica": "Costa Rica",
    "honduras": "Honduras",
    "jamaica": "Jamaica",
    "haiti": "Haití",
    "curacao": "Curazao",
    "curaçao": "Curazao",
    "trinidad and tobago": "Trinidad y Tobago",
    "el salvador": "El Salvador",
    "guatemala": "Guatemala",
    "suriname": "Surinam",
}

# ---------------------------------------------------------------------------
# Match statuses (API enum → Spanish display)
# ---------------------------------------------------------------------------

STATUS_ES: dict[str, str] = {
    "scheduled":   "Programado",
    "not_started": "Por comenzar",
    "tbd":         "Por definir",
    "in_progress": "En vivo",
    "live":        "En vivo",
    "first_half":  "Primer tiempo",
    "second_half": "Segundo tiempo",
    "halftime":    "Descanso",
    "half_time":   "Descanso",
    "extra_time":  "Prórroga",
    "penalties":   "Penales",
    "paused":      "Pausado",
    "completed":   "Finalizado",
    "finished":    "Finalizado",
    "full_time":   "Finalizado",
    "complete":    "Finalizado",
    "postponed":   "Aplazado",
    "cancelled":   "Cancelado",
    "canceled":    "Cancelado",
    "suspended":   "Suspendido",
    "abandoned":   "Abandonado",
}

# ---------------------------------------------------------------------------
# Tournament stages (API enum → Spanish display)
# ---------------------------------------------------------------------------

STAGE_ES: dict[str, str] = {
    "group_stage":    "Fase de grupos",
    "group":          "Fase de grupos",
    "round_of_32":    "Dieciseisavos de final",
    "round_of_16":    "Octavos de final",
    "quarter_final":  "Cuartos de final",
    "quarter_finals": "Cuartos de final",
    "quarterfinal":   "Cuartos de final",
    "semi_final":     "Semifinales",
    "semi_finals":    "Semifinales",
    "semifinal":      "Semifinales",
    "third_place":    "Tercer puesto",
    "final":          "Final",
}

# ---------------------------------------------------------------------------
# Player positions (common API enums → Spanish display)
# ---------------------------------------------------------------------------

POSITION_ES: dict[str, str] = {
    "goalkeeper": "Portero",
    "gk":         "Portero",
    "defender":   "Defensa",
    "df":         "Defensa",
    "def":        "Defensa",
    "midfielder": "Centrocampista",
    "mf":         "Centrocampista",
    "mid":        "Centrocampista",
    "forward":    "Delantero",
    "fw":         "Delantero",
    "fwd":        "Delantero",
    "striker":    "Delantero",
}


def _norm(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def localize_country(name: str) -> str:
    """Spanish country name for an English API name (pass-through if unmapped)."""
    if not isinstance(name, str) or not name:
        return name
    return COUNTRY_ES.get(name.strip().lower(), name)


def localize_status(status: str) -> str:
    """Spanish display label for a match-status enum (pass-through if unmapped)."""
    if not isinstance(status, str) or not status:
        return status
    return STATUS_ES.get(_norm(status), STATUS_ES.get(status.strip().lower(), status))


def localize_stage(stage: str) -> str:
    """Spanish display label for a stage enum (pass-through if unmapped)."""
    if not isinstance(stage, str) or not stage:
        return stage
    return STAGE_ES.get(_norm(stage), stage)


def localize_position(position: str) -> str:
    """Spanish display label for a player-position enum (pass-through if unmapped)."""
    if not isinstance(position, str) or not position:
        return position
    return POSITION_ES.get(_norm(position), position)


# ---------------------------------------------------------------------------
# Recursive payload localization
# ---------------------------------------------------------------------------

#: JSON keys whose values are country/team names.
_COUNTRY_KEYS: frozenset[str] = frozenset({
    "team", "team_a", "team_b", "home_team", "away_team", "home", "away",
    "country", "nation", "nationality", "opponent", "winner", "loser",
})
#: JSON keys whose values are match-status enums.
_STATUS_KEYS: frozenset[str] = frozenset({"status", "match_status", "state"})
#: JSON keys whose values are stage enums.
_STAGE_KEYS: frozenset[str] = frozenset({"stage", "round", "phase"})
#: JSON keys whose values are position enums.
_POSITION_KEYS: frozenset[str] = frozenset({"position", "pos", "role"})


def localize_payload(value: Any) -> Any:
    """Recursively localize known keys in an API payload (dicts/lists).

    Returns a new structure; the input is never mutated.  Values under
    unknown keys are forwarded unchanged.  This runs on every tool output
    before it reaches the LLM or a structured response field, so neither
    prose nor cards depend on the model for enum/country translation.
    """
    if isinstance(value, list):
        return [localize_payload(v) for v in value]
    if not isinstance(value, dict):
        return value
    out: dict[str, Any] = {}
    for k, v in value.items():
        key_l = k.lower() if isinstance(k, str) else k
        if isinstance(v, str):
            if key_l in _COUNTRY_KEYS:
                out[k] = localize_country(v)
            elif key_l in _STATUS_KEYS:
                out[k] = localize_status(v)
            elif key_l in _STAGE_KEYS:
                out[k] = localize_stage(v)
            elif key_l in _POSITION_KEYS:
                out[k] = localize_position(v)
            else:
                out[k] = v
        else:
            out[k] = localize_payload(v)
    return out
