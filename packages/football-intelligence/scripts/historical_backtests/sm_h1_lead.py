"""H1 lead time vs the FPL-visible signal (plan): FPL signal = xGI/90 of the last 3 played matches exceeds the 6 before by >= 0.15 (>=150 min in each window),
evaluated after every match. Matched players only (gate + amendment-2 bridge). Association only."""
from __future__ import annotations
import sys, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8")
from hb_data import load_season
THR, MIN_W = 0.15, 150


def signal_series(rows):
    """rows: one player's FPL rows sorted by kick. Returns list of (kick, minutes>0, signal_true_after_this_match)."""
    pl = rows[rows.minutes > 0].reset_index(drop=True)
    out = []
    for i in range(len(pl)):
        a, b = pl.iloc[max(0, i - 2):i + 1], pl.iloc[max(0, i - 8):max(0, i - 2)]
        if len(a) < 3 or len(b) < 4: out.append((pl.kick[i], False)); continue
        ma, mb = a.minutes.sum(), b.minutes.sum()
        if ma < MIN_W or mb < MIN_W: out.append((pl.kick[i], False)); continue
        xa = (a.expected_goals.fillna(0) + a.expected_assists.fillna(0)).sum() / ma * 90
        xb = (b.expected_goals.fillna(0) + b.expected_assists.fillna(0)).sum() / mb * 90
        out.append((pl.kick[i], bool(xa - xb >= THR)))
    return out


if __name__ == "__main__":
    E = pd.read_pickle("sm_h1_events.pkl"); B = pd.read_pickle(sys.argv[1] if len(sys.argv) > 1 else "sm_bridge.pkl")
    for s in ("2024-2025", "2025-2026"):
        rows, _, _ = load_season(s); rows = rows.sort_values(["player_id", "kick"])
        fin = B[s]["final"]; ev = E[(E.season == s) & (E.c == 1) & (~E.team_driven)]
        sig = {fid: signal_series(g) for fid, g in rows.groupby("player_id")}
        matched_ev = ev[ev.player.isin(fin)]
        print(f"\n{s}: individual 'posible' events {len(ev)}, with an FPL-matched player {len(matched_ev)} ({100*len(matched_ev)/max(1,len(ev)):.0f} %)")
        leads, before, none = [], 0, 0; n_eval = 0
        for r in matched_ev.itertuples():
            ser = sig.get(fin[r.player])
            if not ser: continue
            n_eval += 1
            kicks = [k for k, _ in ser]
            # position of the alert match in the player's FPL played sequence
            idx = next((i for i, k in enumerate(kicks) if abs((k - r.t_kick).total_seconds()) < 6 * 3600), None)
            if idx is None: continue
            if any(v for _, v in ser[max(0, idx - 2):idx]): before += 1
            fut = [(j - idx) for j in range(idx, min(len(ser), idx + 7)) if ser[j][1]]
            if fut: leads.append(fut[0])
            else: none += 1
        print(f"  evaluated {n_eval}: signal already true in the 3 matches before the alert {before}; signal within the next 6 matches (incl. alert match) {len(leads)}; none {none}")
        if leads: print(f"  lead (matches from alert to first FPL signal): median {np.median(leads):.1f}, mean {np.mean(leads):.2f}; share 0 (same match) {np.mean(np.array(leads)==0):.2f}; share >=1 (Sportmonks earlier) {np.mean(np.array(leads)>=1):.2f}")
        # control: random player-match positions without a role-change event
        ev_keys = set(zip(ev.player, ev.t_match))
        rng = np.random.default_rng(3); ctrl = []
        for fid, ser in sig.items():
            for i in range(3, len(ser) - 7):
                if rng.random() < 0.15: ctrl.append(any(v for _, v in ser[i:i + 7]))
        print(f"  control: share of random player-matches with an FPL signal within 6 matches: {np.mean(ctrl):.3f} (n={len(ctrl)}) vs after an individual role change: {len(leads)/max(1,n_eval):.3f} (n={n_eval})")
