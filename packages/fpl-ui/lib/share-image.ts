import { toBlob } from 'html-to-image';

/** Export a rendered node as PNG bytes. */
export async function exportNodeAsPng(node: HTMLElement): Promise<Blob> {
  const blob = await toBlob(node, {
    cacheBust: true,
    pixelRatio: 2,
    backgroundColor: '#14121D',
  });
  if (!blob) {
    throw new Error('No se pudo generar la imagen de la tarjeta.');
  }
  return blob;
}

/** Trigger a browser download for a blob. */
export function downloadBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
