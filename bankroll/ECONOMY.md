# Economy and Balance

All tunables live in `config/balance.json` and `config/board.json`.

## Starting economy

- Starting cash by randomized turn order: `$1,000`, `$1,050`, `$1,100`, `$1,150`.
- Passing START pays `$200`.
- Cash may be negative.
- A player is bankrupt at cash `<= -$500` or net worth `<= $0`.
- Selling a property returns 80% of its purchase price; buildings are removed without a refund.

## Net worth

`calculate_net_worth(player)` = cash + purchase price of owned properties + actual upgrade price paid for every building level.

The same server-side calculation is used by snapshots, victory, rankings, bankruptcy checks, bots, and tests.

## City rent

Every city defines these data-driven values:

- `baseRent`: rent while the owner has one city in that colour group;
- `rentOwned2`: rent on every owned city after acquiring two in the group;
- `rentWithSet`: rent after completing the colour set;
- `buildingPrice`: the per-level upgrade cost;
- `rentBuilding1` through `rentBuilding3`: rent after each upgrade.

A full colour set is required before upgrading. Upgrades are available during the owner's pre-roll management phase and bonus-roll phase. More expensive groups have higher rents and higher upgrade prices.

Contract examples:

- Rio: `$30` with one lime, `$60` with two, `$90` with the full set, then `$150/$230/$320` after upgrades costing `$100` each.
- London/Tokyo: `$70` with one coral and `$150` with two; the full set raises them to `$230`.
- New York: `$80` alone, `$150` with two corals, `$250` with the full set; upgrades cost `$220`.

## Public-property rent

Airport, Harbor, Railway, and Electricity form one four-property public set. Each owned public property charges:

- 1 owned: `$35`;
- 2 owned: `$70` each;
- 3 owned: `$105` each;
- all 4: `$150` each.

## Transaction rules

- Landing on another player's property pays the current server-calculated rent.
- Landing on your own property never transfers cash.
- Rent, purchases, upgrades, salary, cards, bankruptcy and victory are server-authoritative.
- The turn advances automatically after rent or completed landing resolution unless a six grants a bonus roll or a decision is pending.

## Pacing target

Games should usually resolve in roughly 20–35 rounds. Tune config values first; do not duplicate economy numbers in client-only logic.
