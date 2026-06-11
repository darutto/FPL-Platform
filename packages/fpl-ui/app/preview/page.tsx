/**
 * /preview — TEMPORARY dev-only gallery of every intent card (Track 3 U1).
 *
 * Renders all 10 intent components from the Jest fixtures so the re-skin can
 * be visually verified against the Stitch screens without driving the
 * backend.
 *
 * ⚠ DELETE THIS ROUTE BEFORE MERGING THE RE-SKIN BRANCH (Phase 4).
 */
import type { ResourceRows } from '@/lib/types';
import CaptainCard from '@/components/intents/CaptainCard';
import ComparisonCard from '@/components/intents/ComparisonCard';
import RankingTable from '@/components/intents/RankingTable';
import TransferCard from '@/components/intents/TransferCard';
import ChipCard from '@/components/intents/ChipCard';
import FixtureRunTable from '@/components/intents/FixtureRunTable';
import InjuriesTable from '@/components/intents/InjuriesTable';
import ResourceRankingTable from '@/components/intents/ResourceRankingTable';
import DifferentialTable from '@/components/intents/DifferentialTable';
import MultiIntentView from '@/components/intents/MultiIntentView';
import {
  captainOkResponse,
  captainUpsideResponse,
  comparisonOkResponse,
  comparisonTiedResponse,
  rankingOkResponse,
  transferOkResponse,
  transferHoldResponse,
  chipOkResponse,
  chipWildcardResponse,
  chipMissingContextResponse,
  chipUnavailableResponse,
  fixtureRunDgwResponse,
  differentialOkResponse,
  multiIntentOkResponse,
} from '@/__tests__/fixtures/sample-responses';

// Inline resource fixtures — sample-responses.ts predates resource_rows.
const injuriesRows: ResourceRows = {
  resource: 'injuries',
  title: 'Lesionados y en duda',
  columns: ['Jugador', 'Estado', '%', 'Noticia'],
  rows: [
    {
      web_name: 'Saliba',
      team_short: 'ARS',
      position: 'DEF',
      status_label: 'Injured',
      chance_of_playing: 0,
      news: 'Lesión muscular — baja confirmada para la próxima jornada.',
      news_added: new Date(Date.now() - 2 * 86400000).toISOString(),
    },
    {
      web_name: 'Bowen',
      team_short: 'WHU',
      position: 'MID',
      status_label: 'Doubtful 75%',
      chance_of_playing: 75,
      news: 'Molestias en el tobillo, evaluación día a día.',
      news_added: new Date(Date.now() - 86400000).toISOString(),
    },
    {
      web_name: 'Maddison',
      team_short: 'TOT',
      position: 'MID',
      status_label: 'Available',
      chance_of_playing: 100,
      news: 'Recuperado — disponible para el próximo partido.',
      news_added: new Date().toISOString(),
    },
  ],
};

const topFormRows: ResourceRows = {
  resource: 'top_form',
  title: 'Jugadores en racha',
  columns: ['Jugador', 'Equipo', 'Posición', 'Forma'],
  rows: [
    { web_name: 'Haaland', team_short: 'MCI', position: 'FWD', value: 9.2 },
    { web_name: 'Palmer', team_short: 'CHE', position: 'MID', value: 8.8 },
    { web_name: 'Saka', team_short: 'ARS', position: 'MID', value: 8.4 },
    { web_name: 'Salah', team_short: 'LIV', position: 'MID', value: 8.0 },
    { web_name: 'Watkins', team_short: 'AVL', position: 'FWD', value: 7.6 },
  ],
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-xs font-bold uppercase tracking-widest text-bf-gray">{title}</h2>
      {children}
    </section>
  );
}

export default function PreviewPage() {
  return (
    <main className="mx-auto max-w-2xl space-y-8 px-4 py-8">
      <header className="space-y-1">
        <h1 className="text-lg font-extrabold text-white">Preview — intent cards</h1>
        <p className="text-xs text-bf-gray">
          Ruta temporal de desarrollo (Track 3 U1). Eliminar antes de merge.
        </p>
      </header>

      <Section title="CaptainCard — safe / upside">
        <CaptainCard data={captainOkResponse.captain!} />
        <CaptainCard data={captainUpsideResponse.captain!} />
      </Section>

      <Section title="ComparisonCard — winner / tied">
        <ComparisonCard data={comparisonOkResponse.comparison!} />
        <ComparisonCard data={comparisonTiedResponse.comparison!} />
      </Section>

      <Section title="RankingTable">
        <RankingTable data={rankingOkResponse.captain_ranking!} />
      </Section>

      <Section title="TransferCard — fichar / conservar">
        <TransferCard data={transferOkResponse.transfer!} />
        <TransferCard data={transferHoldResponse.transfer!} />
      </Section>

      <Section title="ChipCard — favorable / marginal / sin datos / no disponible">
        <ChipCard data={chipOkResponse.chip!} />
        <ChipCard data={chipWildcardResponse.chip!} />
        <ChipCard data={chipMissingContextResponse.chip!} />
        <ChipCard data={chipUnavailableResponse.chip!} />
      </Section>

      <Section title="FixtureRunTable — DGW (ramp FDR V2 intacto)">
        <FixtureRunTable data={fixtureRunDgwResponse.fixture_run!} />
      </Section>

      <Section title="InjuriesTable">
        <InjuriesTable data={injuriesRows} />
      </Section>

      <Section title="ResourceRankingTable — top_form">
        <ResourceRankingTable data={topFormRows} />
      </Section>

      <Section title="DifferentialTable">
        <DifferentialTable data={differentialOkResponse.differential!} />
      </Section>

      <Section title="MultiIntentView">
        <MultiIntentView sub_responses={multiIntentOkResponse.sub_responses!} />
      </Section>
    </main>
  );
}
