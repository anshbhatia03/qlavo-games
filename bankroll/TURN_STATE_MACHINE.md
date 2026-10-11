# Turn State Machine

```text
TURN_START
  -> PROPERTY_MANAGEMENT
  -> READY_TO_ROLL
  -> DICE_ROLL
  -> MOVEMENT
  -> SPACE_RESOLUTION
      -> PROPERTY_DECISION (unowned city/public)
      -> CARD_DECISION (Lucky Card requiring property choice)
      -> JAILED_DECISION
      -> AUCTION
      -> EXTRA_ROLL (roll == 6)
      -> TURN_END
  -> GAME_OVER
```

## Legal actions
- `PROPERTY_MANAGEMENT`: `UPGRADE_PROPERTY`, `SELL_PROPERTY`, `START_AUCTION` if landed/allowed.
- `READY_TO_ROLL`: `ROLL_DICE`.
- `DICE_ROLL`: no client action; server generates 1–6.
- `MOVEMENT`: no client action; server animates/broadcasts path.
- `PROPERTY_DECISION`: `BUY_PROPERTY` or `SKIP_PROPERTY` for the exact landed property only.
- `CARD_DECISION`: `CHOOSE_LOST_PROPERTY` when a card requires a choice.
- `JAILED_DECISION`: `PAY_JAIL_FINE` or `STAY_IN_JAIL`.
- `AUCTION`: initiator `SUBMIT_AUCTION_OFFER`, any opponent `SUBMIT_AUCTION_OFFER`, initiator `ACCEPT_AUCTION_OFFER` or `CANCEL_AUCTION`.
- `EXTRA_ROLL`: `ROLL_DICE` after landing and effects resolve.
- `TURN_END`: server advances to next active player.

## Transition rules
- No automatic purchase.
- Passing Start is detected from the movement path, never from final position alone.
- A six only enables an extra roll after all landing effects and pending decisions resolve.
- A property decision, card choice, or auction pauses the turn.
- Bankruptcy/victory checks run after movement effects, rent, purchases, sales, upgrades, trades, card effects, salary, and bail.
- If the round cap is reached after the final active player completes their turn, deterministic ranking ends the game.
