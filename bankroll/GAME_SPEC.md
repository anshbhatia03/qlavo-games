# Bankroll — Game Specification

## Product
Fast 2–4 player real-estate race inspired by the gameplay loop of Plato's Bankroll, not a Monopoly clone. The visual identity is original: pale mint board, rounded white cards, soft color-group bands, clean typography, and compact mobile controls.

## Objective
The first active player whose authoritative net worth reaches the host-selected target ($3,000 / $5,000 / $7,000) wins immediately. A game also ends when only one active player remains, or when a configured 30/50-round cap is reached. At the cap, rank by net worth, then cash, then property purchase value, then deterministic seed order.

## Turn loop
1. `TURN_START`: management is available.
2. Player may upgrade or sell owned properties.
3. Player rolls one server-generated d6.
4. A roll of 6 grants another roll after landing resolution.
5. Move clockwise, award $200 exactly when crossing Start, then resolve the landing space.
6. Unowned city/public property presents BUY or SKIP; no forced auction.
7. Owned property charges rent; debt is allowed.
8. Resolve Lucky Card / Jail / Auction effects.
9. Check bankruptcy and victory after every economic mutation.
10. End turn unless another six or a pending decision remains.

## Required mechanics
- City rent scales at one owned, two owned, complete set, then upgrade levels 1–3. A complete colour set unlocks upgrades during the owner's pre-roll or bonus-roll management phase.
- Airport, Harbor, Railway, and Electricity form one public set: rent is $35/$70/$105/$150 on every public property when the owner holds 1/2/3/4.
- Sale returns floor(80% of original purchase price); buildings are a separate configurable liquidation rule.
- Jail lasts 3 turns; on each jailed turn choose STAY or pay $150.
- Auction is a property-for-property exchange: initiator offers one property, other players offer one property, initiator accepts one or cancels. Successful participants each receive $100.
- General trading is not assumed outside Auction; the Auction flow is the Bankroll-specific trade mechanic.
- Lucky Cards are data-driven and may gain/lose money, pay/receive from opponents, move, jail, or force property loss.
- Cash can be negative; bankruptcy is cash <= -$500 OR net worth <= $0. Bankrupt properties return to bank.

## Scope assumptions
- Existing production uses FastAPI + WebSockets. We retain this stack for the first fully playable implementation and isolate the pure engine so a TypeScript/Socket.IO service can replace the transport later.
- Starting cash and later-player bonuses are config values, not claimed canonical Plato values.
- Board/property names are original; no Plato branding or artwork is used.
