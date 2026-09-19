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

import array
import importlib.machinery
import importlib.util
import json
import math
import os
import random
import re
import shutil
import sys
import tempfile
import unittest
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import battle_assets as assets                                # noqa: E402
import battle_rules as battles                                # noqa: E402
import pantry                                                 # noqa: E402
import window_moves as moves                                  # noqa: E402


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
        self.assertEqual(battles.type_of("steam"), "GAME")

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
        self.assertEqual(fight.snapshot()["actions"], ["FIGHT", "ITEM", "RUN"])

    def test_fight_opens_the_move_list_and_b_backs_out_of_it(self):
        fight = self.fight()
        now = self.to_the_move_menu(fight)
        self.assertTrue(fight.menu_open)
        self.assertTrue(fight.back(now))
        self.assertEqual(fight.phase, "action")
        self.assertEqual(fight.cursor, 0)
        # There is nothing to back out of anywhere else.
        self.assertFalse(fight.back(now))

    def test_the_action_cursor_walks_a_two_by_two_grid(self):
        # FIGHT ITEM
        # RUN   -
        fight = self.fight()
        self.to_the_action_menu(fight)
        self.assertEqual(fight.cursor, 0)
        self.assertTrue(fight.move_cursor("r"))
        self.assertEqual(fight.cursor, 1, "ITEM")
        self.assertTrue(fight.move_cursor("l"))
        self.assertEqual(fight.cursor, 0, "FIGHT")
        self.assertTrue(fight.move_cursor("d"))
        self.assertEqual(fight.cursor, 2, "RUN")
        self.assertTrue(fight.move_cursor("u"))
        self.assertEqual(fight.cursor, 0)
        self.assertFalse(fight.move_cursor("u"), "already on the top row")

    def test_the_hole_in_the_action_grid_is_not_reachable(self):
        # Three options in four cells: the fourth is empty, and the cursor
        # must refuse it rather than landing on nothing.
        fight = self.fight()
        self.to_the_action_menu(fight)
        fight.move_cursor("d")
        self.assertEqual(fight.cursor, 2, "RUN")
        self.assertFalse(fight.move_cursor("r"), "no fourth option")
        self.assertEqual(fight.cursor, 2)

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
                          "float", "fullscreen"):
            self.assertNotIn(forbidden, body, forbidden)
        # And the move it does ask for is built by the one module that knows
        # how, so it cannot quietly become something else here.
        self.assertIn("moves.command(self.move_style", body)

    def test_every_command_a_move_can_become_is_a_move(self):
        # The other half of the invariant: end() sends whatever that module
        # hands it, so every style it can hand back has to be a move and
        # nothing else.
        for style, template in moves.STYLES.items():
            for direction in moves.DIRECTIONS:
                command = moves.command(style, direction)
                self.assertTrue(command.startswith("hl.dsp."), command)
                self.assertIn("move", command)
                for forbidden in ("close", "kill", "workspace", "float",
                                  "fullscreen", "resize"):
                    self.assertNotIn(forbidden, command)

    def ending(self, result, direction="left", style="layout"):
        """A bare daemon, ended on one result. Nothing here has a compositor,
        a pad, a speaker or a screen."""
        daemon = bd.Daemon.__new__(bd.Daemon)
        daemon.battle = type("Fight", (), {
            "result": result, "direction": direction,
            "player": {"name": "FOOT"},
        })()
        daemon.quiet_until = 0.0
        daemon.move_style = style
        daemon.pad = FakePad()
        daemon.sound = FakeSound()
        daemon.effects = FakeSound()
        daemon.bar_hidden = False
        daemon.publish = lambda: None
        daemon.dispatched = []
        daemon.hypr = type("Hypr", (), {
            "dispatch": lambda _self, command: daemon.dispatched.append(command),
        })()
        daemon.notices = []
        daemon.notify = lambda summary, body: daemon.notices.append((summary, body))
        daemon.end(100.0)
        return daemon

    def test_a_loss_says_so_on_the_desktop(self):
        # The overlay is gone by the time the window moves back, so without
        # this the only sign of a lost battle is a window somewhere the
        # person did not put it.
        daemon = self.ending("loss")
        self.assertEqual(len(daemon.notices), 1)
        summary, body = daemon.notices[0]
        self.assertIn("FOOT", summary)
        self.assertIn("original position", body)

    def test_nothing_is_said_when_nothing_moved(self):
        # A win, a draw and a flee all leave the swap standing, and a forced
        # battle has no direction to put anything back along. None of them
        # has anything to apologise for.
        for result, direction in (("win", "left"), ("draw", "left"),
                                  ("", "left"), ("loss", "")):
            daemon = self.ending(result, direction)
            self.assertEqual(daemon.notices, [], (result, direction))
            self.assertEqual(daemon.dispatched, [], (result, direction))

    def test_a_loss_is_undone_in_the_language_the_move_was_made_in(self):
        # The one thing a battle does to the desktop has to be the exact
        # reverse of the move that started it, whichever layout that was.
        for style, expected in (
                ("layout", 'hl.dsp.layout("move right")'),
                ("window", 'hl.dsp.window.move({ direction = "r" })')):
            daemon = self.ending("loss", "left", style)
            self.assertEqual(daemon.dispatched, [expected], style)

    def test_the_notifier_is_reaped_like_the_bar_toggles(self):
        # Nothing waits on it, so an unreaped one is a zombie for the life of
        # the daemon - in the plugin that serves zombies as food.
        with open(os.path.join(ROOT, "bin", "battles")) as handle:
            source = handle.read()
        start = source.index("    def notify(self, summary, body):")
        body = source[start:source.index("    # ---", start)]
        self.assertIn("child.poll() is None", body)
        self.assertIn("start_new_session=True", body)

    def test_everything_it_dispatches_is_a_lua_expression(self):
        # This Hyprland evaluates `hl.dispatch(<what we sent>)` as Lua, so a
        # classic dispatcher string is a syntax error that fails silently.
        with open(os.path.join(ROOT, "bin", "battles")) as handle:
            source = handle.read()
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "self.hypr.dispatch(" not in stripped:
                continue
            # Either the expression is right there, or it came from the module
            # whose every template the test above checks.
            self.assertTrue("hl.dsp." in stripped or "moves.command" in stripped
                            or "command)" in stripped, stripped)
        for template in moves.STYLES.values():
            self.assertTrue(template.startswith("hl.dsp."), template)


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
    def __init__(self, grabs=True):
        self.grabbed = False
        self.released = 0
        self.socket = None
        self.held = False
        self.buzzes = []
        self._grabs = grabs

    def grab(self, now):
        self.grabbed = self._grabs
        self.held = self._grabs
        return self._grabs

    def release(self):
        self.released += 1
        self.held = False

    def rumble(self, strong, weak, milliseconds):
        self.buzzes.append((strong, weak, milliseconds))
        return True


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


class FakeCompositor:
    """Two tiled windows side by side, and a compositor that understands
    exactly one of the two move styles - which is the situation on every real
    desktop.

    `pans` is what a scrolling layout does: the camera follows the window that
    moved, so it ends up back at the pixel it started on and every other
    window shifts instead. It is the case that absolute coordinates get wrong.
    """

    SIZE = [800, 600]

    def __init__(self, layout="dwindle", understands="window", pans=False):
        self.layout = layout
        self.understands = understands
        self.pans = pans
        # The active window is the right-hand one, so it has somebody to
        # its left to be moved into.
        self.places = {"0xaaa": [800, 0], "0xbbb": [0, 0]}
        self.dispatched = []

    def query(self, what):
        if what.startswith("getoption"):
            return {"option": "general:layout", "str": self.layout}
        if what == "activewindow":
            return {"address": "0xAAA"}
        if what == "clients":
            return [{"address": address, "mapped": True, "floating": False,
                     "at": list(at), "size": list(self.SIZE),
                     "workspace": {"id": 1}}
                    for address, at in self.places.items()]
        return None

    def dispatch(self, command):
        self.dispatched.append(command)
        if command != moves.command(self.understands, "left"):
            return              # a message this layout does not know: a no-op
        was = list(self.places["0xaaa"])
        self.places["0xaaa"], self.places["0xbbb"] = (
            list(self.places["0xbbb"]), was)
        if self.pans:
            shift = was[0] - self.places["0xaaa"][0]
            for at in self.places.values():
                at[0] += shift


def tiled(address, at, size=(800, 600), workspace=1):
    return {"address": address, "mapped": True, "floating": False,
            "at": list(at), "size": list(size),
            "workspace": {"id": workspace}}


class AnyLayout(unittest.TestCase):
    """Moving a window without a layout plugin to do it.

    Demon Slayer's Hyprscroll2D is a private fork, so most desktops do not
    have it and never will. `battles-ctl move` is the trigger path for those:
    the daemon makes the move itself and works out from the window list who
    was next to whom, which comes to the same thing on dwindle, on master and
    on a scrolling layout.
    """

    ROW = [tiled("0xa", (0, 0)), tiled("0xb", (800, 0)), tiled("0xc", (1600, 0))]

    def daemon(self, compositor):
        daemon = bd.Daemon.__new__(bd.Daemon)
        daemon.hypr = compositor
        daemon.move_style = "layout"
        daemon.collisions = []
        daemon.on_collision = lambda *args: daemon.collisions.append(args)
        return daemon

    def test_a_scrolling_layout_is_asked_in_its_own_language(self):
        self.assertEqual(moves.style_for("hyprscroll2d"), "layout")
        self.assertEqual(moves.command("layout", "left"),
                         'hl.dsp.layout("move left")')

    def test_everything_else_takes_the_dispatcher(self):
        for layout in ("dwindle", "master", ""):
            self.assertEqual(moves.style_for(layout), "window")
        self.assertEqual(moves.command("window", "left"),
                         'hl.dsp.window.move({ direction = "l" })')

    def test_the_lua_prefix_is_not_part_of_the_name(self):
        # Hyprland reports a Lua layout as `lua:hyprscroll2d`; the prefix says
        # where the layout came from, not which layout it is.
        self.assertEqual(moves.layout_name({"str": "lua:hyprscroll2d"}),
                         "hyprscroll2d")
        self.assertEqual(moves.layout_name(None), "")

    def test_a_nonsense_direction_has_no_command(self):
        self.assertEqual(moves.command("window", "sideways"), "")
        self.assertEqual(moves.command("nonsense", "left"), "")

    def test_only_tiled_windows_are_in_a_cell(self):
        places = moves.placement([
            tiled("0xA", (0, 0)),
            dict(tiled("0xB", (10, 10)), floating=True),
            dict(tiled("0xC", (20, 20)), mapped=False),
        ])
        self.assertEqual(list(places), ["0xa"])

    def test_a_neighbour_is_the_nearest_window_in_that_direction(self):
        places = moves.placement(self.ROW)
        self.assertEqual(moves.neighbour("0xb", places, "left"), "0xa")
        self.assertEqual(moves.neighbour("0xb", places, "right"), "0xc")
        self.assertEqual(moves.neighbour("0xa", places, "left"), "")
        self.assertEqual(moves.neighbour("0xa", places, "up"), "")

    def test_a_window_in_another_row_is_not_a_neighbour(self):
        places = moves.placement([tiled("0xa", (0, 0)),
                                  tiled("0xb", (800, 600))])
        self.assertEqual(moves.neighbour("0xa", places, "right"), "")
        self.assertEqual(moves.neighbour("0xa", places, "down"), "")
        self.assertEqual(moves.neighbour("0xb", places, "up"), "")

    def test_a_window_the_focused_one_overlaps_is_still_the_neighbour(self):
        # Demon Slayer's Hyprscroll2D draws the focused window larger than the
        # cell it sits in, so it laps over the window beside it: the facing
        # edges have crossed while the centres have not. Measured off a real
        # desktop - the 1896-wide window is the focused one, and the window in
        # the way starts 162px inside it.
        places = moves.placement([
            tiled("0xa", (1932, 42), size=(1896, 1026)),
            tiled("0xb", (3666, 165), size=(1519, 780)),
            tiled("0xc", (5211, 165), size=(1519, 780)),
        ])
        self.assertEqual(moves.neighbour("0xa", places, "right"), "0xb")

    def test_a_swap_under_an_overlapping_window_is_a_collision(self):
        # The same desktop, either side of `layoutmsg move right`: the focused
        # window stayed on its pixel and the one it displaced went past it to
        # the left, still overlapped.
        before = moves.placement([
            tiled("0xa", (1932, 42), size=(1896, 1026)),
            tiled("0xb", (3666, 165), size=(1519, 780)),
        ])
        after = moves.placement([
            tiled("0xa", (1932, 42), size=(1896, 1026)),
            tiled("0xb", (575, 165), size=(1519, 780)),
        ])
        self.assertEqual(moves.swapped("0xa", "right", before, after), "0xb")

    def test_a_swap_is_the_pair_changing_sides(self):
        before = moves.placement([tiled("0xa", (0, 0)), tiled("0xb", (800, 0))])
        after = moves.placement([tiled("0xa", (800, 0)), tiled("0xb", (0, 0))])
        self.assertEqual(moves.swapped("0xb", "left", before, after), "0xa")

    def test_a_camera_that_follows_the_window_is_still_a_swap(self):
        # What a scrolling layout actually does: the window that moved is at
        # the pixel it started on and everything else shifted instead.
        before = moves.placement([tiled("0xa", (0, 0)), tiled("0xb", (800, 0))])
        after = moves.placement([tiled("0xa", (1600, 0)), tiled("0xb", (800, 0))])
        self.assertEqual(moves.swapped("0xb", "left", before, after), "0xa")

    def test_stepping_into_an_empty_cell_is_not_a_collision(self):
        before = moves.placement([tiled("0xa", (800, 0))])
        after = moves.placement([tiled("0xa", (0, 0))])
        self.assertEqual(moves.swapped("0xa", "left", before, after), "")

    def test_landing_short_of_a_far_window_is_not_a_collision(self):
        # A gap, then a window: it was in the direction of travel, but it is
        # still on the same side afterwards, so nothing was displaced.
        before = moves.placement([tiled("0xa", (1600, 0)), tiled("0xb", (0, 0))])
        after = moves.placement([tiled("0xa", (800, 0)), tiled("0xb", (0, 0))])
        self.assertEqual(moves.swapped("0xa", "left", before, after), "")

    def test_a_window_that_did_not_move_collided_with_nothing(self):
        places = moves.placement(self.ROW)
        self.assertEqual(moves.swapped("0xb", "left", places, places), "")

    def test_a_swap_on_dwindle_rolls_for_a_battle(self):
        compositor = FakeCompositor("dwindle", "window")
        daemon = self.daemon(compositor)
        self.assertTrue(daemon.move("left", 100.0))
        self.assertEqual(daemon.collisions,
                         [("0xaaa,0xbbb,left", 100.0, "move")])
        self.assertEqual(daemon.move_style, "window")

    def test_a_swap_on_a_scrolling_layout_rolls_the_same_way(self):
        compositor = FakeCompositor("lua:hyprscroll2d", "layout", pans=True)
        daemon = self.daemon(compositor)
        self.assertTrue(daemon.move("left", 100.0))
        self.assertEqual(daemon.collisions,
                         [("0xaaa,0xbbb,left", 100.0, "move")])
        self.assertEqual(daemon.move_style, "layout")
        self.assertEqual(compositor.dispatched, ['hl.dsp.layout("move left")'])

    def test_the_other_style_gets_a_turn_when_the_first_moved_nothing(self):
        # A layout can differ per workspace, so the name is a hint and not an
        # answer. A message a layout does not understand moves nothing, and
        # nothing moving is what the fallback is looking for.
        compositor = FakeCompositor("lua:hyprscroll2d", "window")
        daemon = self.daemon(compositor)
        self.assertTrue(daemon.move("left", 100.0))
        self.assertEqual(compositor.dispatched,
                         ['hl.dsp.layout("move left")',
                          'hl.dsp.window.move({ direction = "l" })'])
        self.assertEqual(daemon.move_style, "window")
        self.assertEqual(len(daemon.collisions), 1)

    def test_only_one_of_the_two_styles_can_ever_land(self):
        # Both understood would be a window moved twice. The loop stops on the
        # first one that changed anything.
        compositor = FakeCompositor("lua:hyprscroll2d", "layout")
        daemon = self.daemon(compositor)
        daemon.move("left", 100.0)
        self.assertEqual(len(compositor.dispatched), 1)

    def test_a_move_that_hits_nobody_is_still_a_move(self):
        compositor = FakeCompositor("dwindle", "window")
        del compositor.places["0xbbb"]

        def dispatch(command):
            compositor.dispatched.append(command)
            compositor.places["0xaaa"] = [0, 0]

        compositor.dispatch = dispatch
        daemon = self.daemon(compositor)
        self.assertTrue(daemon.move("left", 100.0))
        self.assertEqual(daemon.collisions, [])

    def test_a_direction_that_is_not_one_moves_nothing(self):
        compositor = FakeCompositor()
        daemon = self.daemon(compositor)
        self.assertFalse(daemon.move("sideways", 100.0))
        self.assertEqual(compositor.dispatched, [])


class WithoutTheLayoutPlugin(unittest.TestCase):
    """Demon Slayer's Hyprscroll2D is a private fork, so it is a shortcut and
    never a requirement."""

    def test_the_move_verb_is_the_trigger_everybody_has(self):
        ctl = load_ctl()
        self.assertIn("move", ctl.COMMANDS)

    def test_a_move_still_happens_with_no_daemon_running(self):
        # A move key that died with the shell would be far more annoying than
        # a missed battle, so the CLI makes the move itself as a fallback.
        ctl = load_ctl()
        self.assertNotIn("move", ctl.OFFLINE)
        with open(os.path.join(ROOT, "bin", "battles-ctl")) as handle:
            source = handle.read()
        self.assertIn('if argument == "move":\n            return move(', source)

    def test_the_cli_and_the_daemon_move_windows_the_same_way(self):
        ctl = load_ctl()
        self.assertIs(ctl.moves, moves)


class EncounterRumble(unittest.TestCase):
    """A battle opening should be felt, not just seen. The motors live in the
    gamepad plugin, so this is an ask over its socket rather than a write."""

    def daemon(self, pad):
        daemon = bd.Daemon.__new__(bd.Daemon)
        daemon.sound = FakeSound()
        daemon.effects = FakeSound()
        daemon.pad = pad
        daemon.battle = None
        daemon.source = None
        daemon.input = "keys"
        daemon.published = None
        daemon.publish = lambda: None
        daemon.pantry = None
        daemon.bar_hidden = False
        daemon.set_bar = lambda visible: None
        daemon.monitor_name = lambda client: "DP-4"
        daemon.hypr = type("Q", (), {"query": staticmethod(
            lambda what: [window("0x10", "foot"), window("0x20", "firefox")])})()
        return daemon

    def test_a_battle_starting_asks_for_a_second_at_full(self):
        pad = FakePad()
        daemon = self.daemon(pad)
        daemon.start("0x10", "0x20", "left", 0.0, source="pad")
        self.assertIsNotNone(daemon.battle)
        self.assertEqual(pad.buzzes, [(1.0, 1.0, bd.ENCOUNTER_RUMBLE_MS)])

    def test_it_is_asked_for_even_when_the_lease_is_refused(self):
        # A keyboard battle, or a pad lent elsewhere: the buzz is harmless and
        # the controller may well still be in reach.
        pad = FakePad(grabs=False)
        daemon = self.daemon(pad)
        daemon.start("0x10", "0x20", "left", 0.0, source="keyboard")
        self.assertEqual(pad.buzzes, [(1.0, 1.0, bd.ENCOUNTER_RUMBLE_MS)])

    def test_nothing_buzzes_when_the_battle_cannot_start(self):
        pad = FakePad()
        daemon = self.daemon(pad)
        daemon.start("0x10", "0xmissing", "left", 0.0, source="pad")
        self.assertIsNone(daemon.battle)
        self.assertEqual(pad.buzzes, [])


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
        daemon.input = "keys"
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

    def test_start_again_over_the_closing_line_ends_it_now(self):
        # The battle is already over and only its last line is on screen.
        # Pressing the way out a second time should not be ignored.
        daemon = self.daemon()
        ended = []
        daemon.end = lambda now: ended.append(now)
        now = self.at_the_action_menu(daemon)
        daemon.on_pad_event(self.press("Start"), now)
        self.assertEqual(ended, [])
        daemon.on_pad_event(self.press("Start"), now + 0.5)
        self.assertEqual(ended, [now + 0.5])

    def test_escape_again_over_the_closing_line_ends_it_now(self):
        # The overlay's Escape, which goes through the socket rather than the
        # pad. Same rule: the second one does not wait out the dwell.
        daemon = self.daemon()
        ended = []
        daemon.end = lambda now: ended.append(now)
        self.at_the_action_menu(daemon)
        daemon.handle_command("cancel")
        self.assertEqual(daemon.battle.phase, "over")
        self.assertEqual(ended, [])
        daemon.handle_command("cancel")
        self.assertEqual(len(ended), 1)

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

    def test_the_controls_are_named_for_whatever_is_in_hand(self):
        # The overlay draws one set of hints, not both, so the daemon has to
        # say which. A battle can change hands mid-fight either way: the pad
        # is grabbed whoever started the fight, and the keyboard is never
        # taken away.
        daemon = self.daemon()
        now = self.at_the_action_menu(daemon)
        daemon.on_key("down", now)
        self.assertEqual(daemon.input, "keys")
        daemon.on_pad_event({"event": "direction", "direction": "u"}, now)
        self.assertEqual(daemon.input, "pad")
        daemon.on_key("up", now)
        self.assertEqual(daemon.input, "keys")

    def test_the_overlay_is_told_which_one(self):
        daemon = self.daemon()
        daemon.enabled = lambda: True
        daemon.input = "pad"
        self.assertEqual(daemon.state()["input"], "pad")

    def test_a_grab_being_revoked_is_not_somebody_playing(self):
        # It is the pad going away, so it must not relabel the hints as the
        # pad's on the way out.
        daemon = self.daemon()
        daemon.on_pad_event({"event": "grab", "state": "revoked"}, 0.0)
        self.assertEqual(daemon.input, "keys")

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
                         "me.schafman.omarchy.plugin.hyprscroll2d:collision")

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
        # `assets` is here too: which file a sound comes from is a setting and
        # a pair of directories, so it can be read and changed with the shell
        # down, exactly like the on/off flag.
        self.assertEqual(set(self.ctl.OFFLINE),
                         {"enabled", "on", "off", "toggle", "assets"})
        for verb in self.ctl.OFFLINE:
            self.assertIn(verb, self.ctl.COMMANDS)

    def test_the_daemon_and_the_cli_agree_on_where_the_flag_lives(self):
        # Two processes, one setting. If these ever drift the menu row and the
        # daemon would disagree about whether battles are on.
        fresh = load_ctl()
        self.assertEqual(fresh.DISABLED_FLAG, bd.DISABLED_FLAG)


# --------------------------------------------------------------------- food
#
# The hard constraint is that the pantry is read-only: it reads counters and
# sizes and changes nothing. These tests run it against fixture files, so the
# readings are known, and against the real machine, so the shape is right.

class Readings(unittest.TestCase):
    """Reading the machine. Fixtures, so the numbers are known."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def write(self, name, text):
        path = os.path.join(self.directory, name)
        with open(path, "w") as handle:
            handle.write(text)
        return path

    def test_meminfo_is_parsed_as_kilobytes(self):
        path = self.write("meminfo", "MemTotal:  32625496 kB\n"
                                     "MemAvailable: 15524760 kB\n"
                                     "Cached:    13412676 kB\n")
        values = pantry.read_meminfo(path)
        self.assertEqual(values["MemAvailable"], 15524760.0)
        self.assertEqual(values["Cached"], 13412676.0)

    def test_a_meminfo_that_is_not_there_is_empty_not_fatal(self):
        self.assertEqual(pantry.read_meminfo("/nonexistent/meminfo"), {})

    def test_a_line_that_makes_no_sense_is_skipped(self):
        path = self.write("meminfo", "Good: 12 kB\nBroken: not-a-number kB\n"
                                     "NoColonHere\n")
        values = pantry.read_meminfo(path)
        self.assertEqual(values.get("Good"), 12.0)
        self.assertNotIn("Broken", values)

    def test_entropy_is_a_number(self):
        self.assertEqual(pantry.read_entropy(self.write("entropy", "256\n")), 256.0)
        self.assertEqual(pantry.read_entropy("/nonexistent"), 0.0)
        self.assertEqual(pantry.read_entropy(self.write("junk", "hello")), 0.0)

    def test_zombies_are_counted_from_the_state_field(self):
        # The comm field is parenthesised and may contain spaces and brackets,
        # so the state is whatever follows the *last* close parenthesis.
        for pid, comm, state in (("1", "systemd", "S"), ("2", "a (odd) name", "Z"),
                                 ("3", "kworker", "Z"), ("4", "bash", "R")):
            os.makedirs(os.path.join(self.directory, pid))
            self.write(os.path.join(pid, "stat"),
                       "%s (%s) %s 1 1 0 0\n" % (pid, comm, state))
        os.makedirs(os.path.join(self.directory, "not-a-pid"))
        self.assertEqual(pantry.count_zombies(self.directory), 2)

    def test_zombie_counting_survives_a_process_that_vanishes(self):
        os.makedirs(os.path.join(self.directory, "999"))   # no stat file
        self.assertEqual(pantry.count_zombies(self.directory), 0)

    def test_used_bytes_comes_from_statvfs(self):
        self.assertGreater(pantry.used_bytes("/"), 0)
        self.assertEqual(pantry.used_bytes("/nonexistent"), 0.0)

    def test_the_real_machine_fills_every_shelf_shape(self):
        # Not the values - those move - but that each shelf reads a number.
        larder = pantry.Pantry(ledger=pantry.Ledger())
        for shelf in larder.stock():
            self.assertIsInstance(shelf["available"], float)
            self.assertGreaterEqual(shelf["available"], 0.0)
            self.assertGreaterEqual(shelf["servings"], 0)
            self.assertTrue(shelf["name"])
            self.assertTrue(shelf["note"])

    def test_nothing_in_the_pantry_writes_outside_its_ledger(self):
        # The constraint this whole feature rests on. If a future shelf
        # reaches for a write, an unlink or a signal, this fails.
        with open(os.path.join(ROOT, "lib", "pantry.py")) as handle:
            source = handle.read()
        for forbidden in ("os.unlink", "os.remove", "os.kill", "shutil.rmtree",
                          "subprocess", "sudo", "drop_caches", "truncate"):
            self.assertNotIn(forbidden, source, forbidden)
        # One write, and it is the ledger's own save().
        self.assertEqual(source.count('open(temporary, "w")'), 1)


class TheLedger(unittest.TestCase):
    """What stops the same 512 MiB feeding a creature forever."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.path = os.path.join(self.directory, "pantry.json")

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_an_eaten_portion_is_outstanding_straight_away(self):
        ledger = pantry.Ledger(self.path)
        ledger.take("staple", 512.0, 1000.0)
        self.assertAlmostEqual(ledger.outstanding("staple", 1000.0), 512.0)

    def test_it_grows_back_smoothly(self):
        ledger = pantry.Ledger(self.path)
        ledger.take("staple", 512.0, 1000.0)
        half = 1000.0 + pantry.REGEN_SECONDS / 2
        self.assertAlmostEqual(ledger.outstanding("staple", half), 256.0, places=3)

    def test_it_is_fully_back_after_the_regen_window(self):
        ledger = pantry.Ledger(self.path)
        ledger.take("staple", 512.0, 1000.0)
        later = 1000.0 + pantry.REGEN_SECONDS + 1
        self.assertEqual(ledger.outstanding("staple", later), 0.0)

    def test_shelves_do_not_borrow_from_each_other(self):
        ledger = pantry.Ledger(self.path)
        ledger.take("staple", 512.0, 1000.0)
        self.assertEqual(ledger.outstanding("candy", 1000.0), 0.0)

    def test_a_clock_that_goes_backwards_does_not_refund(self):
        ledger = pantry.Ledger(self.path)
        ledger.take("staple", 512.0, 1000.0)
        self.assertAlmostEqual(ledger.outstanding("staple", 900.0), 512.0)

    def test_it_survives_a_restart(self):
        first = pantry.Ledger(self.path)
        first.take("staple", 512.0, 1000.0)
        second = pantry.Ledger(self.path)
        self.assertAlmostEqual(second.outstanding("staple", 1000.0), 512.0)

    def test_a_corrupt_ledger_is_ignored_rather_than_fatal(self):
        with open(self.path, "w") as handle:
            handle.write("{not json at all")
        ledger = pantry.Ledger(self.path)
        self.assertEqual(ledger.entries, [])

    def test_entries_that_make_no_sense_are_dropped(self):
        with open(self.path, "w") as handle:
            json.dump({"entries": [{"key": "staple", "amount": 1, "at": 2},
                                   {"key": "broken"},
                                   "not a dict",
                                   {"key": "x", "amount": "nope", "at": 0}]},
                      handle)
        ledger = pantry.Ledger(self.path)
        self.assertEqual(len(ledger.entries), 1)

    def test_pruning_forgets_what_has_grown_back(self):
        ledger = pantry.Ledger(self.path)
        ledger.take("staple", 512.0, 1000.0)
        ledger.prune(1000.0 + pantry.REGEN_SECONDS + 1)
        self.assertEqual(ledger.entries, [])

    def test_a_ledger_with_no_path_still_works_in_memory(self):
        ledger = pantry.Ledger()
        ledger.take("staple", 512.0, 1000.0)
        self.assertAlmostEqual(ledger.outstanding("staple", 1000.0), 512.0)


class ThePantry(unittest.TestCase):
    """Live readings minus the ledger, against fixed fixtures."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        meminfo = os.path.join(self.directory, "meminfo")
        with open(meminfo, "w") as handle:
            handle.write("MemAvailable: 2097152 kB\n"     # 2048 MiB
                         "Cached:       4194304 kB\n"     # 4096 MiB
                         "SwapTotal:    2097152 kB\n"
                         "SwapFree:     1048576 kB\n")    # 1024 MiB in use
        entropy = os.path.join(self.directory, "entropy")
        with open(entropy, "w") as handle:
            handle.write("256\n")
        self.roots = {"meminfo": meminfo, "entropy": entropy,
                      "proc": self.directory, "tmp": "/"}
        self.clock = [1000.0]
        self.larder = pantry.Pantry(ledger=pantry.Ledger(),
                                    roots=self.roots,
                                    clock=lambda: self.clock[0])

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def shelf(self, key):
        return next(s for s in self.larder.stock() if s["key"] == key)

    def test_the_staple_reads_memavailable(self):
        self.assertAlmostEqual(self.shelf("staple")["available"], 2048.0)
        self.assertEqual(self.shelf("staple")["servings"], 4)   # 512 MiB each

    def test_swap_in_use_is_total_minus_free(self):
        self.assertAlmostEqual(self.shelf("junk")["available"], 1024.0)

    def test_eating_takes_it_off_the_shelf(self):
        self.assertEqual(self.shelf("staple")["servings"], 4)
        serving = self.larder.take("staple")
        self.assertIsNotNone(serving)
        self.assertAlmostEqual(self.shelf("staple")["available"], 1536.0)
        self.assertEqual(self.shelf("staple")["servings"], 3)

    def test_the_machine_reading_itself_never_changes(self):
        # The whole point: eating moves the ledger, not the machine.
        before = pantry.read_meminfo(self.roots["meminfo"])
        for _ in range(4):
            self.larder.take("staple")
        after = pantry.read_meminfo(self.roots["meminfo"])
        self.assertEqual(before, after)

    def test_a_bare_shelf_refuses(self):
        for _ in range(4):
            self.assertIsNotNone(self.larder.take("staple"))
        self.assertIsNone(self.larder.take("staple"), "nothing left")

    def test_it_comes_back(self):
        for _ in range(4):
            self.larder.take("staple")
        self.assertIsNone(self.larder.take("staple"))
        self.clock[0] += pantry.REGEN_SECONDS + 1
        self.assertIsNotNone(self.larder.take("staple"), "grown back")

    def test_you_cannot_eat_what_the_machine_does_not_have(self):
        with open(self.roots["meminfo"], "w") as handle:
            handle.write("MemAvailable: 1024 kB\n")     # 1 MiB, not a portion
        self.assertIsNone(self.larder.take("staple"))
        self.assertEqual(self.shelf("staple")["servings"], 0)

    def test_an_unknown_shelf_is_not_food(self):
        self.assertIsNone(self.larder.take("sandwich"))

    def test_the_ledger_ignores_the_callers_monotonic_clock(self):
        # The battle hands the pantry a monotonic `now`, which counts from an
        # arbitrary zero and restarts at boot. The ledger is on disk and keeps
        # wall-clock time, so it must use its own clock: writing a monotonic
        # number into it would make every entry look like it was eaten in the
        # future after a reboot, and nothing would ever grow back.
        self.larder.take("staple", 5.0)          # a battle's monotonic clock
        entry = self.larder.ledger.entries[-1]
        self.assertEqual(entry["at"], 1000.0, "the pantry's own clock, not 5.0")

        self.clock[0] += pantry.REGEN_SECONDS + 1
        self.assertEqual(self.larder.ledger.outstanding("staple", self.clock[0]),
                         0.0, "and it still grows back")

    def test_stock_also_ignores_the_callers_clock(self):
        for _ in range(4):
            self.larder.take("staple")
        self.assertEqual(self.shelf("staple")["servings"], 0)
        self.clock[0] += pantry.REGEN_SECONDS + 1
        # Passing a stale monotonic number must not resurrect or freeze it.
        shelves = self.larder.stock(0.0)
        staple = next(s for s in shelves if s["key"] == "staple")
        self.assertEqual(staple["servings"], 4)

    def test_a_reading_that_throws_is_an_empty_shelf(self):
        broken = dict(pantry.SHELVES[0])
        broken["reading"] = lambda roots: 1 / 0
        self.assertEqual(self.larder.available(broken), 0.0)

    def test_every_shelf_is_listed_even_when_bare(self):
        for _ in range(4):
            self.larder.take("staple")
        names = [shelf["key"] for shelf in self.larder.stock()]
        self.assertEqual(len(names), len(pantry.SHELVES))
        self.assertIn("staple", names)

    def test_describe_is_readable(self):
        self.assertEqual(pantry.describe(512, "MiB"), "512 MiB")
        self.assertEqual(pantry.describe(2048, "MiB"), "2.0 GiB")
        self.assertEqual(pantry.describe(256, "bits"), "256 bits")
        self.assertEqual(pantry.describe(6, ""), "6")


class Eating(unittest.TestCase):
    """The ITEM option, in the turn loop."""

    class FakeLarder:
        def __init__(self, servings=2):
            self.shelf = {
                "key": "staple", "name": "FREE RAM", "note": "n", "unit": "MiB",
                "kind": "plain", "portion": 512.0, "available": 512.0 * servings,
                "servings": servings, "heal": 0.30, "nourish": 34,
                "penalty": None, "boon": None,
            }
            self.taken = []

        def stock(self, now=None):
            return [dict(self.shelf)]

        def take(self, key, now=None):
            if key != self.shelf["key"] or self.shelf["servings"] <= 0:
                return None
            self.shelf["servings"] -= 1
            self.taken.append(key)
            return dict(self.shelf)

    def fight(self, larder=None, seed=1):
        return battles.Battle(battles.creature(window("0x10", "foot")),
                              battles.creature(window("0x20", "firefox")),
                              0.0, rng=random.Random(seed),
                              larder=larder or self.FakeLarder())

    def at_the_action_menu(self, fight):
        now = 0.0
        while fight.phase != "action" and now < 30:
            now += 0.1
            fight.tick(now)
        return now

    def open_pantry(self, fight):
        now = self.at_the_action_menu(fight)
        fight.cursor = battles.ACTIONS.index("ITEM")
        self.assertTrue(fight.confirm(now))
        self.assertEqual(fight.phase, "item")
        return now

    def test_item_sits_between_fight_and_run(self):
        self.assertEqual(battles.ACTIONS, ("FIGHT", "ITEM", "RUN"))

    def test_opening_the_pantry_reads_the_shelves(self):
        fight = self.fight()
        self.open_pantry(fight)
        self.assertEqual(len(fight.shelves), 1)
        self.assertEqual(fight.snapshot()["shelves"][0]["name"], "FREE RAM")
        self.assertTrue(fight.snapshot()["item"])

    def test_the_pantry_cursor_walks_a_two_column_grid(self):
        # 0 1
        # 2 3
        # 4 -
        larder = self.FakeLarder()
        larder.stock = lambda now=None: [dict(larder.shelf) for _ in range(5)]
        fight = self.fight(larder)
        self.open_pantry(fight)
        self.assertFalse(fight.move_cursor("u"), "already on the top row")
        self.assertFalse(fight.move_cursor("l"), "already in the left column")
        self.assertTrue(fight.move_cursor("r"))
        self.assertEqual(fight.cursor, 1)
        self.assertTrue(fight.move_cursor("d"))
        self.assertEqual(fight.cursor, 3)
        self.assertTrue(fight.move_cursor("l"))
        self.assertEqual(fight.cursor, 2)
        self.assertTrue(fight.move_cursor("d"))
        self.assertEqual(fight.cursor, 4)
        self.assertFalse(fight.move_cursor("r"), "the last row has a hole")
        self.assertFalse(fight.move_cursor("d"), "and nothing below it")

    def test_b_backs_out_of_the_pantry(self):
        fight = self.fight()
        now = self.open_pantry(fight)
        self.assertTrue(fight.back(now))
        self.assertEqual(fight.phase, "action")

    def test_eating_heals_and_costs_the_turn(self):
        fight = self.fight()
        now = self.open_pantry(fight)
        fight.player["hp"] = 10
        self.assertTrue(fight.eat(0, now))
        self.assertEqual(fight.phase, "resolve")
        self.assertEqual(fight.turn, 1, "eating is a turn")
        # Play the queue out; the heal lands, then the foe swings.
        for _ in range(20):
            if not fight.advance(now):
                break
            now += 0.1
        self.assertGreater(fight.player["hp"], 10)

    def test_healing_cannot_go_past_full(self):
        # Eating on full HP restores nothing - and still costs the turn, so
        # the foe's free swing is why the HP ends up lower, not higher.
        fight = self.fight()
        now = self.open_pantry(fight)
        fight.player["hp"] = fight.player["maxHp"]
        self.assertEqual(fight._heal_for({"heal": 0.30, "kind": "plain"}), 0)
        fight.eat(0, now)
        # Collect the narration as it plays, rather than after the queue has
        # drained and the menu prompt has replaced it.
        said = [fight.message]
        for _ in range(20):
            if not fight.advance(now):
                break
            said.append(fight.message)
            now += 0.1
        self.assertLessEqual(fight.player["hp"], fight.player["maxHp"])
        self.assertTrue(any("nothing happened" in line for line in said), said)

    def test_a_bare_shelf_costs_nothing(self):
        fight = self.fight(self.FakeLarder(servings=0))
        now = self.open_pantry(fight)
        self.assertTrue(fight.eat(0, now), "it says so")
        self.assertEqual(fight.phase, "item", "and stays in the menu")
        self.assertEqual(fight.turn, 0, "no turn was spent")
        self.assertIn("no free ram", fight.message.lower())

    def test_a_shelf_that_empties_between_looking_and_choosing(self):
        larder = self.FakeLarder(servings=1)
        fight = self.fight(larder)
        now = self.open_pantry(fight)
        larder.shelf["servings"] = 0            # something else ate it
        self.assertTrue(fight.eat(0, now))
        self.assertEqual(fight.turn, 0)
        self.assertIn("went before", fight.message.lower())

    def test_an_out_of_range_shelf_is_refused(self):
        fight = self.fight()
        now = self.open_pantry(fight)
        self.assertFalse(fight.eat(9, now))
        self.assertFalse(fight.eat(-1, now))

    def test_a_larder_that_throws_is_an_empty_pantry(self):
        class Broken:
            def stock(self, now=None):
                raise RuntimeError("no /proc today")

            def take(self, key, now=None):
                raise RuntimeError("still no")

        fight = self.fight(Broken())
        now = self.at_the_action_menu(fight)
        fight.cursor = battles.ACTIONS.index("ITEM")
        fight.confirm(now)
        self.assertEqual(fight.phase, "item")
        self.assertEqual(fight.shelves, [])

    def test_with_no_larder_at_all_the_pantry_is_bare(self):
        fight = battles.Battle(battles.creature(window("0x10", "foot")),
                               battles.creature(window("0x20", "firefox")), 0.0)
        now = self.at_the_action_menu(fight)
        fight.cursor = battles.ACTIONS.index("ITEM")
        fight.confirm(now)
        self.assertEqual(fight.shelves, [])

    def test_enough_food_levels_a_creature_up(self):
        larder = self.FakeLarder(servings=20)
        fight = self.fight(larder)
        level = fight.player["level"]
        attack = fight.player["attack"]
        now = 0.0
        for _ in range(4):
            while fight.phase not in ("action", "over"):
                now += 0.1
                if not fight.advance(now):
                    now += 5.0
                    fight.tick(now)
            if fight.phase == "over":
                break
            fight.cursor = battles.ACTIONS.index("ITEM")
            fight.confirm(now)
            fight.player["hp"] = 5
            fight.eat(0, now)
        self.assertGreater(fight.player["level"], level)
        self.assertGreater(fight.player["attack"], attack)

    def test_a_penalty_lowers_a_stat_but_never_below_one(self):
        fight = self.fight()
        fight.player["speed"] = 1
        fight._adjust({"stat": "speed", "fraction": 0.9}, -1)()
        self.assertGreaterEqual(fight.player["speed"], 1)

    def test_candy_is_a_gamble_and_the_rest_are_not(self):
        fight = self.fight()
        fight.player["hp"] = 1
        plain = {"heal": 0.30, "kind": "plain"}
        self.assertEqual({fight._heal_for(plain) for _ in range(20)},
                         {int(fight.player["maxHp"] * 0.30)})
        candy = {"heal": 0.30, "kind": "candy"}
        self.assertGreater(len({fight._heal_for(candy) for _ in range(40)}), 1)

    def test_the_snapshot_carries_the_pantry(self):
        fight = self.fight()
        self.open_pantry(fight)
        snapshot = fight.snapshot()
        for key in ("item", "shelves", "fed", "nourishPerLevel"):
            self.assertIn(key, snapshot)
        self.assertEqual(json.loads(json.dumps(snapshot)), snapshot)


class Music(unittest.TestCase):
    def test_the_first_available_player_is_used(self):
        argv = bd.Sound.command("/tmp/x.wav", loop=True)
        if argv is None:
            self.skipTest("no audio player installed")
        self.assertIn("/tmp/x.wav", argv)

    def test_a_missing_file_plays_nothing(self):
        sound = bd.Sound(assets="/nonexistent", custom="/nonexistent-too")
        sound.play("battle-theme.wav", loop=True)
        self.assertIsNone(sound.process)
        sound.stop()          # must be safe with nothing playing

    def test_every_asset_the_daemon_plays_is_in_the_repository(self):
        # A typo in a filename is silence, which is easy to miss by ear.
        with open(os.path.join(ROOT, "bin", "battles")) as handle:
            source = handle.read()
        for name in re.findall(r'"(battle-[a-z]+\.wav)"', source):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "assets", name)),
                            name)

    def test_the_daemon_only_asks_for_names_the_generator_makes(self):
        # Three hand-written lists in three files. If they drift, a sound
        # either plays from nowhere or goes unaccounted for in `assets`.
        with open(os.path.join(ROOT, "bin", "battles")) as handle:
            played = set(re.findall(r'"(battle-[a-z]+\.wav)"', handle.read()))
        with open(os.path.join(ROOT, "bin", "make-battle-audio")) as handle:
            made = set(re.findall(r'"(battle-[a-z]+\.wav)"', handle.read()))
        self.assertTrue(played)
        self.assertEqual(played - made, set())
        self.assertEqual(played - set(assets.SOUNDS), set())


class Assets(unittest.TestCase):
    """Which of the two directories a sound comes out of.

    The resolution order is the whole of the generated-versus-custom feature,
    so it runs against directories made here rather than against whatever
    happens to be in this machine's config.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="battle-assets-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.generated = os.path.join(self.root, "generated")
        self.custom = os.path.join(self.root, "custom")
        os.makedirs(self.generated)
        os.makedirs(self.custom)
        for name in assets.SOUNDS:
            self.put(self.generated, name)

    def put(self, directory, name, body=b"RIFF"):
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(body)
        return path

    def resolve(self, name, which):
        return assets.resolve(name, which, generated=self.generated,
                              custom=self.custom, environ={})

    def test_auto_takes_a_custom_file_when_there_is_one(self):
        mine = self.put(self.custom, "battle-theme.wav")
        self.assertEqual(self.resolve("battle-theme.wav", "auto"), mine)

    def test_auto_falls_back_per_file_and_not_per_set(self):
        # Replacing only the theme has to leave the rest alone: it is the
        # state almost everyone who replaces anything ends up in.
        self.put(self.custom, "battle-theme.wav")
        rows = dict((name, source) for name, _, source in assets.resolution(
            "auto", self.generated, self.custom, environ={}))
        self.assertEqual(rows["battle-theme.wav"], "custom")
        for name in assets.SOUNDS:
            if name != "battle-theme.wav":
                self.assertEqual(rows[name], "generated", name)

    def test_generated_ignores_a_custom_file_that_is_sitting_there(self):
        # The A/B position: it has to work without moving anybody's files.
        self.put(self.custom, "battle-theme.wav")
        self.assertEqual(self.resolve("battle-theme.wav", "generated"),
                         os.path.join(self.generated, "battle-theme.wav"))

    def test_custom_is_silent_rather_than_falling_back(self):
        # Otherwise `custom` and `auto` would be the same mode, and there
        # would be no way to hear your own set and only your own set.
        self.put(self.custom, "battle-theme.wav")
        self.assertEqual(self.resolve("battle-theme.wav", "custom"),
                         os.path.join(self.custom, "battle-theme.wav"))
        self.assertIsNone(self.resolve("battle-hit.wav", "custom"))

    def test_a_name_in_neither_directory_resolves_to_nothing(self):
        self.assertIsNone(self.resolve("battle-nonesuch.wav", "auto"))

    def test_the_environment_overrides_the_saved_mode_for_one_run(self):
        path = os.path.join(self.root, "battles-assets")
        with open(path, "w") as handle:
            handle.write("custom\n")
        self.assertEqual(assets.mode({}, path), "custom")
        self.assertEqual(assets.mode({assets.ENV_VAR: "generated"}, path),
                         "generated")
        self.assertEqual(assets.saved_mode({}, path), "custom")

    def test_nonsense_in_either_place_reads_as_the_default(self):
        # A typo in a shell profile or a half-written state file must not take
        # the sound out; it reads as unset.
        path = os.path.join(self.root, "battles-assets")
        with open(path, "w") as handle:
            handle.write("GENERATED\n")           # case is forgiven
        self.assertEqual(assets.mode({}, path), "generated")
        with open(path, "w") as handle:
            handle.write("whatever\n")
        self.assertEqual(assets.mode({}, path), "auto")
        self.assertEqual(assets.mode({assets.ENV_VAR: "custm"}, path), "auto")
        self.assertEqual(assets.mode({}, os.path.join(self.root, "nope")),
                         "auto")

    def test_saving_a_mode_round_trips_and_refuses_nonsense(self):
        path = os.path.join(self.root, "state", "battles-assets")
        self.assertIsNone(assets.set_mode("custom", {}, path))
        self.assertEqual(assets.mode({}, path), "custom")
        self.assertIsNotNone(assets.set_mode("loud", {}, path))
        self.assertEqual(assets.mode({}, path), "custom")   # left alone

    def test_the_custom_directory_is_outside_the_checkout(self):
        # A clone has to stay clean however much music is in it.
        self.assertEqual(assets.custom_dir({"XDG_CONFIG_HOME": "/some/config"}),
                         "/some/config/omarchy/hyprbattles/assets")
        self.assertFalse(assets.custom_dir().startswith(ROOT + os.sep))

    def test_the_daemon_resolves_through_the_same_order(self):
        # The daemon must not have a copy of any of this.
        mine = self.put(self.custom, "battle-theme.wav")
        sound = bd.Sound(assets=self.generated, custom=self.custom)
        self.addCleanup(os.environ.pop, assets.ENV_VAR, None)
        os.environ[assets.ENV_VAR] = "auto"
        self.assertEqual(sound.resolve("battle-theme.wav"), mine)
        os.environ[assets.ENV_VAR] = "generated"
        self.assertEqual(sound.resolve("battle-theme.wav"),
                         os.path.join(self.generated, "battle-theme.wav"))
        os.environ[assets.ENV_VAR] = "custom"
        self.assertIsNone(sound.resolve("battle-hit.wav"))

    def test_the_daemon_and_the_cli_agree_on_where_the_mode_lives(self):
        fresh = load_ctl()
        self.assertEqual(fresh.battle_assets.mode_path(), assets.mode_path())
        self.assertEqual(fresh.battle_assets.GENERATED, bd.ASSETS)


class GeneratedAudio(unittest.TestCase):
    """That what ships is really there, really audio, and really audible.

    Nobody can hear a test, so this is the ear: a file that is present but
    silent, clipped or half written sounds exactly like a bug in the daemon.
    """

    @staticmethod
    def samples(name):
        with wave.open(os.path.join(ROOT, "assets", name)) as handle:
            block = array.array("h")
            block.frombytes(handle.readframes(handle.getnframes()))
            return handle.getframerate(), handle.getnchannels(), block

    def test_every_generated_asset_is_a_playable_wav(self):
        for name in assets.SOUNDS:
            rate, channels, block = self.samples(name)
            self.assertEqual(rate, 22050, name)
            self.assertEqual(channels, 1, name)
            self.assertGreater(len(block), rate // 20, name)

    def test_nothing_is_silent_and_nothing_clips(self):
        for name in assets.SOUNDS:
            _, _, block = self.samples(name)
            peak = max(abs(value) for value in block)
            rms = math.sqrt(sum(float(v) * v for v in block) / len(block))
            self.assertGreater(peak, 0.2 * 32767, "%s is near silent" % name)
            self.assertLess(peak, 32767, "%s clips" % name)
            self.assertGreater(rms, 0.01 * 32767, "%s is near silent" % name)

    def test_the_one_shots_are_short_enough_not_to_trample_each_other(self):
        # They share one channel, so a new one cuts the last one off. Any
        # longer than a line of text takes to advance and they would queue up.
        for name in ("battle-select.wav", "battle-hit.wav", "battle-heal.wav"):
            rate, _, block = self.samples(name)
            self.assertLess(len(block) / float(rate), 0.5, name)

    def test_the_theme_loops_without_a_click(self):
        rate, _, block = self.samples("battle-theme.wav")
        seconds = len(block) / float(rate)
        self.assertGreater(seconds, 20.0)
        self.assertLess(seconds, 40.0)
        # The player restarts at sample zero, so the two ends are adjacent. A
        # step there bigger than the steps inside the file is the click; both
        # ends are taken to nothing, so there should be no step at all.
        seam = abs(block[0] - block[-1])
        inside = max(abs(block[index + 1] - block[index])
                     for index in range(0, len(block) - 1, 97))
        self.assertLessEqual(seam, inside, "the loop point clicks")
        self.assertLess(seam, 0.01 * 32767)

    def test_the_theme_leaves_room_for_the_one_shots(self):
        # Both channels go through the same player at the same volume, so the
        # music has to be mixed under the sounds that play over it.
        _, _, music = self.samples("battle-theme.wav")
        _, _, hit = self.samples("battle-hit.wav")
        self.assertLess(max(abs(value) for value in music),
                        max(abs(value) for value in hit))


if __name__ == "__main__":
    unittest.main(verbosity=1)
