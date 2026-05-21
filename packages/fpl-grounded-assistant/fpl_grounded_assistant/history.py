"""fpl_grounded_assistant.history
================================
P1.e Lever 3: Conversation history pruning helper.

Reduces per-turn input token cost in multi-turn sessions by summarising older
turns so the LLM receives full detail only for the most-recent N turns.

IMPLEMENTATION STATUS
---------------------
This module is IMPLEMENTED but DORMANT for the stateless ``POST /ask`` path.
The helper is wired here so session-mode graduation (a future phase) can invoke
it immediately without additional scaffolding.

For stateless ``POST /ask`` (the current production path), ``ask_v2()`` passes
no message history — every call is a fresh single-turn context.  The pruning
helper is a no-op for single-turn inputs.

When session mode graduates, session code should call ``prune_history(messages)``
BEFORE passing the accumulated history to ``ask_orchestrated()``.

Cost motivation
---------------
Without pruning, every turn in a 10-turn session re-sends 9 prior turns,
growing the context linearly.  After pruning:
  - Turns 1..N-3  → one-line summary per turn (or grouped)
  - Turns N-2..N  → full content preserved
Net result: O(constant) input cost per turn after the first 3 turns.

Pruning strategy
----------------
1. Keep the last ``keep_full`` turns (default 3) verbatim.
2. For older turns: replace each tool-result block with a one-line abstract
   (``{status, tool_name}`` only); collapse the full result JSON.
3. Generate a human-readable summary string ONCE (see ``_summarise_older_turns``)
   and cache it on the ``ConversationHistory`` object so it is not regenerated
   on every subsequent turn.

The summary is inserted as a synthetic ``role=system`` (or ``role=user`` for
providers that do not support role=system in conversation turns) at the start
of the pruned history so the LLM knows what was discussed earlier.

API
---
``prune_history(messages, keep_full=3)`` → list[dict]
    Pure function.  No side-effects.  Returns a new list (does not mutate).

``ConversationHistory``
    Stateful wrapper for session use.  Accumulates turns and caches the
    first-generated summary to avoid repeated re-summarisation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default number of recent turns to keep with full content.
DEFAULT_KEEP_FULL: int = 3

#: Maximum characters for a single tool-output summary (one-line abstract).
_TOOL_SUMMARY_MAX_CHARS: int = 120


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_tool_result_block(block: Any) -> bool:
    """Return True when *block* is a tool_result content block."""
    if isinstance(block, dict):
        return block.get("type") == "tool_result"
    return False


def _summarise_tool_result(block: dict[str, Any]) -> dict[str, Any]:
    """Return a compressed one-line tool_result block.

    Replaces the full JSON content with a brief abstract:
    ``{status, tool_use_id}`` + first 80 chars of result summary.
    """
    content = block.get("content", "")
    brief = ""
    if isinstance(content, str):
        try:
            data = json.loads(content)
            status = data.get("status", "?") if isinstance(data, dict) else "?"
            brief = f"status={status}"
        except (json.JSONDecodeError, ValueError):
            brief = content[:_TOOL_SUMMARY_MAX_CHARS]
    elif isinstance(content, list):
        brief = f"[{len(content)} content blocks]"
    else:
        brief = str(content)[:_TOOL_SUMMARY_MAX_CHARS]

    return {
        "type":         "tool_result",
        "tool_use_id":  block.get("tool_use_id"),
        "content":      f"[summarised] {brief}",
    }


def _compress_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *msg* with tool_result blocks replaced by one-line abstracts."""
    content = msg.get("content")
    if isinstance(content, list):
        new_content = []
        for block in content:
            if _is_tool_result_block(block):
                new_content.append(_summarise_tool_result(block))
            else:
                new_content.append(block)
        return {**msg, "content": new_content}
    return msg


def _summarise_older_turns(messages: list[dict[str, Any]]) -> str:
    """Generate a one-line summary string for a list of older turns.

    Extracts user questions and tool names from the compressed message list.
    This summary is inserted as a synthetic context message at the start of
    the pruned history so the LLM has recall of prior conversation topics.

    Parameters
    ----------
    messages:
        Older turns (already compressed by ``_compress_message``).

    Returns
    -------
    str
        Plain-text summary e.g.:
        "Earlier in this conversation, the user asked about: gameweek,
        Haaland captain score. Tools used: get_current_gameweek,
        get_captain_score."
    """
    topics: list[str] = []
    tools_used: list[str] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            if isinstance(content, str) and content.strip():
                # Trim to first 60 chars of the question
                snippet = content.strip()[:60]
                if snippet:
                    topics.append(snippet)
        elif role == "assistant":
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "")
                        if name and name not in tools_used:
                            tools_used.append(name)

    parts = []
    if topics:
        parts.append("user asked about: " + "; ".join(topics[:3]))
    if tools_used:
        parts.append("tools used: " + ", ".join(tools_used[:5]))

    if not parts:
        return "Earlier turns summarised (no extractable topics)."
    return "Earlier in this conversation, " + "; ".join(parts) + "."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def prune_history(
    messages: list[dict[str, Any]],
    keep_full: int = DEFAULT_KEEP_FULL,
) -> list[dict[str, Any]]:
    """Prune conversation history, keeping the last *keep_full* turns verbatim.

    Older turns are summarised: tool-result blocks are compressed to one-line
    abstracts, and a brief summary context message is prepended.

    This is a PURE FUNCTION — it does not mutate *messages* and has no side-
    effects.  It is safe to call on any list of message dicts.

    DORMANT for stateless ``POST /ask``: when *messages* has ≤ *keep_full*
    turns, the original list is returned unchanged (zero overhead for the
    single-turn path).

    Parameters
    ----------
    messages:
        Conversation message list in the LLM API wire format:
        ``[{"role": "user"/"assistant", "content": str | list}, ...]``.
    keep_full:
        Number of most-recent turns to preserve with full content.
        Default: 3.  Must be >= 1.

    Returns
    -------
    list[dict[str, Any]]
        Pruned message list.  When len(messages) <= keep_full, returns
        *messages* unchanged (no allocation overhead).

    Examples
    --------
    Stateless single-turn (no-op)::

        result = prune_history([{"role": "user", "content": "who is Haaland?"}])
        assert result == [{"role": "user", "content": "who is Haaland?"}]

    Multi-turn session (>3 turns)::

        pruned = prune_history(long_history, keep_full=3)
        # pruned[0] is a synthetic summary context message
        # pruned[-3:] are the 3 most-recent turns verbatim

    Session integration (future)::

        # In session code, BEFORE passing history to ask_orchestrated():
        messages = prune_history(session.message_history, keep_full=3)
        result = ask_orchestrated(question, bootstrap, history=messages, ...)
    """
    keep_full = max(1, keep_full)

    # No-op: not enough turns to prune.
    if len(messages) <= keep_full:
        return messages

    # Split into older turns and recent turns.
    older = messages[:-keep_full]
    recent = messages[-keep_full:]

    # Compress tool results in older turns.
    compressed_older = [_compress_message(msg) for msg in older]

    # Generate summary of older turns.
    summary_text = _summarise_older_turns(compressed_older)

    # Build summary context block (role=user so it works across all providers).
    summary_msg: dict[str, Any] = {
        "role":    "user",
        "content": f"[CONTEXT] {summary_text}",
    }

    return [summary_msg] + recent


# ---------------------------------------------------------------------------
# Stateful session wrapper (for future session graduation)
# ---------------------------------------------------------------------------

@dataclass
class ConversationHistory:
    """Stateful conversation history with cached summary.

    Usage (future session path)::

        history = ConversationHistory()
        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": answer})

        # Get pruned view for the next LLM call:
        pruned = history.get_pruned(keep_full=3)

    The summary string is generated once (the first time pruning fires) and
    cached in ``_cached_summary``.  Subsequent calls to ``get_pruned()`` reuse
    the cached summary rather than regenerating it, saving a string-building
    operation on every turn.

    DORMANT: this class is not wired into ask_v2() or ask_orchestrated().
    Session code (when graduated) should instantiate ConversationHistory per
    session and call get_pruned() before each orchestrator invocation.
    """

    _messages: list[dict[str, Any]] = field(default_factory=list)
    _cached_summary: str | None = field(default=None, init=False)

    def append(self, message: dict[str, Any]) -> None:
        """Append one message dict to the history."""
        self._messages.append(message)

    def get_pruned(self, keep_full: int = DEFAULT_KEEP_FULL) -> list[dict[str, Any]]:
        """Return the pruned message list, using cached summary when available.

        Parameters
        ----------
        keep_full:
            Number of recent turns to keep verbatim.

        Returns
        -------
        list[dict[str, Any]]
            Pruned history, same contract as ``prune_history()``.
        """
        keep_full = max(1, keep_full)
        if len(self._messages) <= keep_full:
            return list(self._messages)

        older = self._messages[:-keep_full]
        recent = self._messages[-keep_full:]

        # Generate summary once; reuse on subsequent calls.
        if self._cached_summary is None:
            compressed_older = [_compress_message(msg) for msg in older]
            self._cached_summary = _summarise_older_turns(compressed_older)

        summary_msg: dict[str, Any] = {
            "role":    "user",
            "content": f"[CONTEXT] {self._cached_summary}",
        }
        return [summary_msg] + list(recent)

    def __len__(self) -> int:
        """Return total number of accumulated messages."""
        return len(self._messages)
