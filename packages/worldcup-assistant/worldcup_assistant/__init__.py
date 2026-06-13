"""
worldcup_assistant
===================
World Cup 2026 information assistant — isolated parallel domain.

Iteration 1 surface::

    from worldcup_assistant import ask_wc, WCAskResult
    from worldcup_assistant.locale_es import localize_payload
    from worldcup_assistant.tools import WC_TOOL_SPECS, execute_wc_tool
    from worldcup_assistant.context_builder import build_wc_context, WC_SYSTEM_PROMPT

Depends on ``llm_orchestrator_core`` (generic provider + tool loop) and
``worldcup_api_client`` (data).  MUST NOT import from any ``fpl_*`` package.
"""

import os
import sys

# Sibling-package sys.path bootstrap. This must run before the imports below,
# since Python executes this __init__ (to import the ``worldcup_assistant``
# package) before any submodule such as ``wc_server`` gets a chance to set up
# sys.path itself — e.g. when uvicorn loads "worldcup_assistant.wc_server:app".
_PKGS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _pkg in ("llm-orchestrator-core", "worldcup-api-client"):
    _path = os.path.join(_PKGS, _pkg)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from .ask import DEFAULT_WC_MODEL, WCAskResult, ask_wc  # noqa: F401
from .context_builder import WC_SYSTEM_PROMPT, build_wc_context  # noqa: F401
from .tools import WC_TOOL_NAMES, WC_TOOL_SPECS, execute_wc_tool  # noqa: F401
