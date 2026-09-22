-- Put `hyprbattles-ctl move` on the keys you already move windows with.
--
--   local battles = dofile(os.getenv("HOME")
--     .. "/.config/omarchy/plugins/dev.cstav.omarchy.plugin.hyprbattles/hyprbattles.lua")
--   battles.bind("SUPER + SHIFT", { "LEFT", "DOWN", "UP", "RIGHT" })
--
-- Keys come in left, down, up, right order - h, j, k, l - so a vim setup is
-- { "H", "J", "K", "L" }. Whatever sat on those keys is unbound first: the
-- move replaces it and keeps doing its job, battles on or off, daemon up or
-- down.
--
-- dofile rather than require, because the plugin's directory name is full of
-- dots and require reads every dot as a slash. The script finds itself, so
-- the checkout can live anywhere.
--
-- All this file ever binds is `hyprbattles-ctl move <direction>`. Nothing is
-- dispatched here, and nothing is bound until bind() is called.

local M = {}

local here = debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or "."
M.ctl = here .. "/bin/hyprbattles-ctl"
M.directions = { "left", "down", "up", "right" }

local function quote(text)
  return "'" .. text:gsub("'", "'\\''") .. "'"
end

-- The shell command that moves the focused window one cell that way.
function M.move(direction)
  return quote(M.ctl) .. " move " .. direction
end

-- Bind four keys under one set of modifiers, left, down, up, right.
function M.bind(mods, keys)
  assert(type(keys) == "table" and #keys == 4,
    "hyprbattles: bind(mods, keys) wants four keys, in left, down, up, right order")
  for i, direction in ipairs(M.directions) do
    local combo = mods .. " + " .. keys[i]
    hl.unbind(combo)
    hl.bind(combo, hl.dsp.exec_cmd(M.move(direction)),
      { description = "Window: Move " .. direction })
  end
end

return M
