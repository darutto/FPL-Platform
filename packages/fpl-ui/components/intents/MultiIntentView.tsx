'use client';

/**
 * MultiIntentView — structured rendering for multi_intent OK turns.
 *
 * Rendered beneath final_text when:
 *   response.outcome      === 'ok'
 *   response.intent       === 'multi_intent'
 *   response.sub_responses is non-null and non-empty
 *
 * Each sub-response is rendered as a stacked sub-card containing:
 *   - the sub-response's final_text
 *   - its structured component (if applicable) via the same selectIntentView
 *     routing used by the top-level IntentRenderer
 *
 * BOUNDING RULE: recursion is explicitly stopped at one level.
 * Sub-responses whose selectIntentView returns 'multi_intent' are rendered
 * text-only. This prevents unbounded nesting and matches the backend
 * guarantee that sub_responses do not themselves contain sub_responses.
 */
import type { AskResponse } from '@/lib/types';
import { selectIntentView } from '@/lib/intent-renderer';
import CaptainCard from '@/components/intents/CaptainCard';
import ComparisonCard from '@/components/intents/ComparisonCard';
import RankingTable from '@/components/intents/RankingTable';
import TransferCard from '@/components/intents/TransferCard';
import ChipCard from '@/components/intents/ChipCard';
import FixtureRunTable from '@/components/intents/FixtureRunTable';
import DifferentialTable from '@/components/intents/DifferentialTable';

interface Props {
  sub_responses: AskResponse[];
}

export default function MultiIntentView({ sub_responses }: Props) {
  if (sub_responses.length === 0) return null;

  return (
    <div className="mt-3 space-y-3">
      {sub_responses.map((sub, idx) => (
        <SubCard key={`${sub.intent ?? 'unknown'}-${idx}`} response={sub} />
      ))}
    </div>
  );
}

function SubCard({ response }: { response: AskResponse }) {
  const view = selectIntentView(response);
  // Explicitly stop at one level — never recurse into multi_intent sub-cards.
  const safeView = view === 'multi_intent' ? null : view;

  return (
    <div className="rounded-card border border-white/10 bg-white/[0.03] p-3 space-y-2">
      <p className="text-sm text-bf-text/80 leading-relaxed">{response.final_text}</p>
      {safeView != null && renderSubView(safeView, response)}
    </div>
  );
}

function renderSubView(
  view: Exclude<ReturnType<typeof selectIntentView>, null | 'multi_intent'>,
  response: AskResponse,
): React.ReactNode {
  if (view === 'captain' && response.captain != null) {
    return <CaptainCard data={response.captain} />;
  }
  if (view === 'comparison' && response.comparison != null) {
    return <ComparisonCard data={response.comparison} />;
  }
  if (view === 'ranking' && response.captain_ranking != null) {
    return <RankingTable data={response.captain_ranking} />;
  }
  if (view === 'transfer' && response.transfer != null) {
    return <TransferCard data={response.transfer} />;
  }
  if (view === 'chip' && response.chip != null) {
    return <ChipCard data={response.chip} />;
  }
  if (view === 'fixture_run' && response.fixture_run != null) {
    return <FixtureRunTable data={response.fixture_run} />;
  }
  if (view === 'differential' && response.differential != null) {
    return <DifferentialTable data={response.differential} />;
  }
  return null;
}
