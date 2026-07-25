import {
  buildBlueskyUrl,
  buildCopyPayload,
  buildThreadsUrl,
  buildWhatsAppUrl,
  buildXIntentUrl,
  canonicalAppUrl,
} from '../lib/share';

describe('share utils', () => {
  test('canonicalAppUrl normalizes missing scheme and keeps /chat', () => {
    expect(canonicalAppUrl('app.benditofantasy.com/chat')).toBe('https://app.benditofantasy.com/chat');
  });

  test('canonicalAppUrl adds /chat for bare domain', () => {
    expect(canonicalAppUrl('https://app.benditofantasy.com')).toBe('https://app.benditofantasy.com/chat');
  });

  test('buildXIntentUrl encodes question and app URL', () => {
    const url = buildXIntentUrl({
      question: '¿Capitán para GW8?',
      appUrl: 'app.benditofantasy.com/chat',
    });

    expect(url.startsWith('https://x.com/intent/tweet?text=')).toBe(true);
    expect(decodeURIComponent(url.split('text=')[1])).toContain('¿Capitán para GW8?');
    expect(decodeURIComponent(url.split('text=')[1])).toContain('https://app.benditofantasy.com/chat');
  });

  test('buildWhatsAppUrl encodes payload', () => {
    const url = buildWhatsAppUrl({
      question: '¿Quién entra por Saka?',
      appUrl: 'https://app.benditofantasy.com/chat',
    });

    expect(url.startsWith('https://wa.me/?text=')).toBe(true);
    expect(decodeURIComponent(url.split('text=')[1])).toContain('¿Quién entra por Saka?');
  });

  test('buildBlueskyUrl encodes payload', () => {
    const url = buildBlueskyUrl({
      question: '¿A quién capitanear en GW9?',
      appUrl: 'https://app.benditofantasy.com/chat',
    });

    expect(url.startsWith('https://bsky.app/intent/compose?text=')).toBe(true);
    expect(decodeURIComponent(url.split('text=')[1])).toContain('¿A quién capitanear en GW9?');
  });

  test('buildThreadsUrl encodes payload', () => {
    const url = buildThreadsUrl({
      question: '¿Cambio a Palmer?',
      appUrl: 'https://app.benditofantasy.com/chat',
    });

    expect(url.startsWith('https://www.threads.net/intent/post?text=')).toBe(true);
    expect(decodeURIComponent(url.split('text=')[1])).toContain('¿Cambio a Palmer?');
  });

  test('buildCopyPayload returns full invite text', () => {
    const payload = buildCopyPayload({
      question: '¿Vendo a Son?',
      appUrl: 'https://app.benditofantasy.com/chat',
    });

    expect(payload).toContain('Club Bendito Fantasy');
    expect(payload).toContain('Pruébalo tú también en Club Bendito Fantasy.');
    expect(payload).toContain('https://app.benditofantasy.com/chat');
  });
});
