# Demo notes: how the 3D dice throw works

The demo at the repository root (`index.html`, `main.js`, `physics.js`) is a standalone page. One die or a handful of up to 10 (d4 to d20, the d100 pair, the d100 ball)
thrown on a felt table with three.js (drawing) and cannon-es (physics). No build step, no network at runtime.

Run it from the repository root (ES modules need http, `file://` will not work):

```
python3 -m http.server 8790 --bind 127.0.0.1
# open http://127.0.0.1:8790/
```

## Use

- **Die** picker (d4 to d20, `d100 pair`, `d100 ball`): only while idle. Picking replaces the handful with that one entry (the quick way),
  puts it at rest, rebuilds the Land on list and clears the last roll. It shows `handful` while the handful is not exactly one entry.
  Models load on first use and are cached (each die on the table is a clone of the cached model). The result text and history chips name the die (`d6 4`; last 10 kept). A face can carry a `value` in `faces.json` that is shown instead of its `number` (d10: the face numbered 0 reads 10).
- **Dice panel** (handful, see *Several dice* below): a table at the left edge, one row per kind (d4 ... d20, d100, ball): `− [icon] +`, **Clear** at the bottom.
- **Throw** button (or Space, unless a button or select has the focus). Or press the table, shake and release: the **hand box** (below), for one die or a handful.
- **Land on** `free` / the values of the current die: forces the result (simulate-then-turn, see below). The option labels are the shown values (`value ?? number`), the option values are face **indices**, so face 0 can never be mistaken for `free`. With a target set, the hand box is
  disabled (a short note says so): the relabel would show in your hand, so forced throws only use the Throw button.
- **Lift result: on** (default): the die stays where physics left it for about 1 s, then floats toward the camera
  (0.6 s, ease-in-out), turning in the air so the rolled face looks straight at the camera with its digit upright
  (from the face `normal` and `up` in `<die>.faces.json`), and grows to 1.05x. A d4 has no `up`: its top corner goes to
  screen-up, its `front` direction faces the camera, then the top leans 25 degrees toward the camera (seen from above, an edge toward you). It holds there with the big "Rolled N" text.
  It stays there until the next throw: a tap/click drops it (a new free throw, through the hand box: scoop + immediate release), pressing and shaking
  scoops it into the hand box, Throw starts a normal throw. With Land on set it stays floating until Throw (no hand throws then).
- **Lift result: off**: no lift; instead the die turns on the table about the vertical axis (0.35 s, ease-out) so the
  digit reads upright toward the top of the screen (not for the d4: no `up`, so no turn).
- **Textures** button (top right, first): cycles Full -> High -> Light. The models are the same everywhere (identical meshes and `faces.json`); only the textures differ:
  `dice/models/` = Full (2048 px), `dice/models/high/` = High (1024 px), `dice/models/light/` = Light (512 px). Default Light on touch-first devices (`pointer: coarse`), else Full;
  the choice is remembered in the browser (`localStorage` key `vtt-dice.tex`, ignored when storage is blocked). Only while idle (disabled otherwise); a click reloads the dice on the table
  from the new folder, same handful. Models are cached per tier, so switching back is instant.
- **Shadows** toggle: turns real shadows and high pixel ratio off (cheap blob shadow instead).
- Top-left readout: fps, frame time, JS time per frame. Bottom line: `forced`, `replay matched`, seed.

## Several dice (handful)

- **Handful:** a list of entries (`kinds` in `main.js`, kept in panel order d4, d6, d8, d10, d12, d20, d100, ball). At most **10 dice**; the d100 pair counts 2,
  so a + button is disabled when its dice would not fit. `KINDS` maps an entry to its models (`d100` -> `['d10t', 'd10']`) and its values `1..sides`.
  **Dice panel** (`#tray`, built in `main.js` from `KINDS`): header `Dice` and `n / 10`, then one row per kind in tray order, each `− [icon + name] +` with the die's
  picture (`dice/icons/<kind>.webp`, 128x128, shown 56-60 px; `d100` = the pair, `ball`) between the buttons, the name under it (`d4` ... `d20`, `d100`, `d100 ball`) and a gold
  count badge on the icon's corner when the count is above 0 (that row also gets the gold border). − is disabled at 0, + when the die would not fit; buttons are 44 px; **Clear**
  in the footer (disabled when empty). Everything is locked while not idle, and every click goes through `setHand`, so the picker, the panel and the test hooks stay in step.
  From 760 px width the panel is fixed at the left edge (180 px wide), centred in the free band like the stats panel, and scrolls inside when too tall; `fitCamera` uses its
  right edge as the left limit, so the table and the lifted row sit centred between the two side panels. Below 760 px it is hidden; the **Dice (n)** button opens it as a
  sheet above the bar (two columns when two rows fit, i.e. 360 px phones; else one) and the x, Escape, Throw or a tap outside closes it (the tap that closes does not scoop the dice).
  Every die on the table is one `THREE.Group` with a clone of the cached model and its own blob shadow.
- **Adaptive table width:** the table is `HALF_X` wide and `HALF_Z` (3.4) deep (inner half sizes, die-units). `fitCamera` measures the free screen area between the side panels and the
  top and bottom bars and sets the wanted `HALF_X = clamp(3.4 * (width / height) / 1.25, 3.4, 6.1)`, rounded to 0.1: a wide monitor gets a wider table, a portrait phone keeps the
  square 3.4. The new size is applied only while idle or loading (`applyTable`; during a hold or a throw the old table stays and the frame loop applies the new one right after):
  it rebuilds the felt and the four rim pieces (old geometries disposed), calls `setTable(hx, hz)` in `physics.js` and pulls resting dice back inside along x if the table got narrower.
  `makeSim(dice, {hx, hz})` builds the x walls and ramps at `hx` and the z ones at `hz`, and keeps the size in `sim.table`; `launchRoll` passes the same `{hx, hz}` to the hidden run
  and the replay, so they always share one table (`selfTest` uses the current one). Hand and flick clamps use `HALF_X` for x and `HALF_Z` for z; the dice grid takes more dice per row
  when the table is wide. A throw is only reproducible from its seed on the same table width, because the walls decide where it ends.
- **Physics:** one world, one body per die, added in hand order (`makeSim(dice)`, `launch(sim, specs)`, `runHeadless(specs, dice)` in `physics.js`).
  Drag, ramps and rest detection run per die; the throw ends when **all** dice rest at the same step (or at the 5 s limit).
  Dice knock each other with their own contact material (friction 0.1, restitution 0.35): slippery, so a die leaning on a die tends to slide down.
- **Throw start:** one seed, one random stream, drawn die by die in hand order (own orientation, velocity and spin per die). The dice start on a grid
  (`grid`: rows of 5, 1.3 apart, front row at the single-die spot) with a small jitter: free throws at the near edge, forced throws each raised until
  it is outside the camera view. A handful of one draws exactly the single-die numbers.
- **Server roll** (a stand-in for a server or game master deciding the result; switch shown instead of Land on when the handful has more than one die): Throw first picks a uniform random face per die with
  `crypto.getRandomValues` (as a server or game master would), shows the picks small (`server: 4, 6, 37`, also in the status line), runs the whole handful
  hidden, relabels each die with its own turn (polyhedra: a hull symmetry; the ball: target aimed at its final up), and replays. Per die the same safety
  nets as before apply (settle tween if the replay misses, tilt fix). Hand throws are off while it is on (a note says so).
- **d100 pair:** the tens die `d10t` (faces 00..90, `value` 0..90) + the d10. Result = tens + ones (the d10's `number` 0..9), `00 + 0 = 100`.
  The d10 alone still reads its zero face as 10.
- **Result:** big `Rolled <total>` (sum of the entries), then a chip per entry (`d6 4`, `d100 37 30 + 7`). The history chip shows the total
  (label `sum`, or the kind when all entries are the same kind) with the parts in its tooltip. A handful of one looks exactly as before.
- **Lift:** after rest the dice float into one row toward the camera along screen-right, centred, each rolled face to the camera with its digit
  upright (`heldPose` per die with an offset). Spacing follows each die's size (the d100 pair sits closer together); a row wider than the free screen
  shrinks spacing and size together so nothing overlaps. A click drops the whole row as a new free throw: a lifted row restarts on the table grid
  around its centre at its height (the real dice are bigger than a shrunk row), dice lying on the table restart where they are.
- **Hand:** pressing the table scoops the dice into the hand box (next section), for one die as well as for several.

## Hand box

Press the table (canvas, mouse or touch), shake, release. Works for a handful of any size, one die included.

- **Scoop** (`holdStart` in `main.js`, only while idle): `makeHand(dice, quats, at)` in `physics.js` builds a **separate cannon world** with the same gravity and the same
  die-die and die-wall contact materials (`newWorld`), one body per die in the same order as the throw (`addDie` with `loose`: a **sphere of radius = the die's tip**, which holds the whole die, instead of the hull; orientation still integrates, so friction and wall hits make the dice tumble), and **one kinematic box body**
  of six thin `CANNON.Box` shapes (floor, lid, 4 walls, 0.5 thick) around the inner space. No table, no felt. The dice jump into the box at once, keeping their drawn
  orientation (a lifted row goes back to normal size), on a grid (rows of `ceil(sqrt n)`) standing on the box floor. The box centre starts above the pointer's table point
  at `HAND_Y` (2.4) and is clamped so the whole box stays over the table. The box and its dice are drawn from the hand bodies; the box itself is invisible, only a faint
  blob shadow (opacity 0.22, the die blob texture) shows where it hovers.
- **Size** (`handBox`): inner width = depth = `1.1 + 0.35 * sqrt(n)` (n = 1: 1.45, 4: 1.8, 10: 2.2), but at least one grid cell per die (`ceil(sqrt n) * 2.05 * the biggest tip`), so 10 dice do not start packed into a box smaller than themselves. Inner height = 0.9, but at least
  2.1 x the biggest tip (the ball, 1.1 wide, would not fit under a 0.9 lid).
- **Shake:** each frame the target is the pointer's point on the `HAND_Y` plane (clamped). `stepHand` sets the box's **velocity** `v = (target - position) / DT`, capped to
  `BOX_SPEED` = 25 u/s, and steps the hand world with the same fixed `DT` (1/120 s; whole steps from an accumulator, at most 4 per frame while holding, 6 for a roll; drawn between the last two
  steps). So dice rattle against each other and the walls, and holding still lets them settle on the box floor.
- **Why velocity, not teleporting:** cannon only resolves a hit when it sees the wall move. A kinematic body moved by velocity pushes the dice with its real speed in the solver; setting
  its position each frame would let a thin wall jump over a die (no contact, the die is lost) or give the die a wrong, huge impulse. The cap (0.21 u per step) is smaller than the wall
  thickness (0.5), so even a hard shake cannot skip a die through a wall. A safety net puts a die that is still found more than 0.6 outside the box back in its centre.
- **Release** (`holdEnd`, pointerup): per die, position, quaternion, velocity and angular velocity come from the hand world; the **flick** is added to the velocity: the box's velocity over
  the last 0.1 s of hand-world time (`trail`), horizontal, capped at 10 u/s, plus an upward `1 + 0.12 * speed` (up to 2.2); the resulting speed is capped at `BOX_SPEED`, positions are
  clamped inside the table (`HALF_X - 0.5` in x, `HALF_Z - 0.5` in z). Then a normal **free** `launchRoll` with these specs: no hidden run, no relabel, so the tally counts it. The dice still carry the speed they had
  as the box moved, so the flick comes on top of it (a hard flick is fast; the caps keep it inside the table).
- **Click** (no movement, or a very short press): the dice are dropped from the box and fall (also how a lifted row is dropped). **pointercancel** / lost pointer capture: release without the flick.
- **Not in the hand box:** Server roll on (several dice) or `Land on` set (one die): pressing only shows a note, the relabel would be visible in the hand. Throw works as before.
- **While held** `dice.state` is `'holding'`; all controls are locked as in any other non-idle state.

## Performance

Measured in pure physics (10 dice of one kind), ms per fixed 1/120 s step before these changes:

| | d4 | d6 | d8 | d10 | d12 | d20 | ball |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hand box | 0.6 | 1.1 | 0.7 | 7.2 | 10.3 | 11.7 | 0.14 |
| table throw | <= 0.3 | <= 0.3 | <= 0.3 | <= 0.3 | 1.6 | 1.1 | <= 0.3 |

Ten d12 or d20 in the hand box needed about 23 ms of physics per 60 Hz frame (2 steps), and the old catch-up (up to 12 steps) then snowballed. Cause: cannon's convex-convex SAT
cost grows with faces x faces, and the trimmed d12/d20 hulls have 32 faces. Changes (`physics.js`, `main.js`):

- **Hand box = spheres.** `makeHand` gives every die a `CANNON.Sphere` of radius = its tip (contains the die, so no overlap at release); `handBox` sizes the box for the biggest tip.
  The throw world still uses the exact hulls.
- **Capped catch-up.** At most 6 fixed steps per frame while rolling and 4 while holding; when the cap is hit the leftover time is dropped (`acc = min(acc, DT)`). The steps and their order are
  unchanged (hidden run and replay stay identical); only the playback speed drops on a slow frame.
- **Hull cache + unique axes.** The trimmed hull of each (hullDef, tip) is built once (`hullShape`); every world gets a new `ConvexPolyhedron` from the cached arrays, with
  `axes` = face normals without parallel/antiparallel duplicates, so the SAT tests half the face directions on d6/d12/d20.
- **Broadphase stays `NaiveBroadphase`.** With about 20 bodies the pair loop is negligible next to the narrowphase, and cannon-es's SAPBroadphase mixes its sort key (AABB lower bound) with
  position +- bounding radius in the sweep and treats the infinite planes poorly, so it could miss pairs for no measurable gain.

Not re-measured after the changes yet.

## Tally

A side panel counts how often each number came up, per kind (d4 ... d20, `d100 pair`, `d100 ball`); the **Die** select in the panel picks the table
(it follows the picker and the last + button; nothing is lost).

- **What counts:** only free throws (Throw button, hand-box throw or click-drop with `Land on = free` / Server roll off). Forced throws are never counted.
  Counted in `showResult`, every die by its kind and shown value (`value ?? number`, so the d10 zero face counts as 10); the d100 pair counts its
  combined value under `d100` (1..100), the ball under `ball`. The header reads `<kind> · N throws`
  and `expected X % each` (100 / sides); each row shows the value, the count, a bar (count / the highest count) and the share of N (`–` while N is 0).
- **Layout:** from 760 px width the panel sits at the right edge (the dice panel mirrors it at the left edge) and the 3D table is fitted into the area left of it (`fitCamera` uses the panel's left edge as the right limit).
  Below that it is hidden; the **Stats** button (top right) shows it as an overlay sheet below the buttons, the x or Stats again hides it. On wide screens Stats hides/shows the panel too (default shown).
- **Storage:** `localStorage` key `dice-demo-tally-v1`, JSON `{ "v": 2, "d6": { "1": 3, "4": 1 } }`. Every access is in try/catch; if storage is blocked the tally lives in memory until reload.
- **Migration:** older versions stored the ball under `d100`. A stored tally without `"v": 2` is the old layout: on load its `d100` counts move to `ball`
  (once; it is saved back with `"v": 2` right away), and `d100` now means the pair.
- **Reset:** *Reset this die* (the kind shown), and *Reset all* (asks `confirm()` first). Test hooks: `dice.tally` (a copy of the counts) and `dice.resetTally(all)` (no confirm; `true` = every kind, otherwise the one shown).
  Fast throws (`dice.fast`) count too when free.

## Files

| File | Role |
| --- | --- |
| `index.html` | page, styles, importmap |
| `main.js` | scene, camera, input (hand box), UI, replay loop (three.js) |
| `physics.js` | cannon-es world, fixed step 1/120 s, rest detection, headless run, hull trimming, symmetry group from the face normals, hand-box world |
| `dice/models/d4/d6/d8/d10/d10t/d12/d20/d100.glb`, `*.faces.json` | die meshes (circumradius 0.5, gltf Y-up), per-face data and the sharp physics `hull` (`d10t` = tens die of the d100 pair, `d100` = the ball) |
| `dice/icons/`, `dice/results/` | picker icons and result stills |
| `tools/dice3d.py` | Blender script that builds the models and stills |
| `vendor/` | vendored libraries with their licences |

## How forcing works

1. The throw (position, orientation, velocities per die) is built from a seed and stored as plain numbers.
2. A hidden cannon-es world runs that throw with the fixed 1/120 s step until all dice rest;
   each result is read from the `<die>.faces.json` normals (the entry whose world normal is most aligned with +Y).
3. Each mesh is turned by one of its die's symmetry rotations (see below), chosen so
   the wanted face takes the landed face's place. The physics shape is symmetric, so the turn
   does not change the trajectory (it is equivalent to pre-applying it to the start orientation).
   The turn is applied at launch while the die is **not visible**: with a target set, Throw starts the die high
   above the table, outside the camera frustum (found at runtime), so it drops into view already relabelled.
   (Free mode starts at the near edge; no relabel is involved.)
4. The same throw is replayed visibly with identical steps (same body order, same specs, same `physDefs()` list). Every die must end on its
   predicted face; a die that does not gets a 0.35 s settle tween to its target and a warning is logged (`roll.fallback`).
   Relabelling never changes a physics shape, so dice knocking each other replay identically too.

## Dice, hulls, symmetries

`h` is the centre-to-face distance, measured from the mesh at load: per face the farthest vertex along the face
direction (all meshes, so recessed numbers never shrink it), averaged, times the die's scale. A resting die sits at
height `h`. There is no per-die shape code: the physics shape comes from `"hull"` in `<die>.faces.json`,
`{ "verts": [[x,y,z],..], "faces": [[i,j,k,..],..] }`, the die's **sharp** polyhedron in glTF axes at the model's own scale
(circumradius 0.5, same units as the `.glb`), faces in cyclic order. `main.js` multiplies the vertices by the die's `DICE` scale and
hands `{ verts, faces }` per die to `makeSim`/`runHeadless`; `physics.js` trims it (below), re-winds every face outward and builds the cannon-es hull.
A `faces.json` without `hull` fails to load with an error.

The bevelled corners of a mesh stop short of the hull's sharp ones, so a sharp hull would prop the die on invisible
tips. Therefore the sharp hull is trimmed (`trim` in `physics.js`): at load the farthest vertex from the centre over all
meshes is measured (`tip`, times the scale; logged next to `h`, model values at scale 1: d4 0.435, d6 0.471, d8 0.458,
against 0.5 for the sharp corners). Every hull corner farther out than `tip` is cut by a plane square to its direction
at distance `tip`: faces keep their cyclic order, the corner becomes the points where the plane crosses its edges, and
each cut corner gets a small cap face (a triangle or quad). `makeSim(dice)` and `runHeadless(specs, dice)` take one `{ h, faces, hullDef, tip, sphere }` per die, `tip`
(default infinity = no trimming); hidden run and replay must pass the same arguments. Visual size comes from the `DICE` table in `main.js`
(all polyhedra x0.8 and the ball a bit larger than the rest: d4 0.92, d6 0.88, d8 0.8, d10 0.76, d10t 0.76, d12 0.8, d20 0.84, ball 1.1):
the scale multiplies model and physics together, so the set looks even. `h` is logged per die in the console.

**Symmetries.** `symsFor(faces)` computes, from the face normals alone, every rotation (3x3, det +1) that maps the set of
`faces[].normal` onto itself, no matter which die: take reference normals `a` = the first and `b` = the first one not parallel to it; for each ordered pair
`(c, d)` of normals with the same angle as `(a, b)`, build the rotation that sends `a` to `c` and `b` to `d` (orthonormal frames
`F(c,d) * F(a,b)^T`), keep it when every normal lands on a normal (dot > 0.999), drop duplicates. Cached per `faces` array.
Counts: d4 12, d6 24, d8 24, d10 10, d12 60, d20 60 (`dice.selfTest()` reports `syms`). Among the candidates for a given
from/to pair the tie-break prefers the one that keeps `up` (or `front` for the d4) closest; without either the first wins.

**Reading.** `read: "face"` (default when missing; d6, d8): the face pointing up is the result. `read: "vertex"` (d4):
`normal` is the corner direction and the corner pointing up is the result; the die rests on the opposite face
(outward normal `-normal`), and `front` is the direction that faces the camera in the show pose.

## Sphere mode (d100 ball)

The ball's `DICE` key is `ball` (label `d100 ball`, `file: 'd100'`, so it loads `d100.glb`/`d100.faces.json`); `d100` is the pair.
`d100.faces.json` has `"physics": "sphere"` (plus the usual `faces[]` with `number`, `normal`, `up`, `read: "face"`; `hull` is optional for it).
`main.js` keeps the flag per model (`m.sphere`) and passes it in the die's `makeSim`/`runHeadless` entry, identically for the hidden run and the replay.
Why a separate mode: 100 near-equal faces make a ball. Its face normals have no useful symmetry group to search for, and a 100-face hull would rest on edges, roll for a long time and need nudging.

- **Shape:** `CANNON.Sphere(h)`, `h` = centre-to-face distance (already times the scale), so a ball lying on a face sits at the right height. No trimming.
- **Rest:** the ball is done when it is `calm` or `still` (never needs a face within `FLAT` of up). Rolling drag applies whenever it is low
  (`y < 1.6 h`, not only when slow) and is stronger (`SPHERE_DRAG` 0.98 per step), so it stops within a few seconds. The 5 s limit still applies.
- **Reading:** at rest the face most up is read as usual, but the ball is never flat on it, so `finishRoll` always runs the 0.35 s `fix` tween (`tiltFix`)
  that tips the ball onto that nearest face (and sinks it to `h`). Then the usual yaw turn / lift follows. Forced throws end on the target: the relabel already put the target
  face where the landed face is, so the tween levels exactly that face.
- **Land on:** any rotation is a symmetry of a sphere, so `symmetryFor(faces, from, to, true)` returns the shortest-arc rotation (3x3 row-major, Rodrigues; half a turn about
  an axis square to the normal for exactly opposite faces) taking `faces[from].normal` onto `faces[to].normal`. No group is built from the 100 normals (`symsFor` is not called for the ball; `dice.selfTest()` reports `syms: 'any'`).
- **Lift:** the ball grows to 1.8x when lifted (`lift` in `DICE`).
- **UI:** the tally panel and the Land on select get 100 rows/options (the panel scrolls inside). `dice.sphere` tells tests which mode the first die uses.

## Adding a die

1. Export `dice/models/<name>.glb` (circumradius 0.5, Y-up) and `dice/models/<name>.faces.json` (see `faces-json.md`): `die`, optional `read`, `faces` (one per face, with
   `number`, `normal`, and `up` for face dice or `front` for vertex dice, optional `value` shown instead of `number`) and `hull` (sharp polyhedron, see above).
2. Add `<name>: { scale }` (optional `label`, `lift`, `file` when the file name differs from the key) to `DICE` and an entry to `KINDS`
   (`{ dice: [<name>], sides }`; the panel, picker and tally are built from it) in `main.js`, and `dice/icons/<kind>.webp` (128x128, transparent) for its panel row. That is all the code a new die needs. A ball also sets `"physics": "sphere"` in its `faces.json` (above).
3. Bump `MODEL_V` in `main.js`. Check with `dice.selfTest()` (0 mismatches, `hist` over all faces, `syms` as expected) and a Land on run per face.

## Test hooks (`window.dice`)

`setDie(kind)` / `setHand([...kinds])` (promise, idle only), `throwTo(value, seed)` (one die, Land on), `throwHand(seed, serverRoll)` (whole handful;
`fast = true` finishes synchronously), `last` (the roll: `seed`, `forced`, `matched`, `total`, `entries[{ kind, value, parts }]`,
`dice[{ kind, name, target, want, predicted, matched, face, value, yaw }]`, `server`, `ok` = every forced die shows its wanted value),
`selfTest(n)` (current handful: same throw twice -> same bits; for several dice `syms` and `hist` are per die), `hand`, `die`, `pose()` (first die plus `dice[]`),
`h`/`tip`/`sphere`/`hull` (first die), `tex` (tier key `'full'|'high'|'light'`) / `setTex(t)` (promise<boolean>; same path as the Textures button, idle only), `tally`, `resetTally(all)`, `lift`, `state`, `trace`, `breakReplay`.
`hand2` drives the hand box with screen coordinates (px), through the same functions as the pointer events: `start(x, y)` (true when scooped; false and a note for Server roll / Land on, or when not idle), `move(x, y)`, `end()` (release with the flick, the throw starts), `info()` (box position, size, dice positions in the hand world, or null). `state` is `'holding'` in between; the hand world advances in the frame loop, so wait frames between the calls.

## Vendored libraries

See `THIRD_PARTY_NOTICES.md` for versions and licences. The folder layout under `vendor/three/` mirrors the npm package, so GLTFLoader's relative imports work; the importmap in `index.html` maps `three`, `three/addons/` and `cannon-es`.

## Known limits

- Frame times were only measured with software WebGL (SwiftShader) in a headless browser; real GPUs and phones are not benchmarked.
- If Lift result is switched off while a result is waiting to lift, the die stays as it landed (the on-table turn only runs right after a throw).
- Touch input is implemented with pointer events but has not been tried on a real touchscreen.
- The d100 ball's rolling behaviour (drag 0.98, rest time) is tuned by eye and may need adjusting for other tables.
- The hand box (collisions of hull dice with its thin boxes, feel on touch, sizes) has had little testing outside automated checks.
- A lifted row of many dice on a phone is shrunk to fit the screen width, so 10 dice show small.
- **Cocked dice (owner choice 08/11/2026):** a die rests when it has been still or calm for 0.5 s, flat or not. A die
  leaning on a wall or on another die stays cocked as it froze and is read by its face closest to up (`faceUp`), as at a
  real table; there is no hop any more. A flat die that keeps trembling in a jam counts as resting after 0.75 s of
  near-stillness (`QUIET_REST`), and a flat, nearly still die gets rest friction (`SETTLE` 0.92 per step). After 5 s
  (`MAX_STEPS`) every die is frozen where it is. Forced results still land exactly: the hidden run and the replay
  freeze at the same step, and the target is relabelled onto the face closest to up. `window.dice.bench(n, 'free'|'hand')`
  measures settle times (simulated seconds, throws with cocked dice, throws hitting the limit).
- Rolls are decided in the browser in this demo. In a real tabletop a server or game master can decide the result and this method only relabels (see `faces-json.md`).
