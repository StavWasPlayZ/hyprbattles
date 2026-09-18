#!/usr/bin/env python3
"""Unit tests for the window battles: the rules, and the daemon around them.

The rules (lib/battle_rules.py) are pure - no evdev, no sockets, no screen -
so the type ring, the damage formula, the odds, the menus and every timeout
run here against fixtures with seeded generators. The daemon's own judgement
calls (does this collision become a battle, does the switch stop it, what may
a result do to a window) are exercised against a bare instance, without a
compositor.

What is not covered here is what cannot be: the forwarded controller events
themselves, which need the gamepad plugin running and a pad plugged in.
"""

import importlib.machinery
import importlib.util
import json
import os
import random
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import battle_rules as battles                                # noqa: E402


def load_ctl():
    loader = importlib.machinery.SourceFileLoader(
        "battles_ctl", os.path.join(ROOT, "bin", "battles-ctl"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_daemon():
    loader = importlib.machinery.SourceFileLoader(
        "battles_daemon", os.path.join(ROOT, "bin", "battles"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


bd = load_daemon()


def window(address="0x1", klass="foot", size=(800, 600)):
    return {"address": address, "class": klass, "initialClass": klass,
            "size": list(size), "title": klass}


class Types(unittest.TestCase):
    def test_classes_map_to_types(self):
        self.assertEqual(battles.type_of("foot"), "SHELL")
        self.assertEqual(battles.type_of("Alacritty"), "SHELL")
        self.assertEqual(battles.type_of("firefox"), "NET")
        self.assertEqual(battles.type_of("jetbrains-webstorm"), "CODE")
        self.assertEqual(battles.type_of("Slack"), "CHAT")
        self.assertEqual(battles.type_of("mpv"), "MEDIA")
        self.assertEqual(battles.type_of("steam"), "PIXEL")

    def test_anything_unrecognised_is_glass(self):
        self.assertEqual(battles.type_of("org.gnome.Nautilus"), "GLASS")
        self.assertEqual(battles.type_of(""), "GLASS")
        self.assertEqual(battles.type_of(None), "GLASS")

    def test_the_ring_beats_the_next_and_bounces_off_the_previous(self):
        for index, kind in enumerate(battles.TYPES):
            following = battles.TYPES[(index + 1) % len(battles.TYPES)]
            self.assertEqual(battles.effectiveness(kind, following), 2.0)
            self.assertEqual(battles.effectiveness(following, kind), 0.5)

    def test_a_type_is_neutral_against_itself(self):
        for kind in battles.TYPES:
            self.assertEqual(battles.effectiveness(kind, kind), 1.0)

    def test_every_type_has_a_way_out(self):
        # No type may be beaten by every other one: with a ring, each type
        # resists exactly one and is weak to exactly one.
        for kind in battles.TYPES:
            weaknesses = [other for other in battles.TYPES
                          if battles.effectiveness(other, kind) > 1.0]
            self.assertEqual(len(weaknesses), 1, kind)


class Creatures(unittest.TestCase):
    def test_the_same_window_always_makes_the_same_creature(self):
        first = battles.creature(window("0xdeadbeef", "firefox"))
        second = battles.creature(window("0xdeadbeef", "firefox"))
        self.assertEqual(first, second)

    def test_a_different_window_makes_a_different_creature(self):
        first = battles.creature(window("0xdeadbeef"))
        second = battles.creature(window("0xfeedface"))
        self.assertNotEqual((first["attack"], first["defense"], first["speed"]),
                            (second["attack"], second["defense"], second["speed"]))

    def test_a_bigger_window_is_a_higher_level(self):
        small = battles.creature(window(size=(400, 300)))
        large = battles.creature(window(size=(1920, 1080)))
        self.assertLess(small["level"], large["level"])

    def test_levels_stay_inside_their_bounds(self):
        for size in ((1, 1), (20, 20), (7680, 4320), (99999, 99999)):
            level = battles.level_of(window(size=size))
            self.assertGreaterEqual(level, 3)
            self.assertLessEqual(level, 40)

    def test_a_nonsense_window_still_produces_a_fighter(self):
        for broken in ({}, {"address": None}, {"size": "not a size"},
                       {"size": []}, {"address": "not hex", "class": None}):
            fighter = battles.creature(broken)
            self.assertGreater(fighter["maxHp"], 0)
            self.assertEqual(len(fighter["moves"]), 4)
            self.assertIn(fighter["type"], battles.TYPES)

    def test_four_moves_two_of_them_its_own_type(self):
        for klass in ("foot", "firefox", "mpv", "steam", "nautilus"):
            fighter = battles.creature(window("0xabc123", klass))
            self.assertEqual(len(fighter["moves"]), 4)
            own = [move for move in fighter["moves"]
                   if move["type"] == fighter["type"]]
            self.assertGreaterEqual(len(own), 2)
            names = [move["name"] for move in fighter["moves"]]
            self.assertEqual(len(set(names[:2])), 2, "own moves are distinct")

    def test_the_name_drops_a_reverse_dns_prefix(self):
        self.assertEqual(battles.display_name(window(klass="org.gnome.Nautilus")),
                         "NAUTILUS")
        self.assertEqual(battles.display_name(window(klass="foot")), "FOOT")

    def test_a_long_name_is_cut_to_fit_the_plate(self):
        name = battles.display_name(window(klass="a-very-long-window-class"))
        self.assertLessEqual(len(name), 12)


class Damage(unittest.TestCase):
    def setUp(self):
        self.attacker = battles.creature(window("0x10", "foot"))
        self.defender = battles.creature(window("0x20", "firefox"))

    def move(self, kind, power=60):
        return {"name": "TEST", "type": kind, "power": power, "accuracy": 1.0}

    def test_damage_is_never_zero(self):
        weak = dict(self.attacker, attack=1, level=3)
        tough = dict(self.defender, defense=999)
        amount, _, _ = battles.damage(weak, tough, self.move("GLASS", 10),
                                      random.Random(1))
        self.assertGreaterEqual(amount, 1)

    def test_a_super_effective_hit_beats_a_resisted_one(self):
        # Same roll both times, so only the type multiplier differs.
        strong, multiplier, _ = battles.damage(
            self.attacker, self.defender, self.move("GLASS"), random.Random(7))
        self.assertEqual(multiplier, battles.effectiveness("GLASS", self.defender["type"]))

        weak_type = battles.TYPES[(battles.TYPES.index(self.defender["type"]) + 1)
                                  % len(battles.TYPES)]
        weak, weak_multiplier, _ = battles.damage(
            self.attacker, self.defender, self.move(weak_type), random.Random(7))
        self.assertGreater(multiplier, weak_multiplier)
        self.assertGreater(strong, weak)

    def test_more_defense_means_less_damage(self):
        soft = dict(self.defender, defense=10)
        hard = dict(self.defender, defense=60)
        first, _, _ = battles.damage(self.attacker, soft, self.move("GLASS"),
                                     random.Random(3))
        second, _, _ = battles.damage(self.attacker, hard, self.move("GLASS"),
                                      random.Random(3))
        self.assertGreater(first, second)

    def test_same_type_attacks_hit_harder(self):
        own = dict(self.attacker)
        matched, _, _ = battles.damage(own, self.defender,
                                       self.move(own["type"]), random.Random(5))
        # A neutral borrowed type, so only the same-type bonus differs.
        neutral = None
        for kind in battles.TYPES:
            if (kind != own["type"]
                    and battles.effectiveness(kind, self.defender["type"]) == 1.0
                    and battles.effectiveness(own["type"], self.defender["type"]) == 1.0):
                neutral = kind
                break
        if neutral is None:
            self.skipTest("no neutral comparison for this pairing")
        borrowed, _, _ = battles.damage(own, self.defender, self.move(neutral),
                                        random.Random(5))
        self.assertGreater(matched, borrowed)

    def test_accuracy_is_a_roll_not_a_coin_flip(self):
        always = {"name": "A", "type": "GLASS", "power": 10, "accuracy": 1.0}
        never = {"name": "B", "type": "GLASS", "power": 10, "accuracy": 0.0}
        generator = random.Random(11)
        self.assertTrue(all(battles.hits(always, generator) for _ in range(50)))
        self.assertFalse(any(battles.hits(never, generator) for _ in range(50)))

    def test_effect_notes(self):
        self.assertEqual(battles.effect_note(2.0), "It's super effective!")
        self.assertEqual(battles.effect_note(0.5), "It's not very effective...")
        self.assertEqual(battles.effect_note(1.0), "")


class Trigger(unittest.TestCase):
    """The 25% roll. This is the one number the whole feature turns on."""

    def test_the_odds_are_one_in_four(self):
        self.assertEqual(battles.BATTLE_CHANCE, 0.25)

    def test_a_seeded_generator_gives_a_quarter_over_the_long_run(self):
        generator = random.Random(1234)
        hits = sum(1 for _ in range(20000) if battles.should_battle(generator))
        self.assertAlmostEqual(hits / 20000.0, 0.25, delta=0.02)

    def test_the_roll_is_reproducible(self):
        first = [battles.should_battle(random.Random(seed)) for seed in range(20)]
        second = [battles.should_battle(random.Random(seed)) for seed in range(20)]
        self.assertEqual(first, second)

    def test_zero_chance_never_fires(self):
        generator = random.Random(9)
        self.assertFalse(any(battles.should_battle(generator, 0.0)
                             for _ in range(500)))

    def test_a_rematch_between_the_same_windows_seeds_the_same(self):
        self.assertEqual(battles.battle_seed("0xa", "0xb"),
                         battles.battle_seed("0xa", "0xb"))
        self.assertNotEqual(battles.battle_seed("0xa", "0xb"),
                            battles.battle_seed("0xb", "0xa"))


class TurnLoop(unittest.TestCase):
    def fight(self, seed=1, now=0.0):
        return battles.Battle(battles.creature(window("0x10", "foot")),
                              battles.creature(window("0x20", "firefox")),
                              now, rng=random.Random(seed), direction="left",
                              monitor="DP-4")

    def run_to_the_end(self, fight, pick=0, limit=900):
        """Play it out, always choosing FIGHT and then move `pick`."""
        now = 0.0
        for _ in range(limit):
            if fight.finished(now):
                return now
            if fight.phase == "action":
                fight.cursor = 0            # FIGHT
                fight.confirm(now)
            elif fight.phase == "menu":
                fight.play(pick, now)
            else:
                now += 0.05
                if not fight.advance(now):
                    now += 5.0
                    fight.tick(now)
        self.fail("the battle never ended")

    def to_the_action_menu(self, fight):
        now = 0.0
        while fight.phase != "action" and now < 30:
            now += 0.1
            fight.tick(now)
        self.assertEqual(fight.phase, "action")
        return now

    def to_the_move_menu(self, fight):
        now = self.to_the_action_menu(fight)
        fight.cursor = 0
        fight.confirm(now)
        self.assertEqual(fight.phase, "menu")
        return now

    def test_it_opens_on_the_intro_and_reaches_the_action_menu(self):
        fight = self.fight()
        self.assertEqual(fight.phase, "intro")
        self.assertIn("blocked the way", fight.message)
        self.to_the_action_menu(fight)
        self.assertTrue(fight.choosing)
        self.assertFalse(fight.menu_open)
        self.assertEqual(fight.snapshot()["actions"], ["FIGHT", "RUN"])

    def test_fight_opens_the_move_list_and_b_backs_out_of_it(self):
        fight = self.fight()
        now = self.to_the_move_menu(fight)
        self.assertTrue(fight.menu_open)
        self.assertTrue(fight.back(now))
        self.assertEqual(fight.phase, "action")
        self.assertEqual(fight.cursor, 0)
        # There is nothing to back out of anywhere else.
        self.assertFalse(fight.back(now))

    def test_the_action_cursor_walks_up_and_down(self):
        fight = self.fight()
        self.to_the_action_menu(fight)
        self.assertEqual(fight.cursor, 0)
        self.assertTrue(fight.move_cursor("d"))
        self.assertEqual(fight.cursor, 1)
        self.assertFalse(fight.move_cursor("d"))
        self.assertTrue(fight.move_cursor("u"))
        self.assertEqual(fight.cursor, 0)
        # Sideways means nothing in a one-column list.
        self.assertFalse(fight.move_cursor("l"))

    def test_every_battle_ends_with_a_result(self):
        for seed in range(12):
            fight = self.fight(seed)
            self.run_to_the_end(fight)
            self.assertEqual(fight.phase, "over")
            self.assertIn(fight.result, ("win", "loss", "draw"))

    def test_hp_never_leaves_its_range(self):
        for seed in range(8):
            fight = self.fight(seed)
            self.run_to_the_end(fight)
            for side in (fight.player, fight.foe):
                self.assertGreaterEqual(side["hp"], 0)
                self.assertLessEqual(side["hp"], side["maxHp"])

    def test_a_fainted_creature_does_not_get_another_turn(self):
        # The exchange is queued up front, so the loser must not be able to
        # swing after the line that knocks it out has already been shown.
        for seed in range(20):
            fight = self.fight(seed)
            self.run_to_the_end(fight)
            if fight.result not in ("win", "loss"):
                continue
            self.assertTrue(fight.player["hp"] == 0 or fight.foe["hp"] == 0)
            self.assertFalse(fight.player["hp"] == 0 and fight.foe["hp"] == 0,
                             "both sides cannot faint in the same exchange")

    def test_the_menu_cursor_walks_a_two_by_two_grid(self):
        fight = self.fight()
        self.to_the_move_menu(fight)
        self.assertEqual(fight.cursor, 0)
        self.assertTrue(fight.move_cursor("r"))
        self.assertEqual(fight.cursor, 1)
        self.assertTrue(fight.move_cursor("d"))
        self.assertEqual(fight.cursor, 3)
        self.assertTrue(fight.move_cursor("l"))
        self.assertEqual(fight.cursor, 2)
        self.assertTrue(fight.move_cursor("u"))
        self.assertEqual(fight.cursor, 0)
        # Already there, and a direction that means nothing here.
        self.assertFalse(fight.move_cursor("u"))
        self.assertFalse(fight.move_cursor("x"))

    def test_the_cursor_does_not_move_outside_the_menu(self):
        fight = self.fight()
        self.assertEqual(fight.phase, "intro")
        self.assertFalse(fight.move_cursor("r"))
        self.assertEqual(fight.cursor, 0)

    def test_an_out_of_range_move_is_refused(self):
        fight = self.fight()
        self.to_the_move_menu(fight)
        self.assertFalse(fight.play(9, 0.0))
        self.assertFalse(fight.play(-1, 0.0))
        self.assertEqual(fight.phase, "menu")

    def test_fleeing_ends_it_as_a_draw(self):
        fight = self.fight()
        self.assertTrue(fight.flee(0.0))
        self.assertEqual(fight.phase, "over")
        self.assertEqual(fight.result, "draw")
        # Nothing is left queued that could still change the HP.
        self.assertEqual(fight.queue, [])
        # And it cannot be fled twice.
        self.assertFalse(fight.flee(0.0))

    def test_an_idle_menu_gives_up_rather_than_waiting_forever(self):
        for reach in (self.to_the_action_menu, self.to_the_move_menu):
            fight = self.fight()
            now = reach(fight)
            fight.tick(now + battles.MENU_TIMEOUT + 1.0)
            self.assertEqual(fight.phase, "over")
            self.assertEqual(fight.result, "draw")


    def test_a_rematch_plays_out_the_same_way(self):
        # No explicit generator: both seed themselves off the two addresses,
        # so the same two windows meeting again is the same fight.
        def build():
            return battles.Battle(battles.creature(window("0x10", "foot")),
                                  battles.creature(window("0x20", "firefox")),
                                  0.0)

        first, second = build(), build()
        self.run_to_the_end(first)
        self.run_to_the_end(second)
        self.assertEqual(first.result, second.result)
        self.assertEqual(first.turn, second.turn)
        self.assertEqual(first.player["hp"], second.player["hp"])
        self.assertEqual(first.foe["hp"], second.foe["hp"])


class Running(unittest.TestCase):
    """RUN is free before the first blow and a gamble after it. START, SELECT
    and Escape are the unconditional way out and go through flee()."""

    def fight(self, seed=1):
        return battles.Battle(battles.creature(window("0x10", "foot")),
                              battles.creature(window("0x20", "firefox")),
                              0.0, rng=random.Random(seed))

    def at_the_action_menu(self, fight):
        now = 0.0
        while fight.phase != "action" and now < 30:
            now += 0.1
            fight.tick(now)
        return now

    def test_running_before_the_first_blow_always_works(self):
        for seed in range(40):
            fight = self.fight(seed)
            now = self.at_the_action_menu(fight)
            fight.cursor = battles.ACTIONS.index("RUN")
            self.assertTrue(fight.confirm(now))
            self.assertEqual(fight.phase, "over", seed)
            self.assertEqual(fight.result, "draw", seed)
            self.assertEqual(fight.turn, 0)

    def test_running_after_a_turn_can_fail(self):
        failures = 0
        for seed in range(60):
            fight = self.fight(seed)
            now = self.at_the_action_menu(fight)
            fight.cursor = 0
            fight.confirm(now)              # FIGHT
            fight.play(0, now)              # one exchange
            while fight.phase not in ("action", "over"):
                now += 0.05
                if not fight.advance(now):
                    now += 5.0
                    fight.tick(now)
            if fight.phase != "action":
                continue
            fight.cursor = battles.ACTIONS.index("RUN")
            fight.confirm(now)
            if fight.phase != "over":
                failures += 1
                # A failed run costs the turn: the other window gets a swing.
                self.assertEqual(fight.phase, "resolve")
                self.assertIn("could not get away", fight.message.lower())
        self.assertGreater(failures, 0, "a later run should sometimes fail")

    def test_the_odds_improve_with_speed_and_with_each_attempt(self):
        even = battles.run_chance({"speed": 30}, {"speed": 30}, 0)
        faster = battles.run_chance({"speed": 60}, {"speed": 30}, 0)
        slower = battles.run_chance({"speed": 10}, {"speed": 40}, 0)
        self.assertGreater(faster, even)
        self.assertGreater(even, slower)
        self.assertGreater(battles.run_chance({"speed": 30}, {"speed": 30}, 3), even)

    def test_the_odds_stay_inside_their_bounds(self):
        for mine in (1, 10, 50, 500):
            for theirs in (1, 10, 50, 500):
                for attempts in range(0, 12):
                    chance = battles.run_chance({"speed": mine},
                                                {"speed": theirs}, attempts)
                    self.assertGreaterEqual(chance, battles.RUN_FLOOR)
                    self.assertLessEqual(chance, battles.RUN_CEILING)

    def test_the_hard_escape_hatch_ignores_the_odds(self):
        # Whatever the roll would have said, flee() always ends the battle.
        # This is what START, SELECT, Escape and the timeouts all call.
        for seed in range(20):
            fight = self.fight(seed)
            now = self.at_the_action_menu(fight)
            fight.cursor = 0
            fight.confirm(now)
            fight.play(0, now)
            self.assertTrue(fight.flee(now))
            self.assertEqual(fight.phase, "over")
            self.assertEqual(fight.result, "draw")

    def test_the_hard_timeout_ends_even_a_battle_being_played(self):
        fight = self.fight()
        fight.tick(battles.HARD_TIMEOUT + 1.0)
        self.assertEqual(fight.phase, "over")
        self.assertEqual(fight.result, "draw")

    def test_it_is_not_finished_until_the_closing_line_has_been_read(self):
        fight = self.fight()
        fight.flee(100.0)
        self.assertFalse(fight.finished(100.0))
        self.assertTrue(fight.finished(100.0 + battles.RESULT_DWELL))

    def test_the_deadline_always_moves_forward(self):
        fight = self.fight()
        self.assertIsNotNone(fight.deadline())
        self.assertGreater(fight.deadline(), 0.0)
        fight.flee(5.0)
        self.assertGreater(fight.deadline(), 5.0)

    def test_the_snapshot_carries_what_the_overlay_draws(self):
        fight = self.fight()
        snapshot = fight.snapshot()
        for key in ("active", "phase", "message", "effect", "seq", "cursor",
                    "monitor", "direction", "menu", "action", "actions",
                    "moves", "player", "foe"):
            self.assertIn(key, snapshot)
        self.assertTrue(snapshot["active"])
        self.assertEqual(len(snapshot["moves"]), 4)
        for side in (snapshot["player"], snapshot["foe"]):
            for key in ("address", "name", "type", "level", "hp", "maxHp"):
                self.assertIn(key, side)
        # It has to survive the trip through the state file.
        self.assertEqual(json.loads(json.dumps(snapshot)), snapshot)

    def test_the_sequence_number_rises_on_every_change(self):
        fight = self.fight()
        before = fight.seq
        fight.advance(0.0)
        self.assertGreater(fight.seq, before)



class BattleWiring(unittest.TestCase):
    """What a result is allowed to do to the desktop."""

    def test_the_event_it_listens_for_is_the_gamepad_plugin_s(self):
        self.assertEqual(bd.PAD_COLLISION_EVENT,
                         "dev.cstav.omarchy.plugin.hyprscroll2d-gamepad:collision")

    def test_the_reverse_of_every_direction_is_a_direction(self):
        opposites = {"left": "right", "right": "left", "up": "down", "down": "up"}
        for direction, opposite in opposites.items():
            self.assertEqual(opposites[opposite], direction)

    def test_a_battle_only_ever_asks_for_a_move(self):
        # The one thing end() is allowed to do to the desktop. If this ever
        # becomes a close, a kill or a workspace change, a lost battle starts
        # costing people windows.
        with open(os.path.join(ROOT, "bin", "battles")) as handle:
            source = handle.read()
        start = source.index("    def end(self, now):")
        body = source[start:source.index("    def set_bar", start)]
        for forbidden in ("window.close", "killactive", "movetoworkspace",
                          "window.move", "float", "fullscreen"):
            self.assertNotIn(forbidden, body, forbidden)
        self.assertIn('hl.dsp.layout("move %s")', body)

    def test_everything_it_dispatches_is_a_lua_expression(self):
        # This Hyprland evaluates `hl.dispatch(<what we sent>)` as Lua, so a
        # classic dispatcher string is a syntax error that fails silently.
        with open(os.path.join(ROOT, "bin", "battles")) as handle:
            source = handle.read()
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "self.hypr.dispatch(" not in stripped:
                continue
            self.assertIn("hl.dsp.", stripped, stripped)


class FakeSound:
    def __init__(self, assets=None):
        self.played = []

    def play(self, name, loop=False):
        self.played.append(name)

    def stop(self):
        pass

    def sweep(self):
        pass


class FakePad:
    def __init__(self):
        self.grabbed = False
        self.released = 0
        self.socket = None
        self.held = False

    def grab(self, now):
        self.grabbed = True
        self.held = True
        return True

    def release(self):
        self.released += 1
        self.held = False


class CollisionGate(unittest.TestCase):
    """What turns a reported pad collision into a battle.

    The gamepad plugin has already decided the pad caused this one; these are
    the gates this plugin puts in front of the roll.
    """

    PAYLOAD = "0xaaa,0xbbb,left"

    def daemon(self, chance=1.0, enabled=True):
        # A bare instance: __init__ would go looking for a compositor.
        daemon = bd.Daemon.__new__(bd.Daemon)
        daemon.battle = None
        daemon.chance = chance
        daemon.rng = random.Random(0)
        daemon.quiet_until = 0.0
        daemon.enabled = lambda: enabled
        daemon.started = []
        daemon.start = lambda *args: daemon.started.append(args)
        daemon.last_collision = None
        daemon.last_collision_at = 0.0
        return daemon

    def test_a_reported_collision_starts_one(self):
        daemon = self.daemon()
        daemon.on_collision(self.PAYLOAD, 100.5)
        self.assertEqual(daemon.started,
                         [("0xaaa", "0xbbb", "left", 100.5, "layout")])

    def test_a_keyboard_move_counts_too(self):
        # The trigger is the layout plugin's collision, which fires for any
        # move. Throwing a window with SUPER + SHIFT + H deserves a battle
        # exactly as much as throwing it with the d-pad.
        daemon = self.daemon()
        daemon.on_collision(self.PAYLOAD, 100.5, "layout")
        self.assertEqual(len(daemon.started), 1)
        self.assertEqual(daemon.started[0][4], "layout")

    def test_both_reports_of_one_collision_only_roll_once(self):
        # A d-pad move is announced twice: once by the layout, once by the
        # gamepad plugin. Rolling on each would double the odds.
        daemon = self.daemon()
        daemon.on_collision(self.PAYLOAD, 100.5, "layout")
        daemon.on_collision(self.PAYLOAD, 100.6, "pad")
        self.assertEqual(len(daemon.started), 1)

    def test_the_same_collision_later_is_a_new_one(self):
        daemon = self.daemon()
        daemon.on_collision(self.PAYLOAD, 100.5, "layout")
        daemon.on_collision(self.PAYLOAD, 100.5 + bd.COLLISION_DEDUP + 0.1, "pad")
        self.assertEqual(len(daemon.started), 2)

    def test_a_different_collision_is_not_deduplicated(self):
        daemon = self.daemon()
        daemon.on_collision(self.PAYLOAD, 100.5, "layout")
        daemon.on_collision("0xccc,0xddd,up", 100.6, "layout")
        self.assertEqual(len(daemon.started), 2)

    def test_nothing_happens_while_battles_are_switched_off(self):
        daemon = self.daemon(enabled=False)
        for index in range(50):
            daemon.on_collision("0x%x,0xbbb,left" % index, 100.5)
        self.assertEqual(daemon.started, [])

    def test_nothing_happens_during_a_battle(self):
        daemon = self.daemon()
        daemon.battle = object()
        daemon.on_collision(self.PAYLOAD, 100.5)
        self.assertEqual(daemon.started, [])

    def test_the_cooldown_keeps_battles_from_stacking(self):
        daemon = self.daemon()
        daemon.quiet_until = 200.0
        daemon.on_collision(self.PAYLOAD, 100.5)
        self.assertEqual(daemon.started, [])
        daemon.on_collision("0xccc,0xddd,left", 200.5)
        self.assertEqual(len(daemon.started), 1, "and starts again after it")

    def test_a_losing_roll_starts_nothing(self):
        daemon = self.daemon(chance=0.0)
        for index in range(50):
            daemon.on_collision("0x%x,0xbbb,left" % index, 100.5)
        self.assertEqual(daemon.started, [])

    def test_the_roll_really_is_a_quarter(self):
        daemon = self.daemon(chance=battles.BATTLE_CHANCE)
        daemon.rng = random.Random(2026)
        for index in range(4000):
            # A fresh pair each time, or the de-duplication would swallow all
            # but the first.
            daemon.on_collision("0x%x,0xbbb,left" % index, 100.5)
        self.assertAlmostEqual(len(daemon.started) / 4000.0, 0.25, delta=0.03)

    def test_a_payload_that_makes_no_sense_is_ignored(self):
        daemon = self.daemon()
        for payload in ("", "0xaaa", ",", "   "):
            daemon.on_collision(payload, 100.5)
        self.assertEqual(daemon.started, [])

    def test_a_missing_direction_is_survivable(self):
        daemon = self.daemon()
        daemon.on_collision("0xaaa,0xbbb", 100.5)
        self.assertEqual(daemon.started,
                         [("0xaaa", "0xbbb", "", 100.5, "layout")])

    def test_a_window_is_found_by_address_either_way_round(self):
        clients = [{"address": "0x601AF8"}, {"address": "0xdead"}]
        self.assertIsNotNone(bd.Daemon.window_by_address("0x601af8", clients))
        self.assertIsNotNone(bd.Daemon.window_by_address("0xDEAD", clients))
        self.assertIsNone(bd.Daemon.window_by_address("0xmissing", clients))


class BattleInput(unittest.TestCase):
    """The controller, forwarded from the gamepad plugin one datagram at a
    time. These are the paths a real pad reaches, so they are worth pinning."""

    def daemon(self):
        daemon = bd.Daemon.__new__(bd.Daemon)
        daemon.sound = FakeSound()
        daemon.effects = FakeSound()
        daemon.pad = FakePad()
        daemon.published = None
        daemon.publish = lambda: None
        daemon.battle = battles.Battle(
            battles.creature(window("0x10", "foot")),
            battles.creature(window("0x20", "firefox")),
            0.0, rng=random.Random(1))
        return daemon

    def at_the_action_menu(self, daemon):
        now = 0.0
        while daemon.battle.phase != "action" and now < 30:
            now += 0.1
            daemon.battle.tick(now)
        return now

    @staticmethod
    def press(name):
        return {"event": "button", "name": name, "pressed": True}

    def test_a_press_that_does_something_clicks(self):
        daemon = self.daemon()
        now = self.at_the_action_menu(daemon)
        daemon.on_pad_event(self.press("A"), now)          # FIGHT
        self.assertIn("battle-select.wav", daemon.effects.played)
        self.assertEqual(daemon.battle.phase, "menu")

    def test_a_release_does_nothing(self):
        daemon = self.daemon()
        now = self.at_the_action_menu(daemon)
        daemon.on_pad_event({"event": "button", "name": "A", "pressed": False}, now)
        self.assertEqual(daemon.effects.played, [])
        self.assertEqual(daemon.battle.phase, "action")

    def test_moving_the_cursor_clicks(self):
        daemon = self.daemon()
        self.at_the_action_menu(daemon)
        daemon.on_pad_event({"event": "direction", "direction": "d"}, 0.0)
        self.assertEqual(daemon.effects.played, ["battle-select.wav"])

    def test_a_cursor_move_that_goes_nowhere_is_silent(self):
        daemon = self.daemon()
        self.at_the_action_menu(daemon)
        daemon.on_pad_event({"event": "direction", "direction": "u"}, 0.0)
        daemon.on_pad_event({"event": "direction", "direction": ""}, 0.0)
        self.assertEqual(daemon.effects.played, [])

    def test_a_button_with_no_job_here_is_silent_and_harmless(self):
        daemon = self.daemon()
        now = self.at_the_action_menu(daemon)
        before = daemon.battle.phase
        for name in ("X", "Y", "LB", "RB", "LS", "RS", "Guide"):
            daemon.on_pad_event(self.press(name), now)
        self.assertEqual(daemon.effects.played, [])
        self.assertEqual(daemon.battle.phase, before)

    def test_start_leaves_whatever_is_happening(self):
        daemon = self.daemon()
        now = self.at_the_action_menu(daemon)
        daemon.on_pad_event(self.press("Start"), now)
        self.assertEqual(daemon.battle.phase, "over")
        self.assertEqual(daemon.battle.result, "draw")

    def test_losing_the_pad_ends_the_battle(self):
        # The lease was revoked - the gamepad daemon stopped, the focused
        # window took the pad, or our renewal lapsed. With no controller there
        # is no way to play, so the battle must not sit there.
        daemon = self.daemon()
        now = self.at_the_action_menu(daemon)
        daemon.on_pad_event({"event": "grab", "state": "revoked",
                             "reason": "lease expired"}, now)
        self.assertEqual(daemon.battle.phase, "over")
        self.assertEqual(daemon.battle.result, "draw")

    def test_a_revoke_with_no_battle_running_is_harmless(self):
        daemon = self.daemon()
        daemon.battle = None
        daemon.on_pad_event({"event": "grab", "state": "revoked"}, 0.0)

    def test_an_event_that_makes_no_sense_is_ignored(self):
        daemon = self.daemon()
        now = self.at_the_action_menu(daemon)
        for event in ({}, {"event": "button"}, {"event": "nonsense"},
                      {"event": "direction"}):
            daemon.on_pad_event(event, now)
        self.assertEqual(daemon.battle.phase, "action")

    def test_a_hit_sounds_like_one(self):
        daemon = self.daemon()
        now = self.at_the_action_menu(daemon)
        daemon.on_pad_event(self.press("A"), now)          # FIGHT
        daemon.on_pad_event(self.press("A"), now)          # the first move
        while daemon.battle.effect != "hit-foe" and now < 40:
            now += 0.1
            daemon.battle.tick(now)
            daemon.sound_for(daemon.battle)
        self.assertIn("battle-hit.wav", daemon.effects.played)

    def test_a_win_rings_the_level_up_over_the_fanfare(self):
        daemon = self.daemon()
        daemon.battle.phase = "over"
        daemon.battle.result = "win"
        daemon.sound_for(daemon.battle)
        # The jingle is a one-shot; the fanfare takes the music channel over.
        self.assertEqual(daemon.effects.played, ["battle-levelup.wav"])
        self.assertEqual(daemon.sound.played, ["battle-victory.wav"])

    def test_a_loss_is_only_the_fanfare(self):
        daemon = self.daemon()
        daemon.battle.phase = "over"
        daemon.battle.result = "loss"
        daemon.sound_for(daemon.battle)
        self.assertEqual(daemon.effects.played, [])
        self.assertEqual(daemon.sound.played, ["battle-defeat.wav"])


class Switch(unittest.TestCase):
    """The bar widget's on/off, which is checked before the roll."""

    def daemon(self, enabled=True):
        daemon = bd.Daemon.__new__(bd.Daemon)
        daemon.battle = None
        daemon.enabled = lambda: enabled
        daemon.started = []
        daemon.start = lambda *args: daemon.started.append(args)
        daemon.hypr = None
        return daemon

    def test_forcing_one_respects_the_switch(self):
        # Otherwise `debug` would be the one way to get a battle while the bar
        # widget says none can happen.
        daemon = self.daemon(enabled=False)
        daemon.debug(0.0)
        self.assertEqual(daemon.started, [])

    def test_the_flag_path_is_the_state_directory(self):
        self.assertTrue(bd.DISABLED_FLAG.endswith("hyprscroll2d/battles-disabled"))

    def test_absent_flag_means_on(self):
        # The default has to be "on": a plugin that installed itself switched
        # off would look broken.
        real = bd.DISABLED_FLAG
        try:
            bd.DISABLED_FLAG = "/nonexistent/battles-disabled"
            self.assertTrue(bd.Daemon.enabled())
        finally:
            bd.DISABLED_FLAG = real


class WithoutTheGamepadPlugin(unittest.TestCase):
    """The controller plugin is an optional dependency, and this pins it.

    Battles trigger from the layout plugin's collision, which any move
    produces, and the overlay's own keyboard plays them. The gamepad plugin
    adds a controller and nothing else.
    """

    def test_the_trigger_is_the_layout_s_event_not_the_gamepad_s(self):
        self.assertEqual(bd.LAYOUT_COLLISION_EVENT,
                         "io.github.kirollosatef.hyprscroll2d:collision")

    def test_a_failed_grab_is_not_an_error(self):
        # No gamepad daemon listening: sendto fails, and that is a normal
        # state rather than something to complain about.
        lease = bd.PadLease(path="/nonexistent/gamepad.sock")
        self.assertFalse(lease.grab(0.0))
        self.assertFalse(lease.held)
        lease.release()                 # must be safe either way
        lease.close()

    def test_a_lease_that_was_never_taken_reads_nothing(self):
        lease = bd.PadLease(path="/nonexistent/gamepad.sock")
        self.assertEqual(lease.read(), [])

    def test_the_keyboard_covers_every_battle_control(self):
        # Anything the controller can do, a keyboard has to be able to do, or
        # a battle a keyboard started could not be finished.
        actions = set(bd.Daemon.KEYS)
        self.assertEqual(actions, {"left", "right", "up", "down",
                                   "confirm", "back", "leave"})
        buttons = {value for kind, value in bd.Daemon.KEYS.values()
                   if kind == "button"}
        self.assertEqual(buttons, {"A", "B", "Start"})

    def test_an_unknown_key_does_nothing(self):
        daemon = bd.Daemon.__new__(bd.Daemon)
        daemon.battle = object()
        daemon.on_key("banana", 0.0)    # must not raise


class TheMenuRow(unittest.TestCase):
    """The switch is a file, so the menu row works with no daemon running.

    That matters: `checked` has to answer while the shell is restarting, and
    turning battles off has to work then too. A toggle that needed a live
    daemon would be a toggle that silently did nothing at the worst moment.
    """

    def setUp(self):
        self.ctl = load_ctl()
        self.directory = tempfile.mkdtemp()
        self.ctl.DISABLED_FLAG = os.path.join(self.directory, "battles-disabled")

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_absent_flag_means_on(self):
        self.assertTrue(self.ctl.enabled())

    def test_off_then_on_round_trips(self):
        self.assertTrue(self.ctl.set_enabled(False))
        self.assertFalse(self.ctl.enabled())
        self.assertTrue(self.ctl.set_enabled(True))
        self.assertTrue(self.ctl.enabled())

    def test_turning_it_off_twice_is_not_an_error(self):
        self.ctl.set_enabled(False)
        self.assertTrue(self.ctl.set_enabled(False))
        self.assertFalse(self.ctl.enabled())

    def test_turning_it_on_when_it_already_is_is_not_an_error(self):
        self.assertTrue(self.ctl.set_enabled(True))
        self.assertTrue(self.ctl.enabled())

    def test_nudging_a_daemon_that_is_not_there_is_harmless(self):
        self.ctl.SOCKET_PATH = os.path.join(self.directory, "nothing.sock")
        self.ctl.nudge()

    def test_the_offline_verbs_are_the_ones_that_need_no_daemon(self):
        self.assertEqual(set(self.ctl.OFFLINE),
                         {"enabled", "on", "off", "toggle"})
        for verb in self.ctl.OFFLINE:
            self.assertIn(verb, self.ctl.COMMANDS)

    def test_the_daemon_and_the_cli_agree_on_where_the_flag_lives(self):
        # Two processes, one setting. If these ever drift the menu row and the
        # daemon would disagree about whether battles are on.
        fresh = load_ctl()
        self.assertEqual(fresh.DISABLED_FLAG, bd.DISABLED_FLAG)


class Music(unittest.TestCase):
    def test_the_first_available_player_is_used(self):
        argv = bd.Sound.command("/tmp/x.wav", loop=True)
        if argv is None:
            self.skipTest("no audio player installed")
        self.assertIn("/tmp/x.wav", argv)

    def test_a_missing_file_plays_nothing(self):
        sound = bd.Sound(assets="/nonexistent")
        sound.play("battle-theme.wav", loop=True)
        self.assertIsNone(sound.process)
        sound.stop()          # must be safe with nothing playing

    def test_every_asset_the_daemon_plays_is_in_the_repository(self):
        # A typo in a filename is silence, which is easy to miss by ear.
        with open(os.path.join(ROOT, "bin", "battles")) as handle:
            source = handle.read()
        for name in re.findall(r'"(battle-[a-z]+\.wav)"', source):
            if name == "battle-theme.wav":
                continue    # supplied locally, deliberately not committed
            self.assertTrue(os.path.exists(os.path.join(ROOT, "assets", name)),
                            name)


if __name__ == "__main__":
    unittest.main(verbosity=1)
