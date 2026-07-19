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
 *   zonal_opportunity  → DefensiveZonesCard (T4b)
 *   multi_intent       → MultiIntentView (bounded to one nesting level)
 *   @resource (metric) → ResourceRankingTable  (A2 post-graduation)
 *   @injuries          → InjuriesTable         (A2 post-graduation)
 *   injury_list        → InjuryListTable       (Track B — generic_card adapter)
 *   * (no bespoke match) → GenericCard         (Track B — generic_card fallback)
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
import FixtureOutlookCard from '@/components/intents/FixtureOutlookCard';
import DifferentialTable from '@/components/intents/DifferentialTable';
import TransferSuggestionCard from '@/components/intents/TransferSuggestionCard';
import DefensiveZonesCard from '@/components/intents/DefensiveZonesCard';
import MultiIntentView from '@/components/intents/MultiIntentView';
import ResourceRankingTable from '@/components/intents/ResourceRankingTable';
import InjuriesTable from '@/components/intents/InjuriesTable';
import InjuryListTable from '@/components/intents/InjuryListTable';
import GenericCard from '@/components/intents/GenericCard';
import WebSearchCard from '@/components/intents/WebSearchCard';

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
  if (view === 'fixture_outlook' && response.fixture_outlook != null) {
    return <FixtureOutlookCard data={response.fixture_outlook} />;
  }
  if (view === 'differential' && response.differential != null) {
    return <DifferentialTable data={response.differential} />;
  }
  if (view === 'transfer_suggestion' && response.transfer_suggestion != null) {
    return <TransferSuggestionCard data={response.transfer_suggestion} />;
  }
  if (view === 'multi_intent' && response.sub_responses != null) {
    return <MultiIntentView sub_responses={response.sub_responses} />;
  }
  if (view === 'defensive_zones' && response.zonal_opportunity != null) {
    return <DefensiveZonesCard data={response.zonal_opportunity} />;
  }
  if (view === 'resource_ranking' && response.resource_rows != null) {
    return <ResourceRankingTable data={response.resource_rows} />;
  }
  if (view === 'resource_injuries' && response.resource_rows != null) {
    return <InjuriesTable data={response.resource_rows} />;
  }
  if (view === 'generic_injuries' && response.generic_card != null) {
    return <InjuryListTable data={response.generic_card} />;
  }
  if (view === 'generic' && response.generic_card != null) {
    return <GenericCard data={response.generic_card} />;
  }
  if (view === 'web_search' && response.web_search != null) {
    return <WebSearchCard data={response.web_search} />;
  }
  return null;
}
