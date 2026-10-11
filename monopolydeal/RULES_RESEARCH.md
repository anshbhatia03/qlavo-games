# Monopoly Deal rules research and implementation contract

## Sources

- Hasbro instruction page: https://instructions.hasbro.com/en-us/instruction/monopoly-deal-card-game-instructions
- Hasbro official PDF used for the card text: https://assets-us-01.kc-usercontent.com/500e0a65-283d-00ef-33b2-7f1f20488fe2/286ba6bc-f22d-4c16-9ef2-4848105de3ff/E3113IN14_INST_MONOPOLY_DEAL_CARD_GAME_FAR.pdf
- Hasbro FAQ — turn order: https://hasbro-new.custhelp.com/app/answers/detail/a_id/929/~/monopoly-deal---what-do-i-do-on-my-turn%3F
- Hasbro FAQ — steals from complete sets: https://hasbro-new.custhelp.com/app/answers/detail/a_id/926/~/monopoly-deal---can-i-steal-properties-from-full-sets-using-my-action-cards%3F
- Hasbro FAQ — Just Say No does not count as one of the three plays: https://hasbro-new.custhelp.com/app/answers/detail/a_id/953/~/monopoly-deal-%E2%80%93-does-a-just-say-no-card-count-towards-my-3-card-maximum-per

## Standard rules implemented

- 2–5 players; deal five cards each.
- At the start of a turn, draw two cards. If the hand is empty at the start of that turn, draw five instead.
- Play 0–3 cards in any combination of money, properties, and actions.
- At the end of a turn, discard to a maximum hand size of seven.
- The first player with three complete property sets in three different colors and at least $10M in cash wins.
- The four Quick Start reference cards are not playable. The box has 110 cards; this engine has the 106 playable cards.
- Any non-property card from hand—including action, Rent, House, and Hotel cards—may be converted to cash. The conversion is permanent: it becomes an ordinary money card with the same value and cannot later be played as an action. Property cards cannot be converted to cash.
- Used actions go to the discard pile. The discard pile is reshuffled when the draw pile is empty.
- Rent is calculated from the number of properties in the selected color, with the standard rent schedule. Two-color Rent charges every opponent; Wild Rent targets one opponent.
- Deal Breaker takes a complete set, including buildings. Sly Deal steals one property outside a complete set. Forced Deal swaps two properties outside complete sets. Debt Collector demands $5M. It's My Birthday demands $2M from each opponent. Pass Go draws two. Double The Rent pairs with a Rent card and doubles its demand.
- Just Say No cancels an action against the responding player and is not one of that player's three plays. A Just Say No can be countered by another Just Say No.
- Houses add $3M and Hotels add $4M to a complete set's rent. A set may have one House and one Hotel; a Hotel requires a House. Buildings cannot be placed on Railroads or Utilities.
- Debts are paid only from cash cards and Properties on the table: cash cards, Properties, or a combination. Cards from hand cannot pay; there is no change. If the payer cannot cover the debt, all available table cards are paid. Cash cards received as payment remain cash cards. Properties paid as rent or debt remain Properties in the receiver's property area and never enter the cash pile.
- Buildings are separate table cards: they transfer with a Deal Breaker set, become inactive when a set is broken, and may be moved to another eligible complete set during the owner's turn without using a play.
- Wild Property cards show their currently assigned color and can be moved between eligible colors during the owner's turn. A complete set must include at least one standard property card.

## Explicit UX choices

- The table shows public property areas and cash totals to everyone; private hands are shown only to their owner.
- Payment selection is explicit so the payer chooses which table cards to use, preserving the no-change rule.
- Targeted actions pause for the target's response before resolving, rather than silently bypassing Just Say No.
