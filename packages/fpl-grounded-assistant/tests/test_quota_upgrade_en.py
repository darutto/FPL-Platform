"""
The English quota upgrade message names each paid tier the way the membership page does.

The page heads a tier with its Patreon name and, in English only, a descriptor:
"Tribuna · Supporter" (fpl-ui lib/tiers.ts tierTitle). Before this the English message
repeated the Spanish short names ("• Tribuna ($1)", "• Ejecutivo ($15)") under English
prose, so an English reader met a name the page never shows. Spanish is unchanged.

The names and descriptors are copied here from the UI sources, and the sync test below reads
those sources so the two cannot drift silently.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from fpl_grounded_assistant.quota import TIERS, UPGRADE_LADDER, _upgrade_prompts

REPO = Path(__file__).resolve().parents[3]
TIERS_TS = REPO / "packages" / "fpl-ui" / "lib" / "tiers.ts"
EN_TS = REPO / "packages" / "fpl-ui" / "lib" / "i18n" / "en.ts"

#: ladder tier key -> plan id on the page (lib/tiers.ts SubscriptionTier.id)
PLAN_ID = {
    "patreon_tribuna": "tribuna",
    "patreon_basic": "gafete",
    "patreon_plus": "socio",
    "patreon_premium": "plata",
}


def _page_names() -> dict[str, str]:
    """plan id -> the name the page heads it with (from tiers.ts)."""
    src = TIERS_TS.read_text(encoding="utf-8")
    names = dict(re.findall(r"id: '(\w+)',\s*name: '([^']+)'", src))
    return names


def _en_descriptors() -> dict[str, str]:
    """plan id -> the English descriptor (from en.ts plan.<id>.descriptor)."""
    src = EN_TS.read_text(encoding="utf-8")
    return dict(re.findall(r"'plan\.(\w+)\.descriptor': '([^']*)'", src))


# -- the English message names each rung as the page does -----------------------------

@pytest.mark.parametrize("name_en", [
    "Tribuna · Supporter",
    "Gafete de cancha · Pitch Pass",
    "Socio Junior · Junior Member",
    "Ejecutivo: carné de plata · Executive: Silver Card",
])
def test_free_user_english_pitch_names_each_tier_as_the_page_does(name_en):
    _, en = _upgrade_prompts("free", "daily_message_cap_exceeded")
    assert f"• {name_en} (" in en, name_en


def test_english_pitch_keeps_the_price_and_the_caps():
    _, en = _upgrade_prompts("free", "daily_message_cap_exceeded")
    for offer in UPGRADE_LADDER:
        assert f"(${offer.price_usd}) — {TIERS[offer.tier].daily_message_cap} messages a day" in en


def test_english_pitch_excludes_the_users_own_tier_in_english_too():
    _, en = _upgrade_prompts("patreon_plus", "daily_message_cap_exceeded")
    assert "Socio Junior · Junior Member" not in en
    assert "Gafete de cancha · Pitch Pass" not in en
    assert "Ejecutivo: carné de plata · Executive: Silver Card" in en


def test_tribuna_patron_is_pitched_the_rungs_above_in_english():
    _, en = _upgrade_prompts("patreon_tribuna", "daily_message_cap_exceeded")
    assert "• Tribuna · Supporter (" not in en
    assert "• Gafete de cancha · Pitch Pass (" in en


def test_english_monthly_window_is_still_a_month():
    _, en = _upgrade_prompts("free", "monthly_message_cap_exceeded")
    assert "messages a month" in en


# -- Spanish is unchanged: the short names and no descriptor ---------------------------

def test_spanish_pitch_keeps_the_short_names_and_no_descriptor():
    es, _ = _upgrade_prompts("free", "daily_message_cap_exceeded")
    for offer in UPGRADE_LADDER:
        assert f"• {offer.display_es} (${offer.price_usd}) — " in es
    assert "Supporter" not in es
    assert "Pitch Pass" not in es
    assert "Executive: Silver Card" not in es


# -- sync with the UI sources ----------------------------------------------------------

@pytest.mark.parametrize("offer", UPGRADE_LADDER, ids=lambda o: o.tier)
def test_ladder_page_name_matches_the_membership_page(offer):
    names = _page_names()
    assert names[PLAN_ID[offer.tier]] == offer.page_name


@pytest.mark.parametrize("offer", UPGRADE_LADDER, ids=lambda o: o.tier)
def test_ladder_english_descriptor_matches_the_english_page(offer):
    descriptors = _en_descriptors()
    assert descriptors[PLAN_ID[offer.tier]] == offer.descriptor_en


def test_every_ladder_rung_has_a_page_name_and_a_descriptor():
    for offer in UPGRADE_LADDER:
        assert offer.page_name and offer.descriptor_en, offer.tier
