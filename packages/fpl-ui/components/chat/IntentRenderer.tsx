'use client';

/**
 * IntentRenderer — renders the structured component beneath final_text.
 *
 * Thin React wrapper around lib/intent-renderer.ts selectIntentView().
 * Returns null (renders nothing) for text-only turns.
 *
 * RENDERED (Phase 2d):
 *   captain_score      → CaptainCard
 *   compare_players    → ComparisonCard
 *   rank_candidates    → RankingTable
 *   transfer_advice    → TransferCard
 *   chip_advice        → ChipCard
 *   player_fixture_run → FixtureRunTable
 *   differential_picks → DifferentialTable
 *   multi_intent       → MultiIntentView (bounded to one nesting level)
 *   @resource (metric) → ResourceRankingTable  (A2 post-graduation)
 *   @injuries          → InjuriesTable         (A2 post-graduation)
 *
 * TEXT-ONLY (Phase 2d — structured rendering deferred):
 *   current_gameweek, player_summary, player_resolve
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
import MultiIntentView from '@/components/intents/MultiIntentView';
import ResourceRankingTable from '@/components/intents/ResourceRankingTable';
import InjuriesTable from '@/components/intents/InjuriesTable';

interface Props {
  response: AskResponse;
}

export default function IntentRenderer({ response }: Props) {
  const view = selectIntentView(response);

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
  if (view === 'multi_intent' && response.sub_responses != null) {
    return <MultiIntentView sub_responses={response.sub_responses} />;
  }
  if (view === 'resource_ranking' && response.resource_rows != null) {
    return <ResourceRankingTable data={response.resource_rows} />;
  }
  if (view === 'resource_injuries' && response.resource_rows != null) {
    return <InjuriesTable data={response.resource_rows} />;
  }
  return null;
}
