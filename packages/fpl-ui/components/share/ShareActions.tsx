'use client';

import { useMemo, useRef, useState } from 'react';
import type { AskResponse } from '@/lib/types';
import {
  DEFAULT_CTA,
  buildCopyPayload,
  canonicalAppUrl,
} from '@/lib/share';
import { downloadBlob, exportNodeAsPng } from '@/lib/share-image';
import ShareCard from './ShareCard';

interface Props {
  question: string;
  response: AskResponse;
  appUrl?: string;
  cta?: string;
}

async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // continue to textarea fallback
    }
  }

  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  } catch {
    return false;
  }
}

export default function ShareActions({ question, response, appUrl, cta }: Props) {
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const exportRef = useRef<HTMLDivElement>(null);

  const finalAppUrl = useMemo(() => canonicalAppUrl(appUrl), [appUrl]);
  const finalCta = (cta ?? DEFAULT_CTA).trim() || DEFAULT_CTA;
  const shareText = useMemo(
    () => buildCopyPayload({ question, appUrl: finalAppUrl, cta: finalCta }),
    [question, finalAppUrl, finalCta],
  );

  const exportCardBlob = async (): Promise<Blob | null> => {
    if (!exportRef.current) return null;
    try {
      return await exportNodeAsPng(exportRef.current);
    } catch {
      return null;
    }
  };

  const canNativeShareFile = (file: File): boolean => {
    if (typeof navigator === 'undefined') return false;
    if (typeof navigator.share !== 'function') return false;
    if (typeof navigator.canShare !== 'function') return false;
    try {
      return navigator.canShare({ files: [file] });
    } catch {
      return false;
    }
  };

  const tryNativeImageShare = async (blob: Blob): Promise<boolean> => {
    const file = new File([blob], 'club-bendito-card.png', { type: 'image/png' });
    if (!canNativeShareFile(file)) return false;
    try {
      await navigator.share({
        files: [file],
        text: shareText,
        title: 'Club Bendito Fantasy',
      });
      return true;
    } catch {
      return false;
    }
  };

  const openFallbackWindow = (url: string, withImage: boolean) => {
    const copiedText = withImage ? 'Tarjeta descargada y texto copiado.' : 'Texto copiado.';
    void url;
    setStatus(copiedText);
  };

  const handleShare = () => {
    void (async () => {
      setBusy(true);
      setStatus(null);

      const blob = await exportCardBlob();
      if (blob) {
        const nativeShared = await tryNativeImageShare(blob);
        if (nativeShared) {
          setBusy(false);
          return;
        }
        const stamp = new Date().toISOString().slice(0, 10);
        downloadBlob(blob, `club-bendito-card-${stamp}.png`);
      }

      await copyText(shareText);
      openFallbackWindow('', blob != null);
      setBusy(false);
    })();
  };

  return (
    <>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-label="Compartir tarjeta"
          title="Compartir tarjeta"
          onClick={handleShare}
          disabled={busy}
          className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-white/15 text-bf-text transition-colors hover:border-white/30 hover:bg-white/5 disabled:opacity-60"
        >
          <InstagramIcon />
        </button>
      </div>

      {status && <p className="mt-2 text-[11px] text-bf-gray">{status}</p>}

      <div className="pointer-events-none fixed -left-[99999px] top-0 opacity-0" aria-hidden="true">
        <div ref={exportRef}>
          <ShareCard question={question} response={response} appUrl={finalAppUrl} cta={finalCta} />
        </div>
      </div>
    </>
  );
}

function InstagramIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M21.2 4.1L11 14.3M21.2 4.1L14.7 22L11 14.3M21.2 4.1L3.3 10.6L11 14.3"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
