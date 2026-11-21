import { planStateForNextTurn } from '@/lib/plan-state';

const state = { target_id: 7, moves: 'one', shown_out_ids: [1, 2] };

describe('planStateForNextTurn', () => {
  it('returns the state of the immediately preceding assistant answer', () => {
    expect(
      planStateForNextTurn([
        { role: 'user' },
        { role: 'assistant', response: { plan_state: state } },
      ]),
    ).toEqual(state);
  });

  it('is undefined when that answer carried none', () => {
    expect(planStateForNextTurn([{ role: 'assistant', response: { plan_state: null } }])).toBeUndefined();
    expect(planStateForNextTurn([{ role: 'assistant' }])).toBeUndefined();
  });

  it('does not reach past a later message: a plan answer must not hijack another question', () => {
    expect(
      planStateForNextTurn([
        { role: 'assistant', response: { plan_state: state } },
        { role: 'user' },
        { role: 'assistant', response: { plan_state: null } },
      ]),
    ).toBeUndefined();
  });

  it('is undefined for an empty chat or when the last message is the user', () => {
    expect(planStateForNextTurn([])).toBeUndefined();
    expect(planStateForNextTurn([{ role: 'assistant', response: { plan_state: state } }, { role: 'user' }])).toBeUndefined();
  });
});
