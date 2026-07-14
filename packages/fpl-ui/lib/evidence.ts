/** FI-1 provider-neutral structured evidence mirror. Not yet on AskResponse. */

export const SIGNAL_BASIS_VALUES = ['observed', 'inferred_proxy'] as const;
export type SignalBasis = (typeof SIGNAL_BASIS_VALUES)[number];

export const EVIDENCE_DIRECTION_VALUES = ['positive', 'negative', 'neutral'] as const;
export type EvidenceDirection = (typeof EVIDENCE_DIRECTION_VALUES)[number];

export const EVIDENCE_SUBJECT_TYPE_VALUES = ['player', 'team', 'fixture'] as const;
export type EvidenceSubjectType = (typeof EVIDENCE_SUBJECT_TYPE_VALUES)[number];

export const EVIDENCE_CODES = [
  'MINUTES_CONFIDENCE_HIGH',
  'MINUTES_CONFIDENCE_LOW',
  'ROTATION_RISK',
  'CAMEO_RISK',
  'ROLE_STABLE',
  'ROLE_CHANGED',
  'OUT_OF_POSITION',
  'OPPONENT_FLANK_WEAKNESS',
  'OPPONENT_UNIT_DISRUPTION',
  'FIXTURE_CONGESTION',
  'REST_ADVANTAGE',
  'SET_PIECE_ROLE',
  'AVAILABILITY_DOUBT',
] as const;
export type EvidenceCode = (typeof EVIDENCE_CODES)[number];

export const EVIDENCE_FIELD_NAMES = [
  'code',
  'label',
  'subject_type',
  'subject_id',
  'fixture_id',
  'impact',
  'direction',
  'confidence',
  'basis',
  'summary',
  'source_features',
  'model_version',
  'calculated_at',
] as const;

export const EVIDENCE_NULLABLE_FIELDS = ['fixture_id'] as const;

export interface EvidenceItem {
  readonly code: EvidenceCode;
  readonly label: string;
  readonly subject_type: EvidenceSubjectType;
  readonly subject_id: string;
  readonly fixture_id: string | null;
  readonly impact: number;
  readonly direction: EvidenceDirection;
  readonly confidence: number;
  readonly basis: SignalBasis;
  readonly summary: string;
  readonly source_features: readonly string[];
  readonly model_version: string;
  /** UTC ISO-8601 timestamp. */
  readonly calculated_at: string;
}
