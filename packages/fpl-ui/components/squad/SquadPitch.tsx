'use client';

/**
 * SquadPitch — "My Squad" pager screen (U2, Stitch Hi-Fi).
 *
 * Renders the connected team's current-GW picks on a football pitch:
 *   - stats strip (GW points / total / bank)
 *   - pitch with the starting XI laid out by position rows
 *   - bench row
 *   - player detail card on tap, with an "Ask AI" shortcut that drops a
 *     question about the player into the chat input.
 *
 * Pitch sizing: the pitch box keeps a fixed 5:3 aspect ratio and fills the
 * panel width (panel itself capped at 460px by the pager). The markings are
 * drawn natively in a matching 400×240 viewBox with
 * `preserveAspectRatio="xMidYMid meet"`, so they NEVER stretch or deform at
 * any screen size — unlike the prototype's `none` mode.
 *
 * Data: GET /api/fpl-squad/{teamId} (server proxy; live FPL API).
 */
import { useCallback, useEffect, useState } from 'react';

interface SquadPlayer {
  id: number;
  web_name: string;
  team_short: string;
  position: 'GK' | 'DEF' | 'MID' | 'FWD';
  price: number; // tenths of £
  sel: string; // "12.3"
  form: string; // "7.0"
  gw_points: number;
  pick_position: number;
  is_starter: boolean;
  is_captain: boolean;
}

interface SquadData {
  gw: number;
  summary: { gw_points: number; total_points: number; bank: number };
  players: SquadPlayer[];
}

// Broadcast position colors (DS .pos-badge): POR gold · DEF turquoise ·
// MC cyan · DEL coral.
const POS_STYLE: Record<
  SquadPlayer['position'],
  { label: string; dotText: string; dotBorder: string; dotTint: string; dotSolid: string; badge: string }
> = {
  GK: {
    label: 'POR',
    dotText: 'text-bf-gold',
    dotBorder: 'border-bf-gold/60',
    dotTint: 'bg-bf-gold/15',
    dotSolid: 'bg-bf-gold',
    badge: 'bg-bf-gold text-bf-ink',
  },
  DEF: {
    label: 'DEF',
    dotText: 'text-bf-turquoise',
    dotBorder: 'border-bf-turquoise/60',
    dotTint: 'bg-bf-turquoise/15',
    dotSolid: 'bg-bf-turquoise',
    badge: 'bg-bf-turquoise text-bf-ink',
  },
  MID: {
    label: 'MC',
    dotText: 'text-bf-cyan',
    dotBorder: 'border-bf-cyan/60',
    dotTint: 'bg-bf-cyan/15',
    dotSolid: 'bg-bf-cyan',
    badge: 'bg-bf-cyan text-bf-ink',
  },
  FWD: {
    label: 'DEL',
    dotText: 'text-bf-coral',
    dotBorder: 'border-bf-coral/60',
    dotTint: 'bg-bf-coral/15',
    dotSolid: 'bg-bf-coral',
    badge: 'bg-bf-coral text-white hc:text-bf-ink',
  },
};

interface Props {
  teamId: number | null;
  /** Drops a question about the player into the chat input. */
  onAskPlayer: (question: string) => void;
  /** Reports the current GW upward (for the TopBar pill). */
  onGw?: (gw: number) => void;
}

type FetchState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; data: SquadData }
  | { status: 'error'; message: string };

export default function SquadPitch({ teamId, onAskPlayer, onGw }: Props) {
  const [state, setState] = useState<FetchState>({ status: 'idle' });
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (teamId == null) {
      setState({ status: 'idle' });
      return;
    }
    setState({ status: 'loading' });
    try {
      const res = await fetch(`/api/fpl-squad/${teamId}`);
      if (!res.ok) {
        setState({ status: 'error', message: `No se pudo cargar la plantilla (${res.status}).` });
        return;
      }
      const data: SquadData = await res.json();
      setState({ status: 'ready', data });
      onGw?.(data.gw);
    } catch {
      setState({ status: 'error', message: 'No se pudo conectar con la API de FPL.' });
    }
  }, [teamId, onGw]);

  useEffect(() => {
    setSelectedId(null);
    load();
  }, [load]);

  return (
    <div className="h-full rounded-card border border-white/10 bg-bf-surface flex flex-col overflow-hidden">
      {/* Panel header */}
      <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between flex-shrink-0 bg-black/25">
        <span className="text-[10px] font-bold uppercase tracking-widest text-bf-text/50">
          My squad
        </span>
        {teamId != null && (
          <span className="text-[10px] font-bold text-bf-turquoise">#{teamId}</span>
        )}
      </div>

      {state.status === 'idle' && (
        <CenteredHint>
          Conecta tu equipo FPL en la pestaña Chat
          <br />
          para ver tu plantilla aquí.
        </CenteredHint>
      )}

      {state.status === 'loading' && (
        <CenteredHint>
          <span className="animate-pulse">Cargando plantilla…</span>
        </CenteredHint>
      )}

      {state.status === 'error' && (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 px-6 text-center">
          <p className="text-xs text-bf-coral">{state.message}</p>
          <button
            onClick={load}
            className="text-xs font-bold text-bf-turquoise hover:text-bf-turquoise/80 transition-colors"
          >
            Reintentar
          </button>
        </div>
      )}

      {state.status === 'ready' && (
        <SquadBody
          data={state.data}
          selectedId={selectedId}
          onSelect={(id) => setSelectedId((prev) => (prev === id ? null : id))}
          onAskPlayer={onAskPlayer}
        />
      )}
    </div>
  );
}

function CenteredHint({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1 flex items-center justify-center px-6">
      <p className="text-xs text-bf-text/30 text-center leading-relaxed">{children}</p>
    </div>
  );
}

function SquadBody({
  data,
  selectedId,
  onSelect,
  onAskPlayer,
}: {
  data: SquadData;
  selectedId: number | null;
  onSelect: (id: number) => void;
  onAskPlayer: (question: string) => void;
}) {
  const starters = data.players.filter((p) => p.is_starter);
  const bench = data.players.filter((p) => !p.is_starter);
  const selected = data.players.find((p) => p.id === selectedId) ?? null;

  const rows: SquadPlayer[][] = (['GK', 'DEF', 'MID', 'FWD'] as const).map((pos) =>
    starters.filter((p) => p.position === pos),
  );

  return (
    <div className="flex-1 min-h-0 flex flex-col overflow-y-auto">
      {/* Stats strip */}
      <div className="flex px-3 py-2 border-b border-white/5 flex-shrink-0">
        <Stat label={`GW${data.gw}`} value={String(data.summary.gw_points)} valueClass="text-bf-turquoise" />
        <Divider />
        <Stat label="Total" value={data.summary.total_points.toLocaleString('en-GB')} valueClass="text-white" />
        <Divider />
        <Stat label="Banco" value={`£${(data.summary.bank / 10).toFixed(1)}m`} valueClass="text-bf-gold" />
      </div>

      {/* Pitch — fixed 5:3 aspect, fills the panel, never deforms */}
      <div className="flex-shrink-0">
        <div className="relative w-full aspect-[5/3] overflow-hidden bg-gradient-to-b from-bf-pitch to-bf-pitch-dark">
          {/* Markings drawn natively at 400×240 (same 5:3 aspect as the box) */}
          <svg
            aria-hidden="true"
            className="absolute inset-0 w-full h-full opacity-20"
            viewBox="0 0 400 240"
            preserveAspectRatio="xMidYMid meet"
          >
            <rect x="8" y="8" width="384" height="224" fill="none" stroke="white" strokeWidth="2" />
            <line x1="8" y1="120" x2="392" y2="120" stroke="white" strokeWidth="1.5" />
            <circle cx="200" cy="120" r="34" fill="none" stroke="white" strokeWidth="1.5" />
            <rect x="130" y="8" width="140" height="36" fill="none" stroke="white" strokeWidth="1.5" />
            <rect x="130" y="196" width="140" height="36" fill="none" stroke="white" strokeWidth="1.5" />
            <rect x="162" y="8" width="76" height="15" fill="none" stroke="white" strokeWidth="1.5" />
            <rect x="162" y="217" width="76" height="15" fill="none" stroke="white" strokeWidth="1.5" />
          </svg>

          <div className="relative z-10 h-full flex flex-col justify-around py-2 px-1">
            {rows.map((row, ri) => (
              <div key={ri} className="flex justify-evenly items-center">
                {row.map((p) => (
                  <PlayerDot key={p.id} player={p} selected={selectedId === p.id} onSelect={onSelect} />
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Bench */}
      <div className="px-3 py-2 border-t border-white/5 bg-black/30 flex-shrink-0">
        <div className="text-[9px] font-extrabold uppercase tracking-widest text-bf-gray mb-1.5">
          Bench
        </div>
        <div className="flex justify-around">
          {bench.map((p) => (
            <PlayerDot key={p.id} player={p} selected={selectedId === p.id} onSelect={onSelect} dimmed />
          ))}
        </div>
      </div>

      {/* Player detail / hint */}
      {selected ? (
        <PlayerDetail player={selected} onAskPlayer={onAskPlayer} />
      ) : (
        <div className="flex-1 flex items-center justify-center px-4 py-5 min-h-[72px]">
          <span className="text-xs text-bf-text/25 text-center leading-relaxed">
            Tap a player
            <br />
            to see details
          </span>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, valueClass }: { label: string; value: string; valueClass: string }) {
  return (
    <div className="flex-1 text-center">
      <div className="text-[9px] font-bold uppercase tracking-widest text-bf-gray">{label}</div>
      <div className={`text-base font-extrabold ${valueClass}`}>{value}</div>
    </div>
  );
}

function Divider() {
  return <div className="w-px bg-white/10 mx-1.5" />;
}

function PlayerDot({
  player,
  selected,
  onSelect,
  dimmed = false,
}: {
  player: SquadPlayer;
  selected: boolean;
  onSelect: (id: number) => void;
  dimmed?: boolean;
}) {
  const s = POS_STYLE[player.position];
  const code = player.web_name.split(' ').pop()!.slice(0, 3).toUpperCase();

  return (
    <button
      onClick={() => onSelect(player.id)}
      data-no-swipe
      className={`flex flex-col items-center gap-0.5 ${dimmed ? 'opacity-60' : ''}`}
    >
      <span
        className={`relative flex items-center justify-center rounded-full border-2 transition-all ${
          selected ? `w-9 h-9 ${s.dotSolid} ${s.dotBorder}` : `w-8 h-8 ${s.dotTint} ${s.dotBorder}`
        }`}
      >
        <span className={`text-[10px] font-bold ${selected ? 'text-bf-ink' : s.dotText}`}>{code}</span>
        {player.is_captain && (
          <span className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-white text-bf-ink text-[8px] font-extrabold flex items-center justify-center">
            C
          </span>
        )}
      </span>
      <span
        className={`text-[8px] font-semibold leading-none max-w-[44px] truncate ${
          selected ? 'text-white' : 'text-white/70'
        }`}
      >
        {player.web_name.split(' ').pop()}
      </span>
      <span
        className={`text-[8px] font-bold leading-none ${
          player.gw_points >= 8 ? 'text-bf-turquoise' : 'text-white/40'
        }`}
      >
        {player.gw_points}
      </span>
    </button>
  );
}

function PlayerDetail({
  player,
  onAskPlayer,
}: {
  player: SquadPlayer;
  onAskPlayer: (question: string) => void;
}) {
  const s = POS_STYLE[player.position];
  const formNum = parseFloat(player.form);
  const stats = [
    { label: 'Pts GW', value: String(player.gw_points), cls: 'text-bf-turquoise border-bf-turquoise/40' },
    { label: 'Sel.', value: `${player.sel}%`, cls: 'text-bf-cyan border-bf-cyan/40' },
    {
      label: 'Forma',
      value: player.form,
      cls: formNum >= 8 ? 'text-bf-turquoise border-bf-turquoise/40' : 'text-bf-gold border-bf-gold/40',
    },
  ];

  return (
    <div className="px-3 py-3 border-t border-white/10 bg-black/40 flex-shrink-0 space-y-2.5">
      <div className="flex items-center gap-2.5">
        {/* DS broadcast parallelogram position badge */}
        <span
          className={`inline-flex items-center justify-center w-10 h-5 text-[10px] font-black uppercase tracking-wider flex-shrink-0 ${s.badge}`}
          style={{ clipPath: 'polygon(5px 0%, 100% 0%, calc(100% - 5px) 100%, 0% 100%)' }}
        >
          {s.label}
        </span>
        <div className="min-w-0 flex-1 leading-none">
          <div className="text-xs font-extrabold text-white truncate">{player.web_name}</div>
          <div className="text-[10px] text-bf-gray mt-1">
            {player.team_short} · £{(player.price / 10).toFixed(1)}m
          </div>
        </div>
        <button
          onClick={() => onAskPlayer(`Cuéntame sobre ${player.web_name} — ¿lo alineo esta semana?`)}
          className="px-2.5 py-1.5 rounded-md bg-bf-turquoise/10 border border-bf-turquoise/40 text-bf-turquoise text-[10px] font-bold whitespace-nowrap hover:bg-bf-turquoise/20 transition-colors"
        >
          Ask AI →
        </button>
      </div>

      {/* DS scoreboard stat chips */}
      <div className="grid grid-cols-3 gap-1.5">
        {stats.map((st) => (
          <div
            key={st.label}
            className={`flex flex-col items-center rounded-md border bg-white/5 px-1 py-1.5 ${st.cls}`}
          >
            <span className="text-sm font-black leading-none">{st.value}</span>
            <span className="text-[7px] font-bold uppercase tracking-widest text-bf-gray mt-1">
              {st.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
