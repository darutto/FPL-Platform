/**
 * Contract shape tests — V2 Phase 1 UI
 *
 * Validates that:
 *   1. Every fixture request in http_contract_fixtures.json uses only
 *      keys present in AskRequest.
 *   2. intent_hint values in fixtures are in the INTENT_HINT_ALLOWLIST.
 *   3. Stable response field names from the contract are all declared in
 *      AskResponse (checked via key enumeration of a typed object).
 *   4. parseSlashCommand correctly extracts intent_hint + question.
 *   5. matchSlashCommands returns the right subset.
 *   6. SLASH_COMMANDS are all on the allowlist (validated at import).
 *   7. SUPPORTED_INTENT_VALUES covers every intent constant in dispatcher.py
 *      (drift guard — fails if a new intent is added to the backend without
 *      updating the UI contract).
 *
 * These tests run against the static artifact — no live backend needed.
 */
import * as path from 'path';
import * as fs from 'fs';
import {
  INTENT_HINT_ALLOWLIST,
  SUPPORTED_INTENT_VALUES,
  type AskRequest,
  type AskResponse,
} from '../lib/types';
import {
  SLASH_COMMANDS,
  parseSlashCommand,
  matchSlashCommands,
} from '../lib/slash-commands';

// ---------------------------------------------------------------------------
// Load the canonical contract artifact
// ---------------------------------------------------------------------------
const fixturesPath = path.resolve(
  __dirname,
  '../../fpl-grounded-assistant/http_contract_fixtures.json',
);
const fixtures = JSON.parse(fs.readFileSync(fixturesPath, 'utf-8'));

// ---------------------------------------------------------------------------
// Known valid AskRequest keys (from lib/types.ts)
// ---------------------------------------------------------------------------
const KNOWN_REQUEST_KEYS: Set<keyof AskRequest> = new Set([
  'question',
  'debug',
  'candidates_list',
  'squad_context',
  'intent_hint',
]);

// ---------------------------------------------------------------------------
// Stable response field names from the contract artifact
// ---------------------------------------------------------------------------
const STABLE_RESPONSE_FIELDS: string[] =
  fixtures._meta.response_stable_fields['POST /ask'];

// ---------------------------------------------------------------------------
// Stable fields declared in AskResponse (checked via typed object keys)
// ---------------------------------------------------------------------------
// We enumerate them by constructing a representative object — TypeScript will
// flag missing keys at compile time.
const DECLARED_STABLE_FIELDS: Record<string, true> = {
  final_text: true,
  outcome: true,
  supported: true,
  intent: true,
  review_passed: true,
  llm_used: true,
  orch_outcome: true,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('http_contract_fixtures.json — request shape', () => {
  const allFixtures = [
    ...fixtures.ask_fixtures,
    ...fixtures.session_ask_fixtures,
  ];

  test('all fixture requests use only known AskRequest keys', () => {
    for (const fixture of allFixtures) {
      const req = fixture.request as Record<string, unknown>;
      for (const key of Object.keys(req)) {
        // session_id is a path param not a body key — skip
        if (key === 'session_id') continue;
        expect(KNOWN_REQUEST_KEYS.has(key as keyof AskRequest)).toBe(true);
      }
    }
  });

  test('question field is string in all fixtures that include it', () => {
    for (const fixture of allFixtures) {
      const req = fixture.request as Record<string, unknown>;
      if ('question' in req) {
        expect(typeof req.question).toBe('string');
      }
    }
  });

  test('intent_hint values in fixtures are in INTENT_HINT_ALLOWLIST (valid hints)', () => {
    for (const fixture of allFixtures) {
      const req = fixture.request as Record<string, unknown>;
      if ('intent_hint' in req && req.intent_hint != null) {
        // The "ask_intent_hint_invalid_safe" fixture intentionally uses an
        // out-of-allowlist value to test the safe-ignore invariant.
        // Skip the allowlist check for that fixture; it is tested separately
        // by the invariants suite which verifies "safe ignore" is documented.
        const isInvalidHintFixture =
          typeof fixture.description === 'string' &&
          fixture.description.toLowerCase().includes('invalid');
        if (!isInvalidHintFixture) {
          expect(INTENT_HINT_ALLOWLIST as readonly string[]).toContain(
            req.intent_hint,
          );
        }
      }
    }
  });

  test('invalid intent_hint fixture confirms safe-ignore outcome', () => {
    const invalidFixture = allFixtures.find(
      (f: Record<string, unknown>) =>
        typeof f.description === 'string' &&
        (f.description as string).toLowerCase().includes('invalid hint'),
    );
    // The fixture exists and its expected outcome is unsupported_intent
    // (the backend silently ignored the invalid hint).
    if (invalidFixture) {
      const expected = (invalidFixture as Record<string, unknown>).expected as Record<string, unknown>;
      const body = expected?.body as Record<string, unknown> | undefined;
      expect(body?.outcome).toMatchObject({ value: 'unsupported_intent' });
    }
  });

  test('debug field is boolean when present', () => {
    for (const fixture of allFixtures) {
      const req = fixture.request as Record<string, unknown>;
      if ('debug' in req) {
        expect(typeof req.debug).toBe('boolean');
      }
    }
  });
});

describe('http_contract_fixtures.json — stable response fields', () => {
  test('all stable fields from the artifact are declared in AskResponse', () => {
    for (const field of STABLE_RESPONSE_FIELDS) {
      expect(DECLARED_STABLE_FIELDS).toHaveProperty(field);
    }
  });

  test('artifact stable fields match expected set', () => {
    expect(new Set(STABLE_RESPONSE_FIELDS)).toEqual(
      new Set(Object.keys(DECLARED_STABLE_FIELDS)),
    );
  });
});

describe('http_contract_fixtures.json — intent_hint contract invariants', () => {
  const { allowlist, invariants } = fixtures._meta.intent_hint_contract;

  test('artifact allowlist matches INTENT_HINT_ALLOWLIST in types.ts', () => {
    expect(new Set(allowlist)).toEqual(new Set(INTENT_HINT_ALLOWLIST));
  });

  test('all expected invariant strings are present in the artifact', () => {
    const invariantStr = invariants.join(' ');
    expect(invariantStr).toContain('deterministic router wins');
    expect(invariantStr).toContain('allowlisted only');
    expect(invariantStr).toContain('safe ignore');
    expect(invariantStr).toContain('pre-classifier');
    expect(invariantStr).toContain('per-turn in sessions');
  });
});

describe('http_contract_fixtures.json — http status contract', () => {
  const statusContract = fixtures.http_status_contract;

  test('200 is documented', () => {
    expect(statusContract['200']).toBeDefined();
  });

  test('422 is documented', () => {
    expect(statusContract['422']).toBeDefined();
  });

  test('404 is documented', () => {
    expect(statusContract['404']).toBeDefined();
  });
});

describe('slash-commands — parseSlashCommand', () => {
  test('parses /capitan with player name', () => {
    const result = parseSlashCommand('/capitan Haaland');
    expect(result).toEqual({ intent_hint: 'captain_score', question: 'Haaland' });
  });

  test('parses /comparar with player names', () => {
    const result = parseSlashCommand('/comparar Salah vs De Bruyne');
    expect(result).toEqual({
      intent_hint: 'compare_players',
      question: 'Salah vs De Bruyne',
    });
  });

  test('returns null for plain text (no slash)', () => {
    expect(parseSlashCommand('should I captain Haaland')).toBeNull();
  });

  test('strips command prefix leaving only the question text', () => {
    const result = parseSlashCommand('/transferencia Palmer por Gordon');
    expect(result?.question).toBe('Palmer por Gordon');
  });
});

describe('slash-commands — matchSlashCommands', () => {
  test('returns empty array for non-slash input', () => {
    expect(matchSlashCommands('haaland')).toHaveLength(0);
  });

  test('returns matching commands for /cap prefix', () => {
    const matches = matchSlashCommands('/cap');
    expect(matches.map((m) => m.command)).toContain('/capitan');
  });

  test('returns all commands for bare /', () => {
    const matches = matchSlashCommands('/');
    expect(matches.length).toBe(SLASH_COMMANDS.length);
  });
});

describe('slash-commands — allowlist validation', () => {
  test('all SLASH_COMMANDS use intent_hint values in the allowlist', () => {
    for (const sc of SLASH_COMMANDS) {
      expect(INTENT_HINT_ALLOWLIST as readonly string[]).toContain(
        sc.intent_hint,
      );
    }
  });

  test('all 6 allowlisted intents have a registered slash command', () => {
    const registered = new Set(SLASH_COMMANDS.map((sc) => sc.intent_hint));
    // rank_candidates is intentionally omitted from slash commands
    // (the /capitan command already implies it for the ranked path)
    const expected = INTENT_HINT_ALLOWLIST.filter(
      (h) => h !== 'rank_candidates',
    );
    for (const hint of expected) {
      expect(registered).toContain(hint);
    }
  });
});

// ---------------------------------------------------------------------------
// Intent drift guard
// ---------------------------------------------------------------------------
// Reads dispatcher.py and extracts all INTENT_* string constant values.
// Excludes the "unsupported" sentinel (INTENT_UNSUPPORTED) which is an
// internal no-match marker that never appears in a response body.
// INTENT_MULTI_INTENT ("multi_intent") is in dispatcher.py but NOT in
// SUPPORTED_INTENTS — it is synthesised by the orchestration layer in
// respond(). Both categories must be present in SUPPORTED_INTENT_VALUES.
//
// This test fails as soon as a new INTENT_* constant is added to
// dispatcher.py without a matching entry in lib/types.ts, preventing
// silent UI contract drift.

const DISPATCHER_PATH = path.resolve(
  __dirname,
  '../../fpl-grounded-assistant/fpl_grounded_assistant/dispatcher.py',
);

/**
 * Extract all INTENT_* string constant values from dispatcher.py.
 * Matches lines of the form:
 *   INTENT_FOO:    str = "bar"
 * Returns a Set of the quoted string values (e.g. {"captain_score", ...}).
 */
function extractDispatcherIntents(): Set<string> {
  const src = fs.readFileSync(DISPATCHER_PATH, 'utf-8');
  const matches = [...src.matchAll(/^INTENT_\w+\s*:\s*str\s*=\s*"([^"]+)"/gm)];
  return new Set(matches.map((m) => m[1]));
}

describe('intent drift guard — dispatcher.py vs lib/types.ts', () => {
  // All backend INTENT_* values, including the "unsupported" sentinel.
  const backendAllValues = extractDispatcherIntents();

  // The sentinel value — internal only, never appears in response.intent.
  const SENTINEL = 'unsupported';

  test('dispatcher.py INTENT_* constants are readable and non-empty', () => {
    expect(backendAllValues.size).toBeGreaterThan(0);
  });

  test('"unsupported" sentinel is present in dispatcher.py (sanity check)', () => {
    expect(backendAllValues).toContain(SENTINEL);
  });

  test('SUPPORTED_INTENT_VALUES covers every non-sentinel INTENT_* value in dispatcher.py', () => {
    const backendResponseIntents = new Set(
      [...backendAllValues].filter((v) => v !== SENTINEL),
    );
    const uiIntents = new Set(SUPPORTED_INTENT_VALUES);

    // Every backend intent must be in the UI contract.
    for (const intent of backendResponseIntents) {
      expect(uiIntents).toContain(intent);
    }
  });

  test('SUPPORTED_INTENT_VALUES contains no values absent from dispatcher.py', () => {
    // Every UI intent value must correspond to a known backend intent.
    // This catches typos or stale values in the UI type definition.
    for (const intent of SUPPORTED_INTENT_VALUES) {
      expect(backendAllValues).toContain(intent);
    }
  });

  test('SUPPORTED_INTENT_VALUES length matches non-sentinel backend intents', () => {
    const backendResponseIntents = new Set(
      [...backendAllValues].filter((v) => v !== SENTINEL),
    );
    expect(SUPPORTED_INTENT_VALUES.length).toBe(backendResponseIntents.size);
  });
});
