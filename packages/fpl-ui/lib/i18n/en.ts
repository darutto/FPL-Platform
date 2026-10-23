/**
 * English copy. Wording follows docs/i18n-glossary.md (British English, chip names unchanged).
 * Typed against es.ts: every Spanish key needs an English one.
 */
import type { es } from './es';

export const en: typeof es = {
  'app.title': 'FPL Assistant · Bendito Fantasy',
  'app.description': 'Your FPL assistant manager',
  'locale.switcherLabel': 'Language',

  // --- Slash commands: canonical English names (Spanish ones stay accepted) ---
  'slash.capitan.command': '/captain',
  'slash.capitan.label': 'Captain',
  'slash.capitan.placeholder': 'e.g. Haaland',
  'slash.comparar.command': '/compare',
  'slash.comparar.label': 'Compare players',
  'slash.comparar.placeholder': 'e.g. Salah vs De Bruyne',
  'slash.transferencia.command': '/transfer',
  'slash.transferencia.label': 'Transfer advice',
  'slash.transferencia.placeholder': 'e.g. Palmer for Gordon',
  'slash.calendarios.command': '/fixtures',
  'slash.calendarios.label': 'Fixtures',
  'slash.calendarios.placeholder': 'e.g. Mbappé',
  'slash.diferenciales.command': '/differentials',
  'slash.diferenciales.label': 'Differentials',
  'slash.diferenciales.placeholder': 'e.g. under 10%',
  'slash.chips.command': '/chips',
  'slash.chips.label': 'Chip usage',
  'slash.chips.placeholder': 'e.g. Triple Captain',
  'slash.clasificacion.command': '/rankings',
  'slash.clasificacion.label': 'Top captains this week',
  'slash.clasificacion.placeholder': 'e.g. Haaland, Salah, Palmer',
  'slash.menuLabel': 'Slash commands',

  // --- Command panel ---
  'panel.title': 'Quick commands',
  'panel.quickViews': 'Quick views',
  'panel.actions': 'Actions',
  'panel.at.injuries.command': '@injuries',
  'panel.at.injuries.label': 'Injuries',
  'panel.at.injuries.desc': 'Latest list',
  'panel.at.form.command': '@form',
  'panel.at.form.label': 'On a run',
  'panel.at.form.desc': 'Best recent form',
  'panel.at.xg.command': '@xg',
  'panel.at.xg.label': 'Goal threat',
  'panel.at.xg.desc': 'xG + xA per 90 leaders',
  'panel.at.points.command': '@points',
  'panel.at.points.label': 'Most points',
  'panel.at.points.desc': 'Season totals',
  'panel.at.minutes.command': '@minutes',
  'panel.at.minutes.label': 'Ever-presents',
  'panel.at.minutes.desc': 'Most minutes played',
  'panel.at.popular.command': '@popular',
  'panel.at.popular.label': 'Most brought in',
  'panel.at.popular.desc': 'Highest ownership',
  'panel.slash.capitan.label': 'Who gets the armband?',
  'panel.slash.capitan.desc': 'Captain recommendation',
  'panel.slash.comparar.label': 'Compare 2 players',
  'panel.slash.comparar.desc': 'Side-by-side analysis',
  'panel.slash.transferencia.label': 'Suggest a transfer',
  'panel.slash.transferencia.desc': 'Is the move worth it?',
  'panel.slash.calendarios.label': 'Player fixtures',
  'panel.slash.calendarios.desc': 'Upcoming fixture difficulty',
  'panel.slash.diferenciales.label': 'Find hidden gems',
  'panel.slash.diferenciales.desc': 'Low ownership, high upside',
  'panel.slash.chips.label': 'Use a chip?',
  'panel.slash.chips.desc': 'Triple Captain, WC, BB or FH',
  'panel.slash.clasificacion.label': 'Top captains this week',
  'panel.slash.clasificacion.desc': 'Gameweek ranking',

  // --- Empty chat: starter prompts ({a}, {b}, {out} are player names) ---
  'starter.captain': 'Who should I captain?',
  'starter.tripleCaptain': 'Should I use the Triple Captain?',
  'starter.differentials': '/differentials under 10%',
  'starter.static.compare': '/compare Haaland vs Bruno Fernandes',
  'starter.static.transfer': '/transfer Cole Palmer for Saka',
  'starter.static.fixtures': '/fixtures Haaland',
  'starter.dynamic.compare': '/compare {a} vs {b}',
  'starter.dynamic.transfer': '/transfer {out} for {a}',
  'starter.dynamic.fixtures': '/fixtures {a}',

  // --- Input bar ---
  'input.placeholder': 'Ask a question or use /captain, /compare…',
  'input.placeholderWeb': 'Ask anything — I will search live news and sources…',
  'input.webActive': 'Web search on · this query will use your premium quota',
  'input.webOff': 'Turn off web search',
  'input.webOn': 'Turn on web search',
  'input.webLocked': 'Web search (premium feature)',
  'input.webTitle': 'Search the web (premium)',
  'input.webTitleLocked': 'Premium feature — become a patron to turn it on',
  'input.ariaLabel': 'Ask the FPL assistant',
  'input.send': 'Send',

  // --- Chat shell ---
  'chat.heading': 'Chat',
  'chat.empty': 'Ask a question about your Fantasy Premier League team.',
  'chat.followUpArmed': 'Replying to this · tap to cancel',
  'chat.unexpectedError': 'Unexpected error. Please try again.',
  'pager.calendar': 'Fixtures',
  'pager.squad': 'Squad',
  'pager.chat': 'Chat',
  'pager.commands': 'Commands',

  // --- Wide workspace ---
  'workspace.navigation': 'Workspace navigation',
  'workspace.centreView': 'Centre view',
  'workspace.chat': 'Chat',
  'workspace.calendar': 'Fixtures',
  'workspace.panel.squad': 'Squad',
  'workspace.panel.commands': 'Commands',
  'workspace.hidePanel': 'Hide {name} panel',
  'workspace.showPanel': 'Show {name} panel',

  // --- Top bar ---
  'topbar.title': 'FPL Assistant',
  'topbar.subtitle': 'Bendito Fantasy',
  'topbar.team': 'Team',
  'topbar.contrast': 'High contrast (accessibility)',

  // --- Messages ---
  'msg.thinking': 'Thinking…',
  'msg.structuredAnswer': 'Structured answer',
  'msg.verdict': 'Verdict',
  'msg.recommendationData': 'Recommendation data',
  'msg.followUpOn': 'Follow-up on ✓',
  'msg.followUp': 'Follow up →',
  'msg.badge.webAi': 'Web search + AI',
  'msg.badge.verified': 'Verified data',
  'msg.badge.noTournament': 'No tournament data',
  'msg.badge.aiOn': 'AI on',
  'msg.badge.deterministic': 'Deterministic',
  'msg.providerDown': 'provider unavailable',

  // --- Wizards (the questions the UI itself asks) ---
  'wizard.compareStep1': 'Who is the first player?',
  'wizard.compareStep2': 'Who are we comparing him with?',
  'wizard.pickOne': 'Which of these players did you mean?',
  'wizard.firstPlayer': 'First player:',
  'wizard.notFound': 'Cannot see your player? Type the name below.',

  // --- Squad context panel ---
  'squad.invalidId': 'Invalid team ID — it must be a positive number.',
  'squad.notFound': 'Team not found. Check the ID.',
  'squad.fetchError': 'Could not load the data ({status}). Please try again.',
  'squad.unreachable': 'Could not reach the FPL API. Please try again.',
  'squad.disconnect': 'Disconnect',
  'squad.placeholder': 'FPL team ID',
  'squad.connecting': 'Connecting…',
  'squad.connect': 'Connect',

  // --- Quota ---
  'quota.day': 'Day',
  'quota.month': 'Month',
  'quota.today': 'Today',
  'quota.thisMonth': 'This month',
  'quota.free': 'Free',
  'quota.messagesLeft': '{n} msgs left',
  'quota.title': 'Message quota',
  'quota.close': 'Close',
  'quota.currentTier': 'Current tier:',
  'quota.plan': 'Plan',
  'quota.includesWeb': 'Includes web search',
  'quota.recommended': 'Recommended',
  'quota.upgrade': 'Upgrade on Patreon',
  'quota.tooltip':
    'Daily quota: {dRem}/{dCap} msgs · Monthly: {mRem}/{mCap} msgs\nDaily tokens: {dtRem}/{dtCap} · Monthly: {mtRem}/{mtCap}',

  // --- Errors from the API client ---
  'error.sessionLimit': 'Session limit reached — please try again in a few minutes',
  'error.sessionExpired': 'Session expired. Start a new conversation.',

  // --- Login ---
  'login.title': 'FPL Assistant',
  'login.subtitle': 'Sign in with your Patreon account to access the chat.',
  'postLogin.verifying': 'Checking your Patreon membership...',

  // --- Relative time ---
  'time.today': 'today',
  'time.dayAgo': '1 day ago',
  'time.daysAgo': '{n} days ago',
  'time.weeksAgo': '{n} weeks ago',
  'time.monthAgo': '1 month ago',
  'time.monthsAgo': '{n} months ago',
};
