"""Provenance of locally built live-trial stores, and the places that must refuse it.

FI-9 builds canonical stores from live Sportmonks reads for the trial's own
analysis. Those stores carry ``live_trial_local`` and must never leave the
machine they were built on: the licence on Sportmonks data is unanswered, and
the identities in them (non-PL club seeds minted from the provider, crosswalks
from the trial's mapping) are not governed. Every path that publishes, syncs or
serves a store checks this and refuses.
"""
from __future__ import annotations

from typing import Any, Mapping

MOCK_VALIDATED = "mock_validated"
LIVE_TRIAL_LOCAL = "live_trial_local"
#: The closed vocabulary of `assumption_status` for feature and context builds.
ASSUMPTION_STATUSES = frozenset({MOCK_VALIDATED, LIVE_TRIAL_LOCAL})
#: Normalizer name the live-trial context builds carry (mock builds carry ``fi5ba-v1``).
LIVE_TRIAL_NORMALIZER = "live-trial-v1"


class LiveTrialProvenanceRefused(ValueError):
    """A live-trial-local store reached a path that publishes or serves."""


def is_live_trial(manifest: Mapping[str, Any]) -> bool:
    """True when a canonical-v1, context-v2 or feature-v2 manifest is live-trial-local."""
    if manifest.get("assumption_status") == LIVE_TRIAL_LOCAL:
        return True
    summary = manifest.get("assumption_status_summary")
    if isinstance(summary, Mapping) and LIVE_TRIAL_LOCAL in summary:
        return True
    versions = manifest.get("normalizer_versions")
    return isinstance(versions, Mapping) and LIVE_TRIAL_NORMALIZER in versions.values()


def refuse_live_trial(manifest: Mapping[str, Any], where: str) -> None:
    if is_live_trial(manifest):
        raise LiveTrialProvenanceRefused(
            f"live_trial_local provenance refused at {where}: this store is local to the trial and is never "
            "published, synchronized or served")
