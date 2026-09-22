.PHONY: test check audio

test:
	python3 tests/battles.py

check: test
	python3 -m py_compile bin/battles bin/hyprbattles-ctl bin/make-battle-audio
	python3 -m py_compile bin/import-battle-theme
	python3 -m py_compile lib/battle_rules.py lib/battle_assets.py
	python3 -m py_compile lib/hyprland.py lib/window_moves.py lib/pantry.py
	python3 -m py_compile lib/creatures.py lib/runtime.py lib/tools.py
	python3 -m json.tool manifest.json >/dev/null
	test -f Service.qml
	test -f Battle.qml
	test -f PixelText.qml
	test -f BattleFighter.qml
	test -f BattleStatusBox.qml
	test -f BattleTypeChip.qml
	test -f Roster.qml
	test -f Launcher.qml
	test -f hyprbattles.lua
	@if command -v luac >/dev/null 2>&1; then luac -p hyprbattles.lua; fi
	test -f assets/battle-theme.wav
	test -f assets/battle-select.wav
	test -f assets/battle-hit.wav
	test -f assets/battle-levelup.wav
	test -f assets/battle-heal.wav
	test -f assets/battle-evolve.wav
	test -f assets/battle-victory.wav
	test -f assets/battle-defeat.wav
	@if command -v omarchy >/dev/null 2>&1; then omarchy plugin validate .; fi

# Regenerate the committed chiptune, the looping theme included. It does not
# touch anything in ~/.config/omarchy/hyprbattles/assets/.
audio:
	python3 bin/make-battle-audio
