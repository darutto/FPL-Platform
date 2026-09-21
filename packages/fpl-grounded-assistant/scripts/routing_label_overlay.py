"""Label overlay for tool_routing_corpus.CORPUS, applied at scoring time.

The corpus file is a shared measurement asset and is left untouched. This
overlay ADDS acceptable tools where a later, decided policy made another
first tool correct; it never removes one.

get_my_squad (i39, PR #167) post-dates the corpus. i41 (PR #186, b54060d)
then decided the routing policy: call it whenever answering correctly
requires knowing what the user already owns, with or without a possessive
-- and measured sb-02/sb-13 going 0/5 -> 5/5 under that description. So a
first call to get_my_squad on these rows is the intended behaviour today,
not a miss.

ad-05 is deliberately NOT in the overlay: the corpus marks it underspecified
between two advice tools, and get_my_squad answers neither.
"""
from __future__ import annotations

ADD_ACCEPTABLE: dict[str, list[str]] = {
    # ownership without a possessive ("el resto del equipo", "el presupuesto
    # que me queda despues de estas ventas") -- i41's exact cases
    "sb-02": ["get_my_squad"],
    "sb-13": ["get_my_squad"],
    # explicit "evalua mi equipo" / "mi plantilla" / "mi equipo actual"
    # squad-evaluation framing. cvg-01 is the pinned question and its phrase
    # is the literal example in get_my_squad's own description.
    "cvg-01": ["get_my_squad"],
    "cvg-02": ["get_my_squad"],
    "cvg-03": ["get_my_squad"],
    "cvg-11": ["get_my_squad"],
    "cvg-12": ["get_my_squad"],
}
# Deliberately NOT overlaid, applying the same condition to their text:
#   cvg-06 "Necesito ARMAR mi equipo"            -> building, build_squad
#   sb-09  "arranco con ... Armame el resto"     -> building from a lock
#   sb-11  "armar mi equipo ideal de arranque"   -> building from scratch
#   ad-05  underspecified between two advice tools; get_my_squad answers neither

# Card E (decided 2026-09-19 by the user, see project_jev_tool_routing_pilot):
# a chip question is answered in two parts, GENERAL (is this a good GW for
# the chip, and which team group makes it so) then PARTICULAR (does the
# user's squad hold that group), possessive or not. So for every chip
# question about an existing/unspecified squad, get_my_squad is a valid
# companion first call. Build-from-scratch rows (cvg-06/07/08, sb-07) are
# NOT here: there is no squad yet, part 2 is build_squad, already accepted.
CARD_E_CHIP: dict[str, list[str]] = {
    i: ["get_my_squad"] for i in (
        "ad-03", "ad-04", "ad-05", "ad-07", "ad-10",
        "cvg-04", "cvg-05", "cvg-09", "cvg-10",
    )
}
# Card E "by extension" to transfer questions -- the user said the shape
# applies beyond chips; kept separate so the effect can be reported alone.
CARD_E_TRANSFER: dict[str, list[str]] = {
    i: ["get_my_squad"] for i in ("ad-01", "ad-06", "ad-09", "ad-11", "ad-12")
}


def acceptable_tools(item: dict, card_e: str = "chip") -> list[str]:
    """card_e: "none" = i41 overlay only; "chip" = + CARD_E_CHIP; "all" = + transfers too."""
    extra = list(ADD_ACCEPTABLE.get(item["id"], []))
    if card_e in ("chip", "all"):
        extra += CARD_E_CHIP.get(item["id"], [])
    if card_e == "all":
        extra += CARD_E_TRANSFER.get(item["id"], [])
    return list(item["acceptable_tools"]) + [t for t in extra if t not in item["acceptable_tools"]]
