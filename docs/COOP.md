# Shared-world co-op

This fork has experimental **host-authoritative shared-world co-op** for the native Windows
ports. Two avatars move independently and see each other in the dungeon. The host
runs one game world: doors, enemies, items, combat, quests, randomness and clocks are
calculated in that process. The client sends input and receives its own host-rendered
view and the host's audio.

UW1 uses **two independent characters**. Each owns inventory (including nested bags,
stacks and cursor items), equipment, attributes, skills, experience, health, mana, runes,
active spells, hunger and fatigue. The client creates its character with the native
character creator on first joining. Quest flags, campaign variables, unique world
objects, enemies, doors and the world clock are shared. Equipment can be passed by
dropping it into the world for the other player to pick up.

The host owns a campaign with one persistent companion slot. Loading its campaign
restores both characters; reconnecting resumes the companion. Existing solo/older
party saves can be loaded, then a new companion is created. Importing an arbitrary
second solo character or moving characters between campaigns is not implemented.
UW2 still uses the earlier shared party sheet/inventory; these individual-character
changes and campaign integration checks target UW1.

## Windows launchers

Extract the complete ZIP on both PCs. Keep `Host.exe`, `Client.exe` and `bin/`
together, and use the rebuilt package on both machines.

1. Run `Host.exe`, select the game and click **Start host**. Create a character or load
   an adventure there. The host needs original GOG game data; **Game folder** can be
   left blank to find or choose it.
2. Run `Client.exe`, select the same game, enter the host's displayed LAN IPv4 address
   and click **Join game**. Use the same port, normally `27860`.
3. Once the host starts playing, the UW1 client uses the character creator for its own
   character. The adventure waits during creation. Later joins restore that campaign's
   companion. The client sees the host's menu while waiting for an adventure.

Allow the host game through Windows Firewall on the private network if prompted.
For two instances on one PC, use `127.0.0.1`. This is for a trusted LAN: no
matchmaking, relay, authentication or automatic NAT traversal is provided. Streaming
latency and the host's performance affect responsiveness. Browser builds do not
support shared sessions.

Only the host saves or loads campaigns. UW1 writes the companion to `coop2.dat` beside
the normal `PLAYER.DAT` in each save slot. Keep the entire save directory together.
Both players' inventories are detached from level archives and rebuilt on travel, so
inventory contents are not also left behind as world objects. Either avatar can start
level travel; both move to the same new level. Rejoins preserve saved positions when
valid, or use a nearby free tile. The companion's checked save format rejects damaged
or incompatible data instead of quietly discarding a character.

Conversations belong to the player who opened them and pause the other seat. The
campaign's ending runs once on the host and its scenes are shared. Friendly fire is
disabled. In UW1, when a teammate lives, a defeated character revives nearby at a
quarter of maximum health plus one and loses an eighth of experience, retaining its
items. If both fall, the native silver-tree/death and campaign restore paths apply.
Networking continues during modal screens. A host disconnect ends the active world;
the client can wait for the host to return. Unsaved progress follows the normal save
rules; joining a different host does not carry the previous campaign's character.

Launcher choices live in `%APPDATA%\underworld-exhumed-coop\host.ini` and
`client.ini`. Game files use `uw1\host`, `uw1\client`, `uw2\host` and
`uw2\client` below that directory. Host folders contain campaign saves;
`launcher-*.log` contains startup and connection messages. Ordinary single-player
saves are unaffected.

## Build

After setting up native dependencies for both games ([BUILDING.md](BUILDING.md)),
run on Windows:

```powershell
python tools/build-coop-windows.py --msys-root C:/msys64
```

This creates `build/coop-windows/Host.exe`, `build/coop-windows/Client.exe` and
`build/Underworld-Coop-Windows.zip`. It builds both games, collects DLL imports,
checks startup with a clean PATH, compiles with Windows' .NET Framework compiler,
and tests launcher process/argument/logging paths. `--skip-build` packages existing
release binaries. Matching source archives under `build/toolchain/` named
`munt.tar.gz` or `*.src.tar.zst` are included. The binaries need 64-bit Windows.

The launchers use these options:

```sh
uw1port.exe --data /path/to/UW1 --home ./host-uw1 --coop-host 27860 --coop-shared
uw1port.exe --home ./client-uw1 --coop-join 127.0.0.1:27860 --coop-shared
```

UW2 uses `uw2port.exe`. Record/replay and `--shot-at-flip` cannot be combined
with co-op. The solo input recorder is disabled in shared mode.

## Implementation

- `coop/shared_net.c` uses explicit byte order and validates version, game, message
  direction, sequence and size. A host accepts one guest. Protocol version 3 rejects
  earlier shared-world clients because they cannot display shared-scene frames.
  Reads, writes, timeouts and
  retries do not block the game thread; at most one outgoing packet is queued.
- `coop/shared_port.c` runs networking on a worker and serialises both avatars'
  actions on the host game thread. It switches physics, keyboard, pointer and camera
  contexts while keeping one world. `coop/uw1_characters.inc` copies the individual
  player/creature records and inventory/UI contexts into the native game's original
  storage (some inventory routines directly access `PlayerDat`). Explicit campaign
  fields carry their latest values between seats, including clears and toggles.
  The client runs no
  NPC AI or independent clock. Input, picture and audio buffers are bounded.
- The companion is an allocated mobile object excluded from NPC AI. The original
  renderer draws human art through its normal wall/sprite ordering. NPC targeting
  considers both avatars. UW1 damage, armour wear, healing and kill rewards use the
  corresponding character context. Object garbage collection protects both avatars
  and the tiles near them. Moving floors update both avatars' physics. Automatic NPC
  conversations use the facing target's character. Plot deaths use the killer's
  character, and cutscenes and nested ending pictures are shared with both views.
  Empty final-area NPC targets are handled safely.
- Save/load and level boundaries detach the companion before serialising or replacing
  object storage, then recreate it in the current world. A guest is not saved as an
  autonomous NPC. UW1's companion image uses the native relocatable inventory layout,
  validates its link graph, and is saved with a format version, sizes and checksum.
  Tybal's mana suppression and the shared orb restore each player's own reserve.
  Shared hooks in game sources are guarded by `#ifndef __TURBOC__`;
  solo and the earlier presence mode remain available.
- The Exhume submodule is unchanged. Windows build adapters wrap the audio output
  callback to forward actual mixed game sound as bounded stereo PCM packets.

## Verification

Transport and presence-adapter tests need no game files, SDL or Borland tools:

```sh
python tools/test-coop.py --cc clang --adapter
```

They cover the existing presence protocol plus shared pictures/input/audio, validation,
bounded queues, capacity, reconnects and timeouts. The Windows builder checks launcher
arguments, addresses, save isolation, UI rendering, process startup and captured logs.

With your own game data, integration checks use isolated homes under
`build/shared-world-tests/`, leaving campaign saves and original files untouched:

```sh
python tools/test-shared-world.py --data /path/to/UW1
python tools/test-shared-world.py --data /path/to/UW1 --interact
python tools/test-shared-world.py --data /path/to/UW1 --stationary --audio
python tools/test-shared-world.py --data /path/to/UW1 --stationary --transitions
python tools/test-shared-world.py --data /path/to/UW1 --stationary --characters
python tools/test-shared-world.py --data /path/to/UW1 --stationary --resume
python tools/test-shared-world.py --data /path/to/UW1 --chargen
python tools/test-shared-world.py --data /path/to/UW1 --campaign quests
python tools/test-shared-world.py --data /path/to/UW1 --campaign puzzles
python tools/test-shared-world.py --data /path/to/UW1 --campaign ritual
python tools/test-shared-world.py --data /path/to/UW1 --campaign ending
python tools/test-shared-world.py --data /path/to/UW1 --campaign terrain
python tools/test-shared-world.py --data /path/to/UW1 --campaign messages
python tools/test-shared-world.py --data /path/to/UW1 --campaign hud
python tools/test-shared-world.py --data /path/to/UW1 --campaign maps
python tools/test-shared-world.py --data /path/to/UW1 --campaign observer
python tools/test-shared-world.py --data /path/to/UW1 --campaign camp
python tools/test-shared-world.py --data /path/to/UW1 --campaign division
python tools/test-shared-world.py --data /path/to/UW1 --campaign orbs
python tools/test-shared-world.py --data /path/to/UW1 --campaign revival
```

UW1 has been exercised in actual processes for visible avatars, independent movement,
client use of a host-owned door, streamed non-silent audio, saving and level travel.
The character checks exercise separate items, nested stacks, cursor items, attributes,
skills, mana, spells/upkeep, shared quest clears/toggles, healing, rewards, campaign
save/load, companion revival, guest-initiated travel, all nine level archives and return,
and Tybal/orb mana rules. `--resume` starts fresh processes against the saved test slot;
`--chargen` drives the client's native character creator over the real transport.
Logs, screenshots and `result.json` describe the most recent check.

The campaign scenarios use separate homes under `build/campaign-tests/uw1/`:

- `quests`: hostile dialogue gates and script attitude for NPCs targeting either
  companion; original conversation script memory with native quest-bit/byte writes,
  reads and clears; plot-death flags; the original orb and Tybal objects, orb weakening,
  guest kill attribution and Tybal's death scene; Garamon's original grave, bones
  consumption and dialogue; automatic conversation with the facing guest; quest save/load.
- `puzzles`: bullfrog/platform controls, moving-floor physics and saved geometry;
  all nine original item-combination rules (including the three key fragments and
  incense); the four-emerald puzzle; client keyboard input playing the flute tune and
  chanting the key mantra; private rewards and duplicate-cup prevention.
- `ritual`: all eight distinct talismans split between inventories, premature and
  wrong-location rejection, counting a guest's throw while the host has fallen,
  save/load after four sacrifices, the remaining sacrifices, native Slasher banishment
  and both avatars arriving in the void.
- `ending`: the guest activates the original final exit trap; the ending cutscene
  runs once, the client receives the shared story view, both win pictures are
  dismissed and the host returns to the original menu. Host/client screenshots
  must match below their status banners. The image check uses Pillow and the
  original menu pixels/palette to recognize exact title animation phases; every
  other pixel must match.
- `terrain`: each player's modern Space shortcut retains its own attack choice after
  the companion chooses a different swing; both avatars follow native slope heights
  and receive shore footing;
  movement/shake clocks remain private; friendly attacks bypass armor damage rolls;
  a quiet fixture using level 8's original lava texture damages an unprotected guest,
  respects that guest's boot protection, and preserves the host's health and equipment
  state. The fixture supplies geometry and protection state to isolate these checks.
- `messages`: the original level 1 orb clue drawn on the alternate native graphics
  page, host locked-door feedback, and clearing the shared message history. Both
  camera pictures must contain the same nonblank text, then the same cleared pane.
- `hud`: separate full/quarter health and full/empty mana, swapping those values,
  and private poison coloring. Pixel checks detect a companion's stale flask fill
  in the other view. Native flask art is rebuilt between frames, after erasing old
  sprite layers, and its pixels are retained for the corresponding camera.
- `maps`: repeated map entry and exit by alternating characters, checking that
  the native mouse-handler count remains stable while viewing and after closing.
- `observer`: the opt-in campaign observer exports the real world without changing
  retained native dream captions, the eight string buffers, or the decoder's cursor,
  buffered bits and file position.
- `camp`: NPC rest and periodic updates run from either character's context without
  changing either avatar's health, AI flags or position; ordinary NPCs still receive
  their native rest healing. Normal player sleep uses percentage-based healing.
- `division`: compare the port's texture-projection and smooth-clipping overflow
  recovery with the original translated interrupt handlers, including repeated
  halving and zero-divisor recovery, flags and emulated stack balance.
- `orbs`: hold the original level-4 crystal-ball trigger through native mouse input;
  both transmitted viewports must match the changed native vision. Releasing the
  button restores separate cameras without moving or damaging either avatar.
- `revival`: revive each character in the original crypt geometry, avoiding nearby
  hostile creatures and hazardous floors. Check the private death penalty, cancelled
  attack, four-second recovery protection, ordinary companion damage, expiry, living
  enemies and the original post-ritual four-HP immortality rule.

`tools/uw1-playthrough.py` also runs a persistent campaign in isolated homes under
`build/uw1-playthrough/`. It uses the packaged UW1 executable, original game data,
normal character creation, real TCP client input, and native campaign saves. Its
opt-in observer exports world and inventory state and visible object pixels; it
cannot grant items, change quests/stats, teleport, or make characters invulnerable.
The input history and named checkpoints preserve both views, native saves, logs,
and world state. `coverage.json` records the completed and pending routes.
Inventory moves now detect rejected destinations and walking refuses to start while
an item remains on the cursor. A native recipe-to-rune-bag rejection verified both
guards and returning the item without changing either private inventory. Planned
river descents can use `go --max-drop`; native collision and fall damage still apply.
Use actions check the acting character's native range feedback before continuing,
so a rejected shrine interaction cannot turn the intended chant into movement keys.
The observer also preserves the native string decoder state. Without that protection,
its item-name reads replaced retained Garamon subtitles with item names. A regression
reproduced that overwrite, and a genuine saved-campaign rest replay now shows readable
dream captions with matching caption pixels in both views.

The live run has exercised level 1 starting equipment, Bragit/Hagbard/Gulik/Drog
conversations, the shared Hagbard flag, NPC-controlled gates, key use, item transfers,
separate sleep recovery, companion passage in narrow corridors, death recovery,
save/reload, Lanugo's native gift/recipe route, Vernix's campaign clues,
and client kills of the original rat, goblin, and Navrey, with private experience
rewards. The guest collected two original thread items for later crafting. A separate
checkpoint replay verifies that a five-coin gift leaves four coins with the guest,
awards its recipe privately, and preserves the host inventory through saving. Native
pick-buffer observations also confirm that both views contain the other avatar.
The driver now accounts for raised bridge surfaces and underpasses, checks pickup
results, and waits for cursor items to enter inventories before proceeding. It found
and fixed stale shared menus/text prompts, unbalanced nested story scopes,
companion movement obstruction, shared weapon animation clocks/art/swing state,
client melee originating from player one, guest-targeted NPC hostility checks,
player-one assumptions in slope/shore handling, missing guest lava/movement effects,
friendly armor damage rolls, and an original sprite-projection stall when companions
overlap at the camera. A previously stalled native checkpoint now reloads, and six
subsequent saves resume with fresh frames and unchanged inventories. The opt-in
checkpoint hook also defers object-relocating saves until an ordinary host frame.
The continued run collected the spare original stone key and preserved it in the
guest's inventory across native save/load. The guest crossed the shrine platforms,
pressed the original wall button to open the shared stone door, passed underneath
it during a descending jump, and chanted at the original shrine. Its attack skill
rose from 15 to 19 while the host's remained 12. The shrine door requires its button;
rejection of the red and stone keys there is original game behavior.
The modern Space attack preference was also found to be shared between characters;
a native regression reproduced this and now verifies separate remembered choices.
Further native level 1 play completed Jaacar's privy clue and the hidden healing
fountain route. The fountain healed the host from 18 to 35 while the guest stayed
at 19. The guest left the shrine by native long jumps, followed the eastern route,
opened the original skull door with its private stone key, and looked into the
original crystal ball. This exposed a missing-client-clue bug: the host could read
the orb text while the guest's pane stayed blank. Shared HUD text now retains the
original drawing-page pixels for both views; conversations and cutscenes keep their
own picture handling. The original client orb lookup has been replayed through
real TCP input and its displayed text compared in both views.
The flask redraw also inherited the other character's graphics and left old layers
behind. Health and mana pictures now use each character's own native art and fill;
bubble state and poison frame choices remain private. The persistent host at 35/35
health and guest at 19/40 now have full and partial bottles respectively.
The playthrough driver observes landing before releasing a native long jump, permits
walking back from ledge overhangs using the observed footing height, and waits for
complete native PNG writes before storing checkpoint screenshots.
The continued native run completed Korianous's platform route in both directions,
recovered its coffer, defeated the optional skeleton, equipped its chain cowl on the
guest, and descended through the privy with both inventories intact. On level 2 the
party collected the red gem key, heard Corby's clues, cleared the mine cave-in with
an original rock hammer, defeated the gazer, and received Goldthirst's gemcutter and
treasury password. Ironwit accepted his actual blueprint scroll and awarded a flight
potion. The host crossed the storeroom gap using the original potion while the guest
remained grounded, and learned Uus without changing the guest's runes. These items,
private inventories and shared quests also survived a fresh-process restore.
The host then transferred Ironwit's reward through the world to the guest, who used
it to collect fifty original treasury coins and fly back out without taking damage;
the host remained on the gallery without a flight effect.

The gazer fight exposed a campaign soft-lock: companion revival called the native
placement search with its destructive clearing option. It removed the living plot
NPC at 31 HP without running its death quest, leaving Goldthirst's reward unavailable.
Revival and companion spawn now use non-destructive placement. A native regression
preserves a living gazer beside the companion, kills it through the normal damage and
death handlers, and checks that its quest reaches both characters. Replaying the actual
pre-fight campaign save also completed the fight and reward successfully.

The original royal stairs exposed another placement issue on level 3: the guest's
preferred adjacent tile was the return-stair trigger. Its first movement sent the
whole party back to level 2. Companion spawn and rescue now retain the native search
while excluding player movement-trigger tiles and preferring space separate from the
other avatar. Ordinary teleport placement is unchanged. The native regression uses
that exact arrival, and the saved campaign replay verifies visible, separate avatars
in both cameras and guest movement that remains on level 3.

Leaving the automap open during the level 3 campaign exposed an input-table leak.
Seat switching requested every editor change, including the map initializer, which
registered another mouse handler each frame. Character switches now request the
character HUD only on the adventure screen; native screen changes retain their own
initialization requests. The regression reproduces the old growth and checks repeated
entry, viewing and exit with both characters.

The complete main story, all talisman acquisition routes, and optional side quests
are still in progress. The persistent campaign has reached level 5 through the
Bullfrog route. On an earlier return to level 3, the guest acquired the original Taper of Sacrifice through Zak's native
barter. Back on level 4, the guest defeated Rodrick, and Dorna recognized that victory
when the host spoke to him and received the Standard of Honor. These two original
talismans remain in separate inventories. The guest completed Ishtass's
Ossikka delivery with the original scroll and
received the private Wis stone, wand and potion reward. The bandit key and southern
combat route are cleared; the remaining level 3 routes require a return. The remaining
talismans and ending have not been completed in this run. On level 4, the host's Crux
initiation was recognized by the guest's troll dialogue; the guest recovered and
delivered the Writ of Lorne, received and equipped a private plate helm, and completed
Derek's Gem Cutter delivery. The host made rotworm stew from the original ingredients
and recipe, then exchanged it with Sethar for dragon scales. Both characters advanced
their own skills at original shrines.

On returning to level 3, the guest supplied fresh fish to free Murgo and received his
thank-you dialogue. The party also completed the vine Search checks and pond drainage,
defeated the ghost, and recovered Caliburn's original broken blade. These checkpoints
retain the guest's talisman and blade, shared quest state, and separate character stats.

The input driver also checks that inventory drags actually change the acting player's
inventory, so a hidden inventory panel cannot silently pass as an equipment change.
Barter offers verify the expected item-count decrease before returning; this avoids
an extra look click that could leave a text prompt ahead of the next offer. The live
campaign verified the rune-panel rejection and the original talisman barter retry.
Conversation cursor placement uses the native right-button inventory action, as
verified when the host received and saved the Standard of Honor.

The party also solved the original gold/silver switch sequence in the Maze of
Silas, recovered Sir Ingvar's plate and mace, and transferred both through the
shared world to the host. Dorna accepted the plate and opened the shared armory;
the host equipped its original plate armor. The isolated northwest towers remain
for the later prison route rather than being reachable from this maze.

A subsequent maze crossing stopped the native renderer with an interrupt return
on a near-call frame. The port's divide-fault adapter omitted the texture projection
and smooth clipping handlers that return with IRET. It now executes those original
translated handlers and resumes after the faulting divide, including recursive
smooth-clipping retries. `--campaign division` compares the adapter's registers,
flags and stack with the original handlers; it reproduces the missing-handler
failure before the repair and passes afterwards. The complete campaign remains
in progress.

The saved campaign also completed Trisch's recovered-Taper acknowledgment and
Sethar's pit, including its original rune pouch, scroll and secret exit. The host
built both Bullfrog ramps with the original selectors and buttons while the guest
crossed them. Lowering and raising the guest's occupied platform changed its native
footing from 12 to 10 and back to 12, leaving the host at the controls. The guest
crossed the northeast gap and used a running jump from the southern ramp to recover
the hidden Fireball wand and potion. The driver now waits for zero vertical velocity
and acceleration before reporting a landing; the ground-contact bit alone can be
set while an avatar is still rising beside a ledge.

The hidden orb exposed another display omission: its native fade wrote directly
to video memory while the ordinary two-seat frame loop was blocked. Neither co-op
window received the remote view. The fade now uses the existing shared-scene scope;
the regression fails on the old behavior and matches both viewports to native video
memory after the repair. Replaying the actual campaign's held Look action shows the
same northwest mage room in both windows, keeps both positions unchanged and returns
to separate cameras on release.

Both characters then entered the original level-5 tombs through the northern
Bullfrog stairs. The guest recovered Caliburn's original hilt while retaining its
blade, and the host opened the secret route into Cabirus's crypt and read its
memorial. The remaining talismans, later levels, ending and optional routes are
still pending in this campaign.

The crypt fight exposed repeated deaths immediately after revival beside the same
enemies. Co-op rescue now prefers dry ground outside nearby hostile creatures'
reach, cancels the interrupted attack and protects only the revived character for
four real seconds. It retains the existing experience penalty and inventory. The
native regression checks both characters and confirms ordinary damage resumes when
the window expires. After the final talisman sacrifice, co-op now delegates to the
original four-HP immortality rule without charging an extra death penalty.

Both Windows binaries build. These scenarios supply prerequisites and call native
handlers or drive native input; they are **not a completed start-to-finish playthrough**.
Every NPC dialogue branch, barter, all eight talisman acquisition routes, combat balance,
the final maze route and extended two-human sessions still need end-to-end playtesting.
UW2's in-game behaviour also needs testing. The current
build should be treated as an experimental campaign playtest, with regular save slots.
DOS byte-matching still needs private Borland inputs ([BUILDING.md](BUILDING.md)).

## Earlier presence mode

Omit `--coop-shared` for the earlier position/health-only transport in
`coop/protocol.c`, `coop/session.c` and `coop/port.c`. That mode runs independent
worlds with a status strip and same-level automap cross. It does not draw a second
avatar or synchronise interactions. Older binaries cannot join the shared mode.
