"""Provenance of football stores, and the places that must refuse trial data.

Three statuses, a closed vocabulary:

* ``mock_validated``: built from checked-in fixtures.
* ``live_trial_local``: FI-9 builds canonical stores from live Sportmonks reads
  for the trial's own analysis. They must never leave the machine they were
  built on: trial-era identities (non-PL club seeds minted from the provider,
  crosswalks from the trial's mapping) are not governed, and the trial terms
  are not the production licence. Every path that publishes, syncs or serves a
  store checks this and refuses.
* ``licensed_starter``: built by the production ingestion job from the paid
  Sportmonks Starter plan. The licence allows storing, deriving and showing to
  subscribers (never redistributing the raw feed), so the publishing and
  serving paths accept it. It has its own normalizer and source kind; a store
  that carries any trial marker is still trial data, whatever its status says.
"""
from __future__ import annotations

from typing import Any, Mapping

MOCK_VALIDATED = "mock_validated"
LIVE_TRIAL_LOCAL = "live_trial_local"
LICENSED_STARTER = "licensed_starter"
#: The closed vocabulary of `assumption_status` for feature and context builds.
ASSUMPTION_STATUSES = frozenset({MOCK_VALIDATED, LIVE_TRIAL_LOCAL, LICENSED_STARTER})
#: Normalizer name the live-trial context builds carry (mock builds carry ``fi5ba-v1``).
LIVE_TRIAL_NORMALIZER = "live-trial-v1"
#: ``source.source_kind`` of the live-trial builds.
LIVE_TRIAL_SOURCE_KIND = "local-live-trial"
#: Normalizer name and source kind of the licensed production builds.
LICENSED_NORMALIZER = "licensed-starter-v1"
LICENSED_SOURCE_KIND = "licensed-sportmonks-starter"


class LiveTrialProvenanceRefused(ValueError):
    """A live-trial-local store reached a path that publishes or serves."""


def is_live_trial(manifest: Mapping[str, Any]) -> bool:
    """True when a canonical-v1, context-v2 or feature-v2 manifest is live-trial-local.

    Any one marker is enough, so a trial store relabelled ``licensed_starter``
    is still recognized by its normalizer or its source kind."""
    if manifest.get("assumption_status") == LIVE_TRIAL_LOCAL:
        return True
    summary = manifest.get("assumption_status_summary")
    if isinstance(summary, Mapping) and LIVE_TRIAL_LOCAL in summary:
        return True
    source = manifest.get("source")
    if isinstance(source, Mapping) and source.get("source_kind") == LIVE_TRIAL_SOURCE_KIND:
        return True
    versions = manifest.get("normalizer_versions")
    return isinstance(versions, Mapping) and LIVE_TRIAL_NORMALIZER in versions.values()


def refuse_live_trial(manifest: Mapping[str, Any], where: str) -> None:
    if is_live_trial(manifest):
        raise LiveTrialProvenanceRefused(
            f"live_trial_local provenance refused at {where}: this store is local to the trial and is never "
            "published, synchronized or served")
