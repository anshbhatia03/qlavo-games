# Game State Contract

The server owns one `GameState` per room. The client receives snapshots and structured events; it never calculates victory or rent authoritatively.

```text
GameState {
  roomCode, phase, currentRound, roundLimit, targetWorth, seed
  turn: { playerId, phase, roll, pendingMove, extraRoll }
  players: Player[]
  properties: Property[]
  luckyDeckState
  auction: AuctionState | null
  pendingPropertyDecision: PropertyDecision | null
  pendingCardDecision: CardDecision | null
  events: GameEvent[]
}

Player {
  id, username, avatar, color, cash, netWorth, boardPosition
  propertiesOwned[], jailTurnsRemaining, bankrupt, forfeited
  connected, isBot, wins
}

Property {
  id, kind, name, colorGroup, purchasePrice, baseRent
  rentWithSet, rentBuilding1, rentBuilding2, rentBuilding3
  buildingPrice, ownerId, buildingLevel
}
```

## Invariants
- Exactly one active `turn.playerId`.
- Only the server changes cash, ownership, position, buildings, jail, deck, or RNG state.
- A property has zero or one owner; bankrupt/forfeited players own nothing.
- `calculateNetWorth(player)` is the only victory valuation path.
- A player cannot act while bankrupt, forfeited, disconnected past grace, or outside the legal turn phase.
- `pendingPropertyDecision` blocks turn completion until BUY/SKIP.
- `pendingCardDecision` blocks turn completion until a property-loss choice is made.
- A successful Auction atomically swaps exactly two properties and awards both participants $100.
- Every meaningful mutation emits a `GameEvent` and runs bankruptcy/victory checks.
