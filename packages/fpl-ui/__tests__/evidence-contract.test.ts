import * as fs from 'fs';
import * as path from 'path';

import {
  EVIDENCE_CODES,
  EVIDENCE_DIRECTION_VALUES,
  EVIDENCE_FIELD_NAMES,
  EVIDENCE_NULLABLE_FIELDS,
  EVIDENCE_SUBJECT_TYPE_VALUES,
  SIGNAL_BASIS_VALUES,
  type EvidenceItem,
} from '../lib/evidence';


const PYTHON_ROOT = path.resolve(
  __dirname,
  '../../football-data-contract/football_data_contract',
);

function normalizeLineEndings(source: string): string {
  return source.replace(/\r\n/g, '\n');
}

function readNormalizedSource(sourcePath: string): string {
  return normalizeLineEndings(fs.readFileSync(sourcePath, 'utf8'));
}

const evidencePython = readNormalizedSource(path.join(PYTHON_ROOT, 'evidence.py'));
const enumsPython = readNormalizedSource(path.join(PYTHON_ROOT, 'enums.py'));
const evidenceTypescript = readNormalizedSource(
  path.resolve(__dirname, '../lib/evidence.ts'),
);

function pythonTuple(name: string): string[] {
  const match = evidencePython.match(
    new RegExp(`${name}\\s*=\\s*\\(([\\s\\S]*?)\\n\\)`),
  );
  if (!match) throw new Error(`Python tuple ${name} not found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map((item) => item[1]);
}

function pythonEvidenceCodes(): string[] {
  const match = evidencePython.match(/EVIDENCE_CODES\s*=\s*frozenset\([\s\S]*?\{([\s\S]*?)\}\s*\)/);
  if (!match) throw new Error('Python EVIDENCE_CODES not found');
  return [...match[1].matchAll(/"([A-Z_]+)"/g)].map((item) => item[1]);
}

function pythonEnumValues(className: string, source = enumsPython): string[] {
  const match = source.match(
    new RegExp(`class ${className}\\(StrEnum\\):([\\s\\S]*?)(?=\\n\\nclass |$)`),
  );
  if (!match) throw new Error(`Python enum ${className} not found`);
  return [...match[1].matchAll(/=\s*"([^"]+)"/g)].map((item) => item[1]);
}

function typescriptInterfaceFields(): string[] {
  const match = evidenceTypescript.match(/export interface EvidenceItem \{([\s\S]*?)\n\}/);
  if (!match) throw new Error('TypeScript EvidenceItem not found');
  return [...match[1].matchAll(/^\s*readonly\s+(\w+)\??:/gm)].map((item) => item[1]);
}

describe('FI-1 Python/TypeScript evidence parity', () => {
  test('source normalization converts CRLF once at the read boundary', () => {
    expect(normalizeLineEndings('first\r\n\r\nclass Next')).toBe('first\n\nclass Next');
    expect(evidencePython).not.toContain('\r\n');
    expect(enumsPython).not.toContain('\r\n');
    expect(evidenceTypescript).not.toContain('\r\n');
  });

  test('field names and order match exactly', () => {
    const expected = pythonTuple('EVIDENCE_FIELD_NAMES');
    expect(EVIDENCE_FIELD_NAMES).toEqual(expected);
    expect(typescriptInterfaceFields()).toEqual(expected);
  });

  test('nullable and optional semantics match exactly', () => {
    expect(EVIDENCE_NULLABLE_FIELDS).toEqual(pythonTuple('EVIDENCE_NULLABLE_FIELDS'));
    expect(evidenceTypescript).toMatch(/readonly fixture_id: string \| null;/);
    expect(evidenceTypescript).not.toMatch(/readonly \w+\?:/);
  });

  test('closed enum values match Python', () => {
    expect(SIGNAL_BASIS_VALUES).toEqual(pythonEnumValues('SignalBasis'));
    expect(EVIDENCE_DIRECTION_VALUES).toEqual(pythonEnumValues('EvidenceDirection'));
    expect(EVIDENCE_SUBJECT_TYPE_VALUES).toEqual(pythonEnumValues('SubjectType'));
  });

  test('enum removal still produces a parity mismatch', () => {
    const mutated = enumsPython.replace('    INFERRED_PROXY = "inferred_proxy"\n', '');
    expect(pythonEnumValues('SignalBasis', mutated)).not.toEqual(SIGNAL_BASIS_VALUES);
  });

  test('evidence codes match Python exactly', () => {
    expect(new Set(EVIDENCE_CODES)).toEqual(new Set(pythonEvidenceCodes()));
    expect(EVIDENCE_CODES).toHaveLength(pythonEvidenceCodes().length);
  });

  test('representative interface requires every stable field', () => {
    const item: EvidenceItem = {
      code: 'ROLE_STABLE', label: 'Stable role', subject_type: 'player',
      subject_id: 'cp_1', fixture_id: null, impact: 2, direction: 'positive',
      confidence: 0.8, basis: 'observed', summary: 'Stable recent role.',
      source_features: ['role_stability'], model_version: 'tactical-role-v1',
      calculated_at: '2026-07-14T18:00:00Z',
    };
    expect(Object.keys(item)).toEqual(EVIDENCE_FIELD_NAMES);
  });
});
