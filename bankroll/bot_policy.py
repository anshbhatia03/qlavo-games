"""Bot decisions for local simulation and future bot seats.
Bots only inspect public snapshot plus their own player state; they submit normal
engine actions and never bypass validation.
"""
from __future__ import annotations

from game_engine import GameEngine, GameState, PlayerState


class BotPolicy:
    def __init__(self, difficulty: str = "normal"):
        self.difficulty = difficulty

    def choose(self, engine: GameEngine, state: GameState, player: PlayerState) -> dict:
        if state.pending_property_id:
            prop = state.properties[state.pending_property_id]
            # Easy buys aggressively; Normal/Hard retain a small liquidity reserve.
            reserve = 0 if self.difficulty == "easy" else prop.purchase_price // 2
            if player.cash >= prop.purchase_price + reserve:
                return {"type": "BUY_PROPERTY", "propertyId": prop.id}
            return {"type": "SKIP_PROPERTY", "propertyId": prop.id}
        if state.pending_card:
            if player.properties_owned:
                pid = min(player.properties_owned, key=lambda x: state.properties[x].purchase_price)
                return {"type": "CHOOSE_LOST_PROPERTY", "propertyId": pid}
        if state.auction:
            auction = state.auction
            # Opt-out policy: hard bots sit out when they hold no tradable assets.
            if player.id not in auction.opted_out and not player.properties_owned and player.cash < 50:
                return {"type": "OPT_OUT_AUCTION"}
            my_bids = [l for l in auction.listings if player.id in l.bids]
            # SELLER FIRST: accept the best external bid on our own listing before anything else.
            mine = [l for l in auction.listings if l.seller_id == player.id and l.bids]
            if mine:
                listing = max(mine, key=lambda l: max(int(b.get("cash", 0)) + (state.properties[b["propertyId"]].purchase_price if b.get("propertyId") else 0) for b in l.bids.values()))
                external = {bidder: bid for bidder, bid in listing.bids.items() if bidder != player.id}
                if external:
                    best_bidder = max(external, key=lambda x: int(external[x].get("cash", 0)) + (state.properties[external[x]["propertyId"]].purchase_price if external[x].get("propertyId") else 0))
                    return {"type": "ACCEPT_AUCTION", "playerId": best_bidder, "listingId": listing.id}
            if not auction.listings:
                if player.properties_owned:
                    pid = max(player.properties_owned, key=lambda x: state.properties[x].purchase_price)
                    return {"type": "LIST_AUCTION_PROPERTY", "propertyId": pid}
                return {"type": "OPT_OUT_AUCTION"}
            # Bid on the best-value listing where our offer would be the strongest.
            open_listings = [l for l in auction.listings if l.seller_id != player.id]  # never bid on your own listing
            for listing in sorted(open_listings, key=lambda l: -state.properties[l.property_id].purchase_price):
                current_best = max((int(b.get("cash", 0)) + (state.properties[b["propertyId"]].purchase_price if b.get("propertyId") else 0) for b in listing.bids.values()), default=0)
                target_value = int(state.properties[listing.property_id].purchase_price * (1.1 if self.difficulty != "easy" else 0.9))
                if target_value <= current_best:
                    continue
                affordable_props = [pid2 for pid2 in player.properties_owned
                                    if pid2 not in {l2.property_id for l2 in auction.listings}
                                    and pid2 != listing.property_id]
                affordable_props.sort(key=lambda x: state.properties[x].purchase_price)
                cash_reserve = 0 if self.difficulty == "easy" else 100
                spend = min(max(target_value - sum(state.properties[x].purchase_price for x in affordable_props[:1]), 0), max(player.cash - cash_reserve, 0))
                bid_prop = affordable_props[0] if affordable_props and sum([state.properties[affordable_props[0]].purchase_price]) + spend >= min(target_value, current_best + 20) else None
                if bid_prop or spend > 0:
                    action = {"type": "SUBMIT_AUCTION_OFFER", "listingId": listing.id}
                    if bid_prop: action["propertyId"] = bid_prop
                    if spend > 0: action["cash"] = int(spend)
                    return action
            if player.id not in [l.seller_id for l in auction.listings]:
                # We are a pure bidder here with nothing more to add.
                if my_bids:
                    return {"type": "END_TURN"}
                return {"type": "OPT_OUT_AUCTION"}
        if state.turn_phase in {"PROPERTY_MANAGEMENT", "READY_TO_ROLL"}:
            if state.turn_phase == "PROPERTY_MANAGEMENT":
                upgrades = [pid for pid in player.properties_owned if state.properties[pid].kind == "city" and state.properties[pid].building_level < 3 and engine.owns_complete_color_set(state, player.id, state.properties[pid].color_group or "") and player.cash >= state.properties[pid].building_price]
                if upgrades and self.difficulty != "easy":
                    return {"type": "UPGRADE_PROPERTY", "propertyId": upgrades[0]}
            return {"type": "ROLL_DICE"}
        if state.turn_phase == "JAILED_DECISION":
            if player.cash >= int(engine.balance["jailFine"]) + 200:
                return {"type": "PAY_JAIL_FINE"}
            return {"type": "STAY_IN_JAIL"}
        if state.turn_phase == "TURN_END":
            return {"type": "END_TURN"}
        return {"type": "ROLL_DICE"}
