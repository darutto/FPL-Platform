/**
 * The login's Patreon button: its text must meet WCAG AA (4.5:1) on its background.
 * Reads the two colours out of the real override in globals.css, so changing either
 * one without re-checking the contrast fails here.
 */
import { readFileSync } from 'fs';
import { join } from 'path';

const css = readFileSync(join(__dirname, '..', 'app', 'globals.css'), 'utf8');
const rule = (selector: string) => {
  const start = css.indexOf(`${selector} {`);
  return start < 0 ? '' : css.slice(start, css.indexOf('}', start));
};

const luminance = (hex: string) => {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [n >> 16, (n >> 8) & 255, n & 255].map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

test('the Patreon button text meets WCAG AA on the orange', () => {
  const background = rule('.login-page .cl-socialButtonsBlockButton').match(/background-color:\s*(#[0-9a-f]{6})/i)?.[1];
  const text = rule('.login-page .cl-socialButtonsBlockButtonText').match(/color:\s*(#[0-9a-f]{6})/i)?.[1];
  expect(background).toBe('#ff6a4d');
  expect(text).toBeDefined();
  expect(contrast(text!, background!)).toBeGreaterThanOrEqual(4.5);
  // The hover shade keeps it too.
  const hover = rule('.login-page .cl-socialButtonsBlockButton:focus-visible').match(/background-color:\s*(#[0-9a-f]{6})/i)?.[1];
  expect(contrast(text!, hover!)).toBeGreaterThanOrEqual(4.5);
});

test('white on that orange would not pass, which is why the text is ink', () => {
  expect(contrast('#ffffff', '#ff6a4d')).toBeLessThan(4.5);
});
