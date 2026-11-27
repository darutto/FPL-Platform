/**
 * @jest-environment jsdom
 *
 * Extracting the shared card blocks must change nothing on screen. The snapshot beside this file was recorded
 * BEFORE the extraction, from backend-serialized bodies; class tokens are sorted, since their order has no
 * effect. fixtures/card-blocks/card_bodies.json holds bodies the backend serialized from its synthetic leagues.
 * The two exceptions are marked "hand-written": no serialized body with that part is committed.
 */
import fs from 'node:fs';
import path from 'node:path';

import React from 'react';
import { render } from '@testing-library/react';

import IntentRenderer from '../components/chat/IntentRenderer';
import TeamCard from '../components/intents/TeamCard';
import ShareCard from '../components/share/ShareCard';
import { genericCardOkResponse, injuryListGenericResponse } from './fixtures/sample-responses';
import type { AskResponse, TeamCardBody } from '../lib/types';

jest.mock('@/lib/data/fixture-outlook-2026-27.json', () => jest.requireActual('./fixtures/fixture-outlook-2026-27.pinned.json'));
jest.mock('@/lib/fixture-outlook-real', () => ({ buildRealSeasonOutlook: () => ({ teams: [] }) }));

const read = (name: string) => JSON.parse(fs.readFileSync(path.resolve(__dirname, name), 'utf8'));
const BODIES = read('fixtures/card-blocks/card_bodies.json');
const QUERY: Record<string, AskResponse> = read(
  '../../fpl-grounded-assistant/tests/fixtures/query_response_bodies.json',
);

const normalized = (root: HTMLElement) => {
  root.querySelectorAll('[class]').forEach((el) => {
    el.setAttribute('class', (el.getAttribute('class') ?? '').split(/\s+/).filter(Boolean).sort().join(' '));
  });
  return root.innerHTML.replace(/></g, '>\n<');
};
const shot = (node: React.ReactElement) => expect(normalized(render(node).container)).toMatchSnapshot();
const card = (response: AskResponse) => shot(<IntentRenderer response={response} />);

test('team card', () => shot(<TeamCard data={BODIES.team_card as TeamCardBody} />));

test.each(['player_snapshot', 'comparison', 'transfer'])('%s', (name) => card(BODIES[name]));

test.each(['favourable', 'profile-only'])('player card with zones: %s', (name) => {
  card(read(`fixtures/player-zonal/${name}.json`));
});

test.each(Object.keys(QUERY))('query card: %s', (name) => card(QUERY[name]));

test('query card with a footnote, in the app and in the shared image', () => {
  const body: AskResponse = JSON.parse(JSON.stringify(QUERY.with_without_attack_es));
  body.query!.footnote = 'Server small print';
  card(body);
  shot(<ShareCard question="q" response={body} appUrl="https://example.test" cta="cta" />);
});

test.each(['split-es', 'one-role-es'])('generic card: position pitch %s', (name) => {
  card(read(`fixtures/position-pitch/${name}.json`));
});

test('generic card with a hero stat (hand-written)', () => card(genericCardOkResponse));

test('injury list with a footer (hand-written)', () => card(injuryListGenericResponse));

test('injury list with its footer line (hand-written)', () => {
  card({ ...injuryListGenericResponse,
    generic_card: { ...injuryListGenericResponse.generic_card!, footer: 'Server footer line' } });
});

test.each(['es', 'en'])('involvement comparison footer: %s', (lang) => {
  card({ ...genericCardOkResponse,
    generic_card: { ...genericCardOkResponse.generic_card!,
      involvement_compare: read(`fixtures/involvement-compare-${lang}.json`).involvement_compare
        ?? read(`fixtures/involvement-compare-${lang}.json`) } });
});
