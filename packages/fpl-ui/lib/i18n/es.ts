/**
 * Spanish copy: the source of truth. en.ts is typed `typeof es`, so a key missing there fails `tsc`.
 * Keys are flat and namespaced ('quota.day'); `{name}` marks a value filled in by t().
 * Spanish wording here is what the app already says: moving a string in must not change it.
 */
export const es = {
  'app.title': 'FPL Asistente',
  'app.description': 'Asistente de Fantasy Premier League',
  'locale.switcherLabel': 'Idioma',
};
