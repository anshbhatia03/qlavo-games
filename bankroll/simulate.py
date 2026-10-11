#!/usr/bin/env python3
"""Run deterministic local Bankroll bot simulations.

Usage: python3 simulate.py --games 1000 --players 4 --seed 42
"""
from __future__ import annotations

import argparse
import statistics
from collections import Counter

from bot_policy import BotPolicy
from game_engine import GameEngine, GameState


def run_one(seed: int, players: int, target: int, limit: int) -> tuple[int, str, str]:
    engine = GameEngine(seed=seed)
    specs = [{"id": f"bot{i}", "username": f"Bot {i+1}", "isBot": True} for i in range(players)]
    state = engine.new_game(specs, target, limit)
    policies = {p["id"]: BotPolicy(["easy", "normal", "hard", "normal"][i]) for i, p in enumerate(specs)}
    actions = 0
    while state.phase != "GAME_OVER" and actions < 8000:
        if state.auction:
            # Auction portal: every bot seat may list / bid / opt out / accept each cycle.
            progressed = False
            for seat in [p for p in state.players.values()]:
                if not state.auction:
                    break
                policy = policies[seat.id]
                if seat.id in state.auction.opted_out:
                    continue
                action = policy.choose(engine, state, seat)
                if action.get("type") == "END_TURN":
                    continue
                try:
                    engine.apply(state, seat.id, action)
                    progressed = True
                    actions += 1
                except Exception:
                    continue
            if not state.auction:
                continue
            if progressed:
                continue
            # Nobody can act: resolve the stale auction after a few quiet cycles.
            if state.auction:
                state.auction.quiet_cycles += 1
                if state.auction.quiet_cycles >= 3:
                    current = engine.current_player(state)
                    engine._emit(state, "AUCTION_CANCELLED", current.id, text="Everyone passed — Auction closed.")
                    state.auction = None
                    engine._after_landing(state, current)
            actions += 1
            continue
        player = engine.current_player(state)
        policy = policies[player.id]
        action = policy.choose(engine, state, player)
        actor = player
        try:
            engine.apply(state, actor.id, action)
        except Exception as exc:
            # A bot must never wedge a game. Skip/cancel the legal pending choice.
            if state.pending_property_id:
                action = {"type": "SKIP_PROPERTY", "propertyId": state.pending_property_id}
            elif state.pending_card:
                pid = next(iter(actor.properties_owned), None)
                if not pid:
                    state.pending_card = None; state.turn_phase = "TURN_END"; continue
                action = {"type": "CHOOSE_LOST_PROPERTY", "propertyId": pid}
            elif state.auction and actor.id == state.auction.initiator_id:
                action = {"type": "CANCEL_AUCTION"}
            else:
                raise RuntimeError(f"bot deadlock at {state.turn_phase}: {exc}") from exc
            engine.apply(state, actor.id, action)
        actions += 1
    if state.phase != "GAME_OVER":
        raise RuntimeError(f"game did not terminate after {actions} actions")
    return state.current_round, state.win_reason, state.winner_id or "none"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--players", type=int, default=4, choices=(2, 3, 4))
    ap.add_argument("--target", type=int, default=3000, choices=(3000, 5000, 7000))
    ap.add_argument("--limit", type=int, default=50, choices=(0, 30, 50))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rounds, reasons, winners = [], Counter(), Counter()
    for i in range(args.games):
        r, reason, winner = run_one(args.seed + i, args.players, args.target, args.limit)
        rounds.append(r); reasons[reason.split(".")[0]] += 1; winners[winner] += 1
    print(f"Games played: {args.games}")
    print(f"Average rounds: {statistics.mean(rounds):.2f}")
    print(f"Median rounds: {statistics.median(rounds):.1f}")
    print(f"Max rounds: {max(rounds)}")
    print(f"Endings: {dict(reasons)}")
    print(f"Wins: {dict(winners)}")


if __name__ == "__main__":
    main()
