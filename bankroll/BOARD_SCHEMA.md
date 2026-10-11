# Board Schema

Board data lives in `config/board.json`; UI reads the same data through server snapshots.

```json
{
  "id": "jakarta",
  "kind": "city",
  "name": "Jakarta",
  "colorGroup": "magenta",
  "purchasePrice": 170,
  "baseRent": 45,
  "rentOwned2": 120,
  "rentWithSet": 120,
  "rentBuilding1": 220,
  "rentBuilding2": 330,
  "rentBuilding3": 460,
  "buildingPrice": 130,
  "ownerId": null,
  "buildingLevel": 0
}
```

Supported kinds: `start`, `city`, `public`, `lucky`, `auction`, `jail`, `goto_jail`, `rest`.

A `public` property has `purchasePrice`, `baseRent`, `publicType`, and `rentByOwnedCount`. The four public properties share the `[35,70,105,150]` rent ladder.

The board has 28 perimeter spaces: 4 corners plus 6 spaces per side. Names and economics are original/tunable, and the visual order matches the supplied reference board. The `START` corner is the authoritative starting square; all players begin there and travel clockwise.
