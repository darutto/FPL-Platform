'use client';

/**
 * WcIntentRenderer — renders the structured WC card beneath final_text.
 *
 * Thin React wrapper around lib/wc-intent-renderer.ts selectWcIntentView().
 * Sibling of components/chat/IntentRenderer.tsx for the World Cup domain.
 * Returns null (renders nothing) for text-only turns.
 *
 * RENDERED (Iteration 3):
 *   standings           → WcStandingsTable
 *   top_scorers         → WcScorersTable
 *   top_assists         → WcAssistsTable
 *   fantasy_top_players → WcFantasyTable
 *   players_info        → WcPlayerInfoCard (1 = profile, 2+ = comparison)
 *   squad               → WcSquadTable
 *   head_to_head        → WcHeadToHeadTable
 *   wc2022_results      → WcFixturesTable (title="Mundial 2022")
 *   fixtures            → WcFixturesTable
 *   web_search          → WcWebSearchCard (unverified · "Búsqueda web + IA")
 */
import type { WcAskResponse } from '@/lib/wc-types';
import { selectWcIntentView } from '@/lib/wc-intent-renderer';
import WcStandingsTable from './WcStandingsTable';
import WcScorersTable from './WcScorersTable';
import WcAssistsTable from './WcAssistsTable';
import WcFantasyTable from './WcFantasyTable';
import WcPlayerInfoCard from './WcPlayerInfoCard';
import WcSquadTable from './WcSquadTable';
import WcHeadToHeadTable from './WcHeadToHeadTable';
import WcFixturesTable from './WcFixturesTable';
import WcWebSearchCard from './WcWebSearchCard';

interface Props {
  response: WcAskResponse;
}

export default function WcIntentRenderer({ response }: Props) {
  const view = selectWcIntentView(response);

  if (view === 'standings' && response.standings != null) {
    return <WcStandingsTable data={response.standings} />;
  }
  if (view === 'top_scorers' && response.top_scorers != null) {
    return <WcScorersTable data={response.top_scorers} />;
  }
  if (view === 'top_assists' && response.top_assists != null) {
    return <WcAssistsTable data={response.top_assists} />;
  }
  if (view === 'fantasy_top_players' && response.fantasy_top_players != null) {
    return <WcFantasyTable data={response.fantasy_top_players} />;
  }
  if (view === 'players_info' && response.players_info != null) {
    return <WcPlayerInfoCard data={response.players_info} wc2022Stats={response.wc2022_stats} />;
  }
  if (view === 'squad' && response.squad != null) {
    return <WcSquadTable data={response.squad} />;
  }
  if (view === 'head_to_head' && response.head_to_head != null) {
    return <WcHeadToHeadTable data={response.head_to_head} />;
  }
  if (view === 'wc2022_results' && response.wc2022_results != null) {
    return <WcFixturesTable data={response.wc2022_results} title="Mundial 2022" />;
  }
  if (view === 'fixtures' && response.fixtures != null) {
    return <WcFixturesTable data={response.fixtures} />;
  }
  if (view === 'web_search' && response.web_search != null) {
    return <WcWebSearchCard data={response.web_search} />;
  }
  return null;
}
