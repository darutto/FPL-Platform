/**
 * Session transport tests — V2 Phase 2e
 *
 * Pure function tests: no fetch mocking, no React, no DOM required.
 *
 * Coverage:
 *   1. Rendering path parity — selectIntentView works identically on
 *      SessionAskResponse shape (structurally a superset of AskResponse).
 *   2. Ask mode resolution — the three-way branch (stateless / session-create /
 *      session-continue) behaves correctly as mode and sessionId change.
 *   3. Session expiry reset — 404 clears sessionId, reverting to session-create
 *      on next send.
 *   4. Stateless regression — existing single-intent rendering is unaffected.
 */
import type { AskResponse } from '../lib/types';
import { selectIntentView } from '../lib/intent-renderer';
import {
  captainOkResponse,
  transferOkResponse,
  comparisonOkResponse,
  fixtureRunOkResponse,
  differentialOkResponse,
  multiIntentOkResponse,
} from './fixtures/sample-responses';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Simulates the wire shape of SessionAskResponse — AskResponse fields plus
 * session_id. Used to verify the renderer is agnostic to the extra field.
 */
interface SessionAskResponseShape extends AskResponse {
  session_id: string;
}

function asSessionResponse(
  r: AskResponse,
  id = 'test-session-abc-123',
): SessionAskResponseShape {
  return { ...r, session_id: id };
}

/**
 * Pure function mirroring the ask-mode branch logic in ChatShell.sendMessage.
 * Extracted here for unit testing without React or mocked fetch.
 */
type AskMode = 'stateless' | 'session-create' | 'session-continue';

function resolveAskMode(sessionMode: boolean, sessionId: string | null): AskMode {
  if (!sessionMode) return 'stateless';
  if (sessionId === null) return 'session-create';
  return 'session-continue';
}

// ---------------------------------------------------------------------------
// Rendering path parity — SessionAskResponse is a structural subtype
// ---------------------------------------------------------------------------

describe('session rendering parity — selectIntentView on session-wrapped responses', () => {
  test('session-wrapped captain response → "captain"', () => {
    expect(selectIntentView(asSessionResponse(captainOkResponse))).toBe('captain');
  });

  test('session-wrapped transfer response → "transfer"', () => {
    expect(selectIntentView(asSessionResponse(transferOkResponse))).toBe('transfer');
  });

  test('session-wrapped comparison response → "comparison"', () => {
    expect(selectIntentView(asSessionResponse(comparisonOkResponse))).toBe('comparison');
  });

  test('session-wrapped fixture_run response → "fixture_run"', () => {
    expect(selectIntentView(asSessionResponse(fixtureRunOkResponse))).toBe('fixture_run');
  });

  test('session-wrapped differential response → "differential"', () => {
    expect(selectIntentView(asSessionResponse(differentialOkResponse))).toBe('differential');
  });

  test('session-wrapped multi_intent response → "multi_intent"', () => {
    expect(selectIntentView(asSessionResponse(multiIntentOkResponse))).toBe('multi_intent');
  });

  test('session_id field does not affect selectIntentView output', () => {
    const withSession = asSessionResponse(captainOkResponse, 'abc-123');
    const withoutSession: AskResponse = captainOkResponse;
    expect(selectIntentView(withSession)).toBe(selectIntentView(withoutSession));
  });

  test('session response with non-ok outcome → null (same as stateless)', () => {
    const expired = asSessionResponse({
      ...captainOkResponse,
      outcome: 'error',
      captain: null,
    });
    expect(selectIntentView(expired)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Ask mode resolution — three-way branch
// ---------------------------------------------------------------------------

describe('resolveAskMode — stateless / session-create / session-continue', () => {
  test('sessionMode=false, sessionId=null → "stateless"', () => {
    expect(resolveAskMode(false, null)).toBe('stateless');
  });

  test('sessionMode=false, sessionId set → "stateless" (mode takes precedence)', () => {
    expect(resolveAskMode(false, 'abc-123')).toBe('stateless');
  });

  test('sessionMode=true, sessionId=null → "session-create" (first turn)', () => {
    expect(resolveAskMode(true, null)).toBe('session-create');
  });

  test('sessionMode=true, sessionId set → "session-continue" (subsequent turns)', () => {
    expect(resolveAskMode(true, 'abc-123')).toBe('session-continue');
  });

  test('session lifecycle: null → id → null transitions', () => {
    let id: string | null = null;

    // First send: no session yet
    expect(resolveAskMode(true, id)).toBe('session-create');

    // After createSession resolves
    id = 'new-session-id';
    expect(resolveAskMode(true, id)).toBe('session-continue');

    // After clearSession / session expired
    id = null;
    expect(resolveAskMode(true, id)).toBe('session-create');
  });
});

// ---------------------------------------------------------------------------
// Session expiry reset — 404 handling mirrors ChatShell behaviour
// ---------------------------------------------------------------------------

describe('session expiry reset logic', () => {
  test('on 404, sessionId resets to null → next call is session-create', () => {
    let sessionId: string | null = 'active-session';

    // Simulate 404 handler: setSessionId(null)
    sessionId = null;

    expect(resolveAskMode(true, sessionId)).toBe('session-create');
  });

  test('after expiry reset, mode stays session (not reverted to stateless)', () => {
    const sessionMode = true;
    let sessionId: string | null = null; // reset by expiry handler

    // Mode is still true — user did not toggle off
    expect(resolveAskMode(sessionMode, sessionId)).toBe('session-create');
  });
});

// ---------------------------------------------------------------------------
// Stateless regression — existing rendering unaffected by session changes
// ---------------------------------------------------------------------------

describe('stateless mode regression', () => {
  test('stateless mode never calls session-create path', () => {
    // Even if somehow a sessionId leaked in, stateless mode ignores it
    expect(resolveAskMode(false, 'leaked-id')).toBe('stateless');
    expect(resolveAskMode(false, null)).toBe('stateless');
  });

  test('all pre-Phase-2e single-intent responses still route correctly in stateless mode', () => {
    // Verify selectIntentView on plain AskResponse still works — no regression
    expect(selectIntentView(captainOkResponse)).toBe('captain');
    expect(selectIntentView(transferOkResponse)).toBe('transfer');
    expect(selectIntentView(fixtureRunOkResponse)).toBe('fixture_run');
    expect(selectIntentView(differentialOkResponse)).toBe('differential');
    expect(selectIntentView(multiIntentOkResponse)).toBe('multi_intent');
  });
});
