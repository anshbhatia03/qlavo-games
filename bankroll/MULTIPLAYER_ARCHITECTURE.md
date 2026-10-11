# Multiplayer Architecture

## Current implementation
- FastAPI HTTP room creation/join endpoints.
- Authoritative room engine in Python, one async lock per room.
- WebSocket snapshots to every connected player after each validated action.
- Server-generated dice and Lucky Card randomness.
- Session reconnect via room/player ID stored client-side; the server keeps room state in memory for the current process.

## Production extension
```text
Browser client
  -> HTTPS + WebSocket
  -> Room gateway / auth / reconnect grace
  -> GameEngine (pure transitions)
  -> Redis room lock + snapshot for horizontal scaling
  -> PostgreSQL games, players, events, results
```

The transport should call `validateAction(state, playerId, action)` then `applyAction(state, action, rng)` and broadcast a new snapshot plus events. The client must never be trusted for dice, Lucky Card selection, rent, ownership, net worth, or victory.

## Reconnect/forfeit
A disconnect marks `connected=false` and starts a configurable grace timer. Reconnect restores the same player ID and full snapshot. After grace, the player is forfeited; their assets return to the bank and victory is checked.

## Bots
Bots consume only public state plus their own private decision context. A bot adapter submits the same validated actions as a human. The first milestone supports bot simulation locally; transport-level bot seats can be enabled without changing rules.

## Events
Every state mutation creates `{id, timestamp, type, actorId, targetId?, amount?, propertyId?, metadata?}`. Snapshots are sufficient for reconnect; events drive UI animations and the compact event feed.
