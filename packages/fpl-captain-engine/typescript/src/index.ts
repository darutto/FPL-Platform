/**
 * fpl-captain-engine — public API entry point
 *
 * Re-exports everything consumers need from the scoring engine.
 * Import as: import { calculateCaptainScore, updateCaptainScores } from '@fpl-platform/fpl-captain-engine'
 */
export {
  calculateCaptainScore,
  updateCaptainScores,
  type CaptainCandidate,
  type MatchupData,
} from './captainScore'


