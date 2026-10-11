# Bankroll

A fast, original real-estate race inspired by the gameplay loop of Plato's Bankroll. It is **not** a Monopoly implementation and uses no Plato branding, artwork, or proprietary assets.

## Live game

`https://qlavo.online/bankroll/`

## Rules implemented

- 2–4 players, with Easy/Normal/Hard bot seats available from the lobby.
- Host chooses `$3,000`, `$5,000`, or `$7,000` target and 30/50/unlimited rounds.
- Server-authoritative one-die movement; rolling 6 grants another roll.
- `$200` salary whenever movement crosses Start.
- Buy or skip an unowned city/public property after landing.
- Complete color sets increase rent and unlock up to 3 buildings per city.
- Public-property rent multiplies by the number owned by the landlord.
- Sell for `floor(purchasePrice * 0.8)`.
- Jail: 3 turns or `$150` release choice.
- Auction: initiator offers one property, other players offer one property, initiator accepts or cancels; a completed swap gives both participants `$100`.
- Lucky Cards are data-driven and include consequential effects such as losing a property, foreclosure, per-building repairs, per-property costs, jail, movement, and cash windfalls.
- Cash may be negative; bankruptcy is cash `<= -$500` or net worth `<= $0`; properties return to the bank.
- Net worth is calculated only by the authoritative engine.

## Development

```bash
cd /root/bankroll
python3 -m unittest discover -s tests -v
python3 simulate.py --games 1000 --players 4 --target 3000 --limit 50
```

Run locally:

```bash
/root/.hermes/hermes-agent/venv/bin/python3 -m uvicorn app:app --host 127.0.0.1 --port 8033 --reload
```

The production service is `bankroll.service`; Caddy exposes it at `/bankroll/`.

## Architecture

- `game_engine.py`: pure authoritative state transitions, configuration-driven economics, deterministic RNG injection, events, snapshots.
- `config/board.json`: original board/property data.
- `config/balance.json`: every balance knob, including explicit assumptions.
- `config/lucky_cards.json`: weighted event definitions.
- `bot_policy.py`: non-cheating Easy/Normal/Hard bot decisions using legal engine actions.
- `simulate.py`: local bot simulation and termination/balance smoke test.
- `app.py`: FastAPI room transport and WebSockets; it does not calculate rent, net worth, victory, or dice values.
- `tests/test_game_engine.py`: engine unit tests for movement, salary, purchase, rent, sets, buildings, public properties, sale, jail, auction, bankruptcy, and authoritative randomness.

## Client protocol

Canonical actions are:

```text
ROLL_DICE
BUY_PROPERTY { propertyId }
SKIP_PROPERTY { propertyId }
UPGRADE_PROPERTY { propertyId }
SELL_PROPERTY { propertyId }
PAY_JAIL_FINE
STAY_IN_JAIL
CHOOSE_LOST_PROPERTY { propertyId }
START_AUCTION { propertyId }
SUBMIT_AUCTION_OFFER { propertyId }
ACCEPT_AUCTION { playerId }
CANCEL_AUCTION
END_TURN
```

The client sends intent only. The server validates the current turn phase and mutates state through `GameEngine.apply`.

## Known tuning assumptions

Starting cash (`$1,500`), building net-worth value, rent tables, property prices, and the starting-order bonus array are configurable assumptions. They live in `config/balance.json` and `config/board.json` so they can be tuned without editing UI components or rule code.
