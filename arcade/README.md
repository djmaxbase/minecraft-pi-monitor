# BLACKSITE ARCADE OS 3.0

A self-contained CC:Tweaked arcade for a **6×3 Advanced Monitor**, **Advanced Computer** and **Create Linked Controller**. The console uses Minecraft's 16-color terminal graphics. All game logic, menu, settings and saving are in `arcade.lua` (no additional downloads).

## Installation

On the Advanced Computer, run the following commands separately:

```
delete arcade.lua
wget https://raw.githubusercontent.com/djmaxbase/minecraft-pi-monitor/main/arcade/arcade.lua arcade.lua
arcade
```

For automatic startup, create `startup.lua` using `edit startup.lua`, with this one Lua line:

```lua
shell.run("arcade.lua")
```

Do **not** use an infinite restart loop in startup.lua. If you need to interrupt the arcade, Ctrl+T on the Advanced Computer.

## Controller setup

Configure five Create Redstone Link receivers, with unique matching frequencies and redstone output to these Advanced Computer sides:

| Linked Controller | Redstone computer side | Function |
|---|---|---|
| Left | `left` | Left |
| Right | `top` | Right |
| Up | `bottom` | Up |
| Down | `back` | Down |
| Space **or Shift** on Create controller | `front` | Select / Action |

The front receiver is treated as **Space/Action**, irrespective of which Create-controller button physically triggers it. Hold this action button for **1.2 seconds** to enter the pause menu; choose Resume, Restart or Exit with Up/Down and Action.

The directional buttons support keyboard-style hold-to-repeat. Keyboard fallback: WASD / arrow keys, Space / Enter, P to pause, Q to quit.

A Create Linked Controller transmits wireless redstone; **no CC:Tweaked modem is required**.

## Installed games (18)

Arcade: Neon Snake, Pixel Pong, Block Drop, Breakout, Space Blaster.

Reflex: Flappy Pixel, Meteor Dodge, Neon Racer, Reaction Lab, Whack-A-Mob, Target Rush.

Puzzle: 2048, Memory Match, Minefield, Lights Out, Simon Signal.

Adventure: Maze Escape.

Party: Connect Four (vs CPU).

## System

- Six-card graphical launcher, selectable on the controller, with an Advanced Monitor touchscreen launcher shortcut.
- Score, status and game-specific instruction HUDs.
- Local high scores, games played and system preferences stored in `blacksite_arcade_save`.
- Migrates highscores once from the earlier `arcade_scores` file.
- Theme selection (Neon Purple, Ocean Blue, Toxic Green).
- Casual, Classic and Hardcore difficulty/speed presets (primarily timer-driven arcade games).
- Configurable held-direction repeat speed.
- Optional sound effects when a CC:Tweaked speaker is connected.
- Records, Settings, Help and pause/restart/exit screens.
- Monitor fixed at text scale 0.5, appropriate for the 6×3 arcade cabinet.

## Notes

CC:Tweaked monitors have a text/pixel grid and 16-color palette, not a GPU, so games use pixel-style colored cells and text iconography. The application needs an Advanced Computer and an Advanced Monitor (or another color terminal). Gameplay requires redstone receivers placed so each button powers the indicated side.

The Lua code is a substantial game pack and should be play-tested in the target Minecraft modpack. If a game reports an error, the program prints it to the Advanced Computer terminal to help diagnose and fix it.
