/**
 * @jest-environment jsdom
 */
import fs from 'node:fs';
import path from 'node:path';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import ConfidenceBadge from '../components/intelligence/ConfidenceBadge';
import EvidenceBoundary from '../components/intelligence/EvidenceBoundary';
import EvidenceChip from '../components/intelligence/EvidenceChip';
import EvidenceList from '../components/intelligence/EvidenceList';
import MessageList, { type Message } from '../components/chat/MessageList';
import MultiIntentView from '../components/intents/MultiIntentView';
import {
  canonicalEvidenceSerialization,
  isEvidenceItem,
  prepareEvidenceItems,
} from '../lib/evidence-presentation';
import type { EvidenceItem } from '../lib/evidence';
import type { AskResponse } from '../lib/types';
import { captainOkResponse, unsupportedResponse } from './fixtures/sample-responses';

const BASE_EVIDENCE: EvidenceItem = {
  code: 'ROLE_STABLE',
  label: 'Rol estable',
  subject_type: 'player',
  subject_id: 'player_internal_123',
  fixture_id: 'fixture_internal_456',
  impact: 0,
  direction: 'neutral',
  confidence: 0.8,
  basis: 'observed',
  summary: 'El rol reciente se mantiene estable.',
  source_features: ['role_distribution_last_10', 'role_stability'],
  model_version: 'tactical-role-v1',
  calculated_at: '2026-08-01T12:00:00Z',
};

function evidence(label: string, overrides: Partial<EvidenceItem> = {}): EvidenceItem {
  return { ...BASE_EVIDENCE, label, summary: `Resumen ${label}`, ...overrides };
}

function textResponse(items?: EvidenceItem[] | null): AskResponse {
  return {
    ...unsupportedResponse,
    final_text: 'Respuesta principal sin tarjeta.',
    outcome: 'ok',
    supported: true,
    intent: 'current_gameweek',
    evidence: items,
  };
}

function assistantMessage(response: AskResponse, id = 'assistant-1'): Message {
  return {
    id,
    role: 'assistant',
    text: response.final_text,
    outcome: response.outcome,
    response,
  };
}

beforeAll(() => {
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    value: jest.fn(),
  });
});

describe('EvidenceList — order, completeness, validation, and semantics', () => {
  test('preserves backend order, including reversed input, and retains exact duplicates', () => {
    const first = evidence('Primero');
    const second = evidence('Segundo', { code: 'ROLE_CHANGED' });
    const { rerender } = render(<EvidenceList evidence={[first, second, first]} />);

    expect(screen.getAllByRole('listitem').map((node) => node.textContent)).toEqual([
      expect.stringContaining('Primero'),
      expect.stringContaining('Segundo'),
      expect.stringContaining('Primero'),
    ]);

    rerender(<EvidenceList evidence={[second, first]} />);
    expect(screen.getAllByRole('listitem').map((node) => node.textContent)).toEqual([
      expect.stringContaining('Segundo'),
      expect.stringContaining('Primero'),
    ]);
  });

  test('renders every received valid item and does not impose a frontend cap', () => {
    const items = Array.from({ length: 9 }, (_, index) => evidence(`Señal ${index + 1}`));
    render(<EvidenceList evidence={items} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(9);
    expect(screen.getByText('Señal 9')).toBeInTheDocument();
  });

  test.each([
    ['undefined', undefined],
    ['null', null],
    ['empty', []],
  ] as const)('%s evidence renders nothing', (_name, value) => {
    const { container } = render(<EvidenceList evidence={value} />);
    expect(container).toBeEmptyDOMElement();
  });

  test('skips each malformed item while retaining valid siblings; all-invalid renders nothing', () => {
    const invalid = { ...BASE_EVIDENCE, confidence: 2 } as EvidenceItem;
    const { rerender, container } = render(
      <EvidenceList evidence={[invalid, evidence('Válida')]} />,
    );
    expect(screen.queryByText('Rol estable')).not.toBeInTheDocument();
    expect(screen.getByText('Válida')).toBeInTheDocument();

    rerender(<EvidenceList evidence={[invalid]} />);
    expect(container).toBeEmptyDOMElement();
  });

  test('renders source features in received order and the exact empty fallback', () => {
    const { rerender } = render(
      <EvidenceList evidence={[evidence('Orden de fuentes', { source_features: ['z_feature', 'a_feature'] })]} />,
    );
    expect(screen.getByText('Fuentes: z_feature · a_feature')).toBeInTheDocument();

    rerender(<EvidenceList evidence={[evidence('Sin fuentes', { source_features: [] })]} />);
    expect(screen.getByText('Fuentes: no indicadas')).toBeInTheDocument();
  });

  test('retains a governed zero-confidence item instead of treating zero as absent', () => {
    render(<EvidenceList evidence={[evidence('Cero válido', { confidence: 0 })]} />);
    expect(screen.getByText('Cero válido')).toBeInTheDocument();
    expect(screen.getByText('Confianza 0%')).toBeVisible();
  });

  test('uses an accessible heading relationship and semantic list/listitem markup', () => {
    render(<EvidenceList evidence={[BASE_EVIDENCE]} />);
    const heading = screen.getByRole('heading', { name: 'Evidencia' });
    const section = heading.closest('section');
    expect(section).toHaveAttribute('aria-labelledby', heading.id);
    expect(within(section!).getByRole('list')).toBeInTheDocument();
    expect(within(section!).getAllByRole('listitem')).toHaveLength(1);
  });

  test('pins exact responsive classes, DOM order, wrapping, and absence of column/masonry flow', () => {
    render(<EvidenceList evidence={[evidence('Uno'), evidence('Dos')]} />);
    const list = screen.getByRole('list');
    expect(list).toHaveClass('grid-cols-1', 'sm:grid-cols-2');
    expect(list.className).not.toMatch(/columns-|masonry|grid-flow-col/);
    expect(screen.getAllByRole('listitem').map((node) => node.textContent?.includes('Uno'))).toEqual([true, false]);
    for (const row of screen.getAllByRole('listitem')) expect(row).toHaveClass('min-w-0');
    expect(screen.getByText('Resumen Uno')).toHaveClass('break-words');
  });

  test('stable keys use canonical full-item serialization plus occurrence ordinal without deleting duplicates', () => {
    const duplicate = evidence('Duplicada');
    const prepared = prepareEvidenceItems([duplicate, duplicate]);
    expect(prepared).toHaveLength(2);
    expect(prepared[0].key).toBe(`${canonicalEvidenceSerialization(duplicate)}#0`);
    expect(prepared[1].key).toBe(`${canonicalEvidenceSerialization(duplicate)}#1`);
    expect(prepareEvidenceItems([duplicate, duplicate]).map((item) => item.key)).toEqual(prepared.map((item) => item.key));
  });
});

describe('EvidenceChip and ConfidenceBadge presentation', () => {
  test('renders approved visible fields and hides internal metadata', () => {
    const { container } = render(<EvidenceChip item={BASE_EVIDENCE} />);
    expect(screen.getByText('Rol estable')).toBeInTheDocument();
    expect(screen.getByText(BASE_EVIDENCE.summary)).toBeInTheDocument();
    expect(screen.getByText('Base: Observado')).toBeInTheDocument();
    expect(screen.getByText('Dirección: Neutral')).toBeInTheDocument();
    expect(screen.getByText(/Fuentes:/)).toBeInTheDocument();
    expect(container).not.toHaveTextContent(BASE_EVIDENCE.subject_id);
    expect(container).not.toHaveTextContent(BASE_EVIDENCE.fixture_id!);
    expect(container).not.toHaveTextContent(BASE_EVIDENCE.model_version);
    expect(container).not.toHaveTextContent(BASE_EVIDENCE.calculated_at);
    expect(container).not.toHaveTextContent('ROLE_STABLE');
  });

  test('uses every closed basis/direction label with text independent of color', () => {
    const { rerender } = render(<EvidenceChip item={BASE_EVIDENCE} />);
    expect(screen.getByText('Base: Observado')).toBeVisible();
    expect(screen.getByText('Dirección: Neutral')).toBeVisible();

    rerender(<EvidenceChip item={evidence('Proxy positivo', {
      impact: 2,
      direction: 'positive',
      basis: 'inferred_proxy',
    })} />);
    expect(screen.getByText('Base: Proxy inferido')).toBeVisible();
    expect(screen.getByText('Dirección: Positivo')).toBeVisible();

    rerender(<EvidenceChip item={evidence('Negativo', { impact: -2, direction: 'negative' })} />);
    expect(screen.getByText('Dirección: Negativo')).toBeVisible();
  });

  test('is presentational, nonfocusable, has no tooltip-only content, and wraps long text', () => {
    const longLabel = 'Una etiqueta de evidencia muy larga que debe permanecer completa y accesible';
    const { container } = render(<EvidenceChip item={evidence(longLabel)} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    expect(container.querySelector('[tabindex]')).toBeNull();
    expect(container.querySelector('[title]')).toBeNull();
    expect(screen.getByText(longLabel)).toHaveClass('break-words');
    expect(container.firstElementChild).toHaveClass('min-w-0');
  });

  test.each([
    [0, 'Confianza 0%'],
    [0.555, 'Confianza 56%'],
    [1, 'Confianza 100%'],
  ])('renders numeric confidence %s without thresholds', (value, expected) => {
    const { container } = render(<ConfidenceBadge confidence={value as number} />);
    expect(screen.getByText(expected as string)).toBeVisible();
    expect(container).not.toHaveTextContent(/baja|media|alta|low|medium|high/i);
  });

  test.each([-0.1, 1.1, Number.NaN, Number.POSITIVE_INFINITY])(
    'does not clamp malformed confidence %s; validation skips the full item',
    (confidence) => {
      const invalid = { ...BASE_EVIDENCE, confidence } as EvidenceItem;
      const { container } = render(<EvidenceList evidence={[invalid]} />);
      expect(container).toBeEmptyDOMElement();
    },
  );
});

describe('EvidenceItem structural validation', () => {
  test('accepts the governed item and rejects direction/sign contradictions', () => {
    expect(isEvidenceItem(BASE_EVIDENCE)).toBe(true);
    expect(isEvidenceItem({ ...BASE_EVIDENCE, impact: 1, direction: 'neutral' })).toBe(false);
  });

  test.each([
    ['blank label', { label: ' ' }],
    ['unknown code', { code: 'UNKNOWN_CODE' }],
    ['unknown subject', { subject_type: 'coach' }],
    ['blank subject id', { subject_id: '' }],
    ['blank fixture id', { fixture_id: '' }],
    ['impact under range', { impact: -11, direction: 'negative' }],
    ['impact nonfinite', { impact: Number.NaN }],
    ['unknown basis', { basis: 'guessed' }],
    ['unknown direction', { direction: 'up' }],
    ['non-array sources', { source_features: 'feature' }],
    ['blank source', { source_features: [''] }],
    ['invalid timestamp', { calculated_at: 'yesterday' }],
    ['non-UTC timestamp', { calculated_at: '2026-08-01T12:00:00+01:00' }],
  ])('rejects %s', (_name, overrides) => {
    expect(isEvidenceItem({ ...BASE_EVIDENCE, ...overrides })).toBe(false);
  });
});

describe('response ownership across stateless, session, replay, and multi-intent paths', () => {
  test('renders stateless text evidence after final text without reconstructing intent eligibility', () => {
    const response = textResponse([evidence('Texto FI')]);
    render(<MessageList messages={[assistantMessage(response)]} loading={false} />);
    expect(screen.getByText(response.final_text)).toBeInTheDocument();
    expect(screen.getByText('Texto FI')).toBeInTheDocument();
  });

  test('renders structured-card evidence once while preserving card content', () => {
    const response: AskResponse = { ...captainOkResponse, evidence: [evidence('Tarjeta FI')] };
    render(<MessageList messages={[assistantMessage(response)]} loading={false} />);
    expect(screen.getByText(response.captain!.web_name)).toBeInTheDocument();
    expect(screen.getAllByText('Tarjeta FI')).toHaveLength(1);
  });

  test('session-shaped and replayed responses use the same local renderer and stable item sequence', () => {
    const response = { ...textResponse([evidence('Sesión FI')]), session_id: 'session-1' };
    const { rerender } = render(<MessageList messages={[assistantMessage(response)]} loading={false} />);
    const first = screen.getAllByRole('listitem').map((node) => node.textContent);
    rerender(<MessageList messages={[assistantMessage(response)]} loading={false} />);
    expect(screen.getAllByRole('listitem').map((node) => node.textContent)).toEqual(first);
  });

  test('never renders parent evidence; child evidence remains separate and ordered', () => {
    const shared = evidence('Compartida');
    const childOne = textResponse([shared, evidence('Hija uno')]);
    const childTwo = textResponse([shared]);
    const childWithout = textResponse(null);
    const parent: AskResponse = {
      ...textResponse([evidence('Padre prohibido')]),
      intent: 'multi_intent',
      sub_responses: [childOne, childWithout, childTwo],
    };

    render(<MessageList messages={[assistantMessage(parent)]} loading={false} />);
    expect(screen.queryByText('Padre prohibido')).not.toBeInTheDocument();
    expect(screen.getAllByRole('heading', { name: 'Evidencia' })).toHaveLength(2);
    expect(screen.getAllByText('Compartida')).toHaveLength(2);
    expect(screen.getByText('Hija uno')).toBeInTheDocument();
    expect(screen.getAllByText('Respuesta principal sin tarjeta.')).toHaveLength(3);
  });

  test('MultiIntentView ignores no child, does not merge lists, and preserves child order', () => {
    const children = [textResponse([evidence('Primera hija')]), textResponse([evidence('Segunda hija')])];
    const { container } = render(<MultiIntentView sub_responses={children} />);
    expect(screen.getAllByRole('heading', { name: 'Evidencia' })).toHaveLength(2);
    expect(Array.from(container.querySelectorAll('h3')).map((node) => node.parentElement?.textContent)).toEqual([
      expect.stringContaining('Primera hija'),
      expect.stringContaining('Segunda hija'),
    ]);
  });
});

describe('error, network, and feature-flag isolation', () => {
  test('contains a throwing evidence subtree while preserving the primary response with null fallback', () => {
    const fetchSpy = jest.fn();
    Object.defineProperty(globalThis, 'fetch', { configurable: true, writable: true, value: fetchSpy });
    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => undefined);
    function ThrowingEvidence(): never {
      throw new Error('evidence render failure');
    }

    const { container } = render(
      <div>
        <p>Respuesta principal intacta</p>
        <EvidenceBoundary><ThrowingEvidence /></EvidenceBoundary>
      </div>,
    );
    expect(screen.getByText('Respuesta principal intacta')).toBeInTheDocument();
    expect(container).not.toHaveTextContent('evidence render failure');
    expect(fetchSpy).not.toHaveBeenCalled();
    consoleSpy.mockRestore();
    delete (globalThis as { fetch?: typeof fetch }).fetch;
  });

  test('rendering evidence performs no fetch or hydration-time request', () => {
    const fetchSpy = jest.fn();
    Object.defineProperty(globalThis, 'fetch', { configurable: true, writable: true, value: fetchSpy });
    const { rerender } = render(<EvidenceList evidence={[BASE_EVIDENCE]} />);
    rerender(<EvidenceList evidence={[BASE_EVIDENCE]} />);
    expect(fetchSpy).not.toHaveBeenCalled();
    delete (globalThis as { fetch?: typeof fetch }).fetch;
  });

  test('bounded implementation files contain no API/runtime imports, FI flag read, viewport JS, or resource work', () => {
    const roots = [
      '../components/intelligence/EvidenceList.tsx',
      '../components/intelligence/EvidenceChip.tsx',
      '../components/intelligence/ConfidenceBadge.tsx',
      '../components/intelligence/EvidenceBoundary.tsx',
      '../lib/evidence-presentation.ts',
    ];
    const source = roots.map((relative) => fs.readFileSync(path.resolve(__dirname, relative), 'utf8')).join('\n');
    expect(source).not.toMatch(/\bfetch\s*\(|\bask\s*\(|sessionAsk|football_intelligence|FOOTBALL_INTELLIGENCE_ENABLED/);
    expect(source).not.toMatch(/matchMedia|innerWidth|ResizeObserver|@minutes|@role/);
    expect(source).not.toMatch(/columns-|masonry|grid-flow-col/);
  });
});
