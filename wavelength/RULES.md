# Wavelength — Rules (final)

Individual free-for-all, played live on call. No typing anywhere.

## Setup
- 2–8 players, everyone plays solo (best with 3).
- Win score: **10 points**. Most points wins; a strict single leader at ≥10 ends the match.
- Psychic rotates through all players in join order.

## Round loop
1. **Spin** — server picks an unused spectrum + secret target (0–100). The colour wheel spins for
   everyone; only the Psychic's wheel shows colours, and yellow decelerates onto their secret target.
   Guessers see a neutral dark wheel spinning — zero colour hints.
2. **Clue** — Psychic says ONE clue out loud on the call for where yellow landed, then taps go-live.
3. **Dial** — every other player privately sets their own dial (drag or nudge) and locks.
4. **Reveal** — the tiered colour ring spins in around the true target and everyone's pins drop in,
   coloured by what they scored.

## Scoring tiers (distance = |your dial − target|)
- inside **yellow** (≤5) → **+5**
- inside **purple** (≤12) → **+3**
- anywhere else on **pink** → **+1**

## Secrecy contract
- Target + colour zones visible ONLY to the psychic until reveal.
- Guessers never see the target, the bands, or other players' dial values before locking.

## Acceptance fixtures
- dist ≤5 → 5 pts; 5<d≤12 → 3 pts; d>12 → 1 pt.
- Reveal fires only when ALL guessers locked (host can force it as AFK escape hatch).
- Tie at ≥10 → play continues; unique leader ≥10 → match over.
- `submit_clue` action does not exist on the wire (voice-only enforced by protocol).
