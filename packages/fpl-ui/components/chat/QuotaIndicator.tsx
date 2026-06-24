'use client';

/**
 * QuotaIndicator — compact footer widget showing daily/monthly quota usage.
 *
 * Polls GET /api/quota?user_id=<id>&tier=<tier> on mount and whenever
 * refreshTrigger changes (caller increments it after each sent message).
 *
 * Color logic:
 *   remaining / cap > 0.5  → green  (plenty of quota left)
 *   0.2–0.5                → amber  (approaching limit)
 *   < 0.2                  → red    (near / at limit)
 *
 * Click → opens an inline modal with tier comparison + Patreon upgrade CTA.
 */

import { useEffect, useState, useCallback } from 'react';
import type { QuotaStatus } from '@/lib/types';
import { quotaTone, QUOTA_TONE_CLASSES } from '@/lib/theme';

interface Props {
  userId?: string;       // defaults to 'anonymous'
  tier?: string;         // defaults to 'free'
  refreshTrigger?: number; // increment to force re-fetch after a turn
  endpoint?: string;     // quota proxy route; defaults to the FPL backend's
}

// ---------------------------------------------------------------------------
// Tier comparison table for modal
// ---------------------------------------------------------------------------

const TIER_TABLE = [
  { tier: 'Free',             daily: 5,   monthly: 30,   link: false },
  { tier: 'Patreon $5',       daily: 30,  monthly: 600,  link: true  },
  { tier: 'Patreon $15',      daily: 150, monthly: 3000, link: true  },
  { tier: 'Patreon $30',      daily: '∞', monthly: 10000, link: true },
] as const;

const PATREON_URL = 'https://www.patreon.com/fpl_asistente';

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function QuotaIndicator({
  userId = 'anonymous',
  tier = 'free',
  refreshTrigger = 0,
  endpoint = '/api/quota',
}: Props) {
  const [status, setStatus] = useState<QuotaStatus | null>(null);
  const [fetchError, setFetchError] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  const fetchQuota = useCallback(async () => {
    try {
      const params = new URLSearchParams({ user_id: userId, tier });
      const res = await fetch(`${endpoint}?${params.toString()}`);
      if (!res.ok) {
        setFetchError(true);
        return;
      }
      const data: QuotaStatus = await res.json();
      setStatus(data);
      setFetchError(false);
    } catch {
      setFetchError(true);
    }
  }, [userId, tier, endpoint]);

  useEffect(() => {
    fetchQuota();
  }, [fetchQuota, refreshTrigger]);

  // Don't render if still loading on first mount or if quota fetch fails silently
  if (!status && !fetchError) return null;
  if (fetchError) return null;
  if (!status) return null;

  const dailyRemaining = status.daily_message_cap - status.daily_message_count;
  const monthlyRemaining = status.monthly_message_cap - status.monthly_message_count;

  // Determine which is more constraining (lower %)
  const dailyPct = status.daily_message_cap > 0
    ? dailyRemaining / status.daily_message_cap
    : 0;
  const monthlyPct = status.monthly_message_cap > 0
    ? monthlyRemaining / status.monthly_message_cap
    : 0;
  const constrainingPct = Math.min(dailyPct, monthlyPct);
  const constrainingTone = constrainingPct > 0.5 ? 'ok' : constrainingPct > 0.2 ? 'warn' : 'danger';
  const pillColor = QUOTA_TONE_CLASSES[constrainingTone].pill;
  const dailyTone = quotaTone(dailyRemaining, status.daily_message_cap);
  const monthlyTone = quotaTone(monthlyRemaining, status.monthly_message_cap);

  return (
    <>
      {/* Compact pill widget */}
      <button
        onClick={() => setModalOpen(true)}
        title={`Cuota diaria: ${dailyRemaining}/${status.daily_message_cap} msgs · Mensual: ${monthlyRemaining}/${status.monthly_message_cap} msgs\nTokens diarios: ${status.daily_token_cap - status.daily_tokens_used}/${status.daily_token_cap} · Mensuales: ${status.monthly_token_cap - status.monthly_tokens_used}/${status.monthly_token_cap}`}
        className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-bold transition-colors hover:opacity-80 ${pillColor}`}
      >
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${QUOTA_TONE_CLASSES[dailyTone].dot}`} />
        <span>
          Día {dailyRemaining}/{status.daily_message_cap}
        </span>
        <span className="opacity-50">·</span>
        <span>
          Mes {monthlyRemaining}/{status.monthly_message_cap}
        </span>
      </button>

      {/* Tier upgrade modal */}
      {modalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setModalOpen(false)}
        >
          <div
            className="relative w-full max-w-sm mx-4 rounded-card border border-white/10 bg-bf-surface p-5 shadow-menu"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-extrabold text-white">Cuota de mensajes</h2>
              <button
                onClick={() => setModalOpen(false)}
                className="text-bf-gray hover:text-bf-text text-lg leading-none"
                aria-label="Cerrar"
              >
                ✕
              </button>
            </div>

            {/* Current usage summary */}
            <div className="mb-4 rounded-card border border-white/10 bg-white/5 p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-bf-gray">Hoy</span>
                <span className={`text-[11px] font-bold ${QUOTA_TONE_CLASSES[dailyTone].text}`}>
                  {dailyRemaining} msgs restantes
                </span>
              </div>
              {/* Daily bar */}
              <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${QUOTA_TONE_CLASSES[dailyTone].bar}`}
                  style={{ width: `${Math.max(0, Math.min(100, dailyPct * 100)).toFixed(1)}%` }}
                />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-bf-gray">Este mes</span>
                <span className={`text-[11px] font-bold ${QUOTA_TONE_CLASSES[monthlyTone].text}`}>
                  {monthlyRemaining} msgs restantes
                </span>
              </div>
              {/* Monthly bar */}
              <div className="h-1.5 w-full rounded-full bg-white/10 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${QUOTA_TONE_CLASSES[monthlyTone].bar}`}
                  style={{ width: `${Math.max(0, Math.min(100, monthlyPct * 100)).toFixed(1)}%` }}
                />
              </div>
              <p className="text-[10px] text-bf-gray/70 pt-1">
                Tier actual: <span className="font-medium text-bf-gray">{status.tier}</span>
              </p>
            </div>

            {/* Tier comparison table */}
            <table className="w-full text-[11px] mb-4">
              <thead>
                <tr className="border-b border-white/10">
                  <th className="text-left text-bf-gray font-bold uppercase tracking-wide pb-1.5">Plan</th>
                  <th className="text-right text-bf-gray font-bold uppercase tracking-wide pb-1.5">Día</th>
                  <th className="text-right text-bf-gray font-bold uppercase tracking-wide pb-1.5">Mes</th>
                </tr>
              </thead>
              <tbody>
                {TIER_TABLE.map((row, idx) => (
                  <tr
                    key={row.tier}
                    className={`${idx % 2 === 0 ? 'bg-white/[0.035]' : ''} ${row.tier.toLowerCase().startsWith(status.tier) ? 'text-white font-bold' : 'text-bf-gray'}`}
                  >
                    <td className="py-1.5 px-1">{row.tier}</td>
                    <td className="text-right py-1.5 px-1">{row.daily}</td>
                    <td className="text-right py-1.5 px-1">{row.monthly}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Upgrade CTA */}
            <a
              href={PATREON_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="block w-full rounded-[10px] bg-bf-coral hover:bg-bf-coral/90 text-white hc:text-bf-ink text-center text-xs font-bold py-2.5 transition-colors"
            >
              Mejorar en Patreon
            </a>
          </div>
        </div>
      )}
    </>
  );
}
