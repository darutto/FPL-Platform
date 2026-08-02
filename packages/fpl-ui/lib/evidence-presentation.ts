import {
  EVIDENCE_CODES,
  EVIDENCE_DIRECTION_VALUES,
  EVIDENCE_SUBJECT_TYPE_VALUES,
  SIGNAL_BASIS_VALUES,
  type EvidenceDirection,
  type EvidenceItem,
  type SignalBasis,
} from './evidence';

export const BASIS_LABELS: Readonly<Record<SignalBasis, string>> = {
  observed: 'Observado',
  inferred_proxy: 'Proxy inferido',
};

export const DIRECTION_LABELS: Readonly<Record<EvidenceDirection, string>> = {
  positive: 'Positivo',
  negative: 'Negativo',
  neutral: 'Neutral',
};

function isNonBlankString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isFiniteInRange(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= minimum && value <= maximum;
}

function isUtcIsoTimestamp(value: unknown): value is string {
  if (!isNonBlankString(value)) return false;
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/.test(value)) return false;
  return Number.isFinite(Date.parse(value));
}

export function isEvidenceItem(value: unknown): value is EvidenceItem {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;

  const item = value as Record<string, unknown>;
  if (!isNonBlankString(item.code) || !(EVIDENCE_CODES as readonly string[]).includes(item.code)) return false;
  if (!isNonBlankString(item.label)) return false;
  if (!isNonBlankString(item.subject_type) || !(EVIDENCE_SUBJECT_TYPE_VALUES as readonly string[]).includes(item.subject_type)) return false;
  if (!isNonBlankString(item.subject_id)) return false;
  if (item.fixture_id !== null && !isNonBlankString(item.fixture_id)) return false;
  if (!isFiniteInRange(item.impact, -10, 10)) return false;
  if (!isNonBlankString(item.direction) || !(EVIDENCE_DIRECTION_VALUES as readonly string[]).includes(item.direction)) return false;
  const expectedDirection = item.impact > 0 ? 'positive' : item.impact < 0 ? 'negative' : 'neutral';
  if (item.direction !== expectedDirection) return false;
  if (!isFiniteInRange(item.confidence, 0, 1)) return false;
  if (!isNonBlankString(item.basis) || !(SIGNAL_BASIS_VALUES as readonly string[]).includes(item.basis)) return false;
  if (!isNonBlankString(item.summary)) return false;
  if (!Array.isArray(item.source_features) || !item.source_features.every(isNonBlankString)) return false;
  if (!isNonBlankString(item.model_version)) return false;
  if (!isUtcIsoTimestamp(item.calculated_at)) return false;
  return true;
}

export function canonicalEvidenceSerialization(item: EvidenceItem): string {
  return JSON.stringify({
    code: item.code,
    label: item.label,
    subject_type: item.subject_type,
    subject_id: item.subject_id,
    fixture_id: item.fixture_id,
    impact: item.impact,
    direction: item.direction,
    confidence: item.confidence,
    basis: item.basis,
    summary: item.summary,
    source_features: item.source_features,
    model_version: item.model_version,
    calculated_at: item.calculated_at,
  });
}

export interface PreparedEvidenceItem {
  readonly item: EvidenceItem;
  readonly key: string;
}

export function prepareEvidenceItems(evidence: readonly unknown[]): PreparedEvidenceItem[] {
  const occurrences = new Map<string, number>();
  const prepared: PreparedEvidenceItem[] = [];

  for (const candidate of evidence) {
    if (!isEvidenceItem(candidate)) continue;
    const serialized = canonicalEvidenceSerialization(candidate);
    const occurrence = occurrences.get(serialized) ?? 0;
    occurrences.set(serialized, occurrence + 1);
    prepared.push({ item: candidate, key: `${serialized}#${occurrence}` });
  }
  return prepared;
}
