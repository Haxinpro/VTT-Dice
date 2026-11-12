# Integrating the dice in your virtual tabletop

This guide is for developers who want to use the dice in their own virtual
tabletop (VTT). The dice come as 3D models (`.glb`) with a data file
(`.faces.json`) that tells your code which face is which. The demo in this
repository (`index.html`, `main.js`, `physics.js`) is a complete worked example;
the sections below explain the data so you can use it with any engine.

If you only need pictures (2D), use the stills in `dice/results/` instead, see
the end of this file.

## What is in `dice/`

```
dice/models/<die>.glb          the 3D model
dice/models/<die>.faces.json   what each face means, plus a physics hull
dice/models/high/, light/       the same models with 1024 px / 512 px textures (phones, weaker GPUs; the demo uses the full set)
dice/icons/<kind>.webp         128 x 128 icons (transparent) for a dice picker
dice/results/<die>/<value>.webp  512 x 512 stills of a die showing <value>
```

`<die>` is one of `d4 d6 d8 d10 d10t d12 d20 d100`:

- `d10t` is the tens die of a percentile pair (faces `00 10 ... 90`).
- `d100` is a single 100-face ball (physics shape: a sphere).
- A "d100 pair" in the demo is one `d10t` plus one `d10`.

## The `.glb` file

- glTF 2.0, binary. **Y is up** (glTF convention). Units: the circumradius of
  the sharp (unbevelled) polyhedron is **0.5**, so every die has a similar size.
  Scale it to what your table needs; the demo draws them at 0.76 to 1.1.
- The die is centred on the origin, with one mesh and **two materials**:
  - `body`: the marble (a base colour texture and a roughness texture,
    both baked, JPEG inside the file);
  - `numbers`: the engraved digits, one flat gold material (colour
    `0.96, 0.68, 0.20`, metallic 0.7, roughness 0.35).
- The file's `asset.copyright` and `asset.extras` (licence, source) say who made it and under which licence, and a tiny
  "Haxinpro" is cut as tiny letters into a side wall of the recess of the digit 1 (tens die: the 1 of 10; gold, part of the `numbers` material). Keep
  both when you convert or re-export the model, as the licence asks for credit.
- Because the materials are separate you can re-colour the digits or the body
  from code by name (for example `material.name === 'numbers'`) without touching
  the textures.
- Bevelled corners stop slightly short of the sharp polyhedron, so the farthest
  vertex is a little below 0.5 (for example about 0.435 for the d4). The
  physics `hull` below is the sharp shape; trim its corners if you want dice
  to rest cleanly (the demo does, see `trim` in `physics.js`).

## The `.faces.json` file

Top level fields:

| Field | Meaning |
| --- | --- |
| `die` | Name of the die, same as the file name stem. |
| `read` | How a result is read: `"face"` (the face pointing up) or `"vertex"` (the corner pointing up; only the d4). Missing means `"face"`. |
| `axes` | Always `"gltf Y-up"`: all vectors in this file are in the model's own space with the glTF axes. |
| `mirror` | `false` for the shipped models. A mirrored build has the opposite handedness of the numbering (see `tools/README.md`). |
| `faces` | One entry per face (per corner for the d4), see below. |
| `hull` | `{ "verts": [[x,y,z],...], "faces": [[i,j,k,...],...] }`: the sharp polyhedron, for a physics engine. Vertices are in model units (circumradius 0.5), each face lists vertex indices in cyclic order. Faces may have winding in either direction, so re-wind them outward in your engine if it needs that. |
| `physics` | Only present on the 100-face ball: `"sphere"`. Use a sphere collider of radius `h` (centre-to-face distance) instead of the hull. |

Each entry of `faces`:

| Field | Meaning |
| --- | --- |
| `number` | The number printed on this face (d4: the number at this corner; d10: `0..9`; d10t: `0..9`, meaning tens `00..90`). |
| `normal` | Unit vector, outward from the die centre. For `read: "face"` it is the face normal; for `read: "vertex"` (d4) it points to the corner. |
| `up` | (face dice) Unit vector along the printed digit's "up" direction, lying in the face plane. Use it to turn the die so the digit reads upright. |
| `front` | (d4 only) In the show pose, the direction that faces the camera when this corner is the top. The d4 has no readable "up" direction, so `front` replaces `up`. |
| `value` | Optional. The value this face counts as, when it differs from `number`: d10 face `0` has `value: 10`; d10t faces have `value: 0, 10 ... 90`. If missing, the value is `number`. |
| `text` | Optional. What is printed, when it differs from `number` (d10t prints `"00"`, `"10"` ... `"90"`). |

The six, eight, ten, twelve and twenty-sided dice, and the ball, have exactly
that many `faces` entries; the d4 has four (one per corner).

## Reading a result

Rest the die (your physics engine, or anything else), then:

1. For each entry in `faces`, rotate `normal` by the die's current rotation
   (the quaternion of the object) to get a world-space direction.
2. The entry whose world normal points **most up** (largest `y` in a Y-up
   world, largest dot product with the up vector) is the result.
3. The result is `value ?? number`.

Special cases:

- **d4** (`read: "vertex"`): the die lies on a face; the result is the **corner
  pointing up**. The same rule works: `normal` is the corner direction, take
  the largest. The die rests on the opposite face (outward normal `-normal`).
- **d10**: the face numbered `0` reads **10** (its `value` is 10).
- **Percentile (d100 pair)**: result = `d10t.value` + `d10.number` (use
  `number`, not `value`, for the ones die), and `00 + 0` means **100**. For
  example tens `30` with ones `7` is 37; tens `00` with ones `0` is 100.
- **d100 ball**: a normal face die with 100 faces; the result is the face most
  up. It never rests flat on a face by itself, so nudge or ease it onto the
  nearest face if you need a flat result (the demo tips it with a 0.35 s tween).

A die that is nearly but not exactly flat (the demo accepts 6 degrees) can be
treated as at rest; the nearest face is still the answer.

## Forcing a result

If a server or game master decides the result, you can still let the dice
roll physically and end on the decided number. The trick: simulate, then relabel
by a symmetry.

1. Run your physics for the throw (same start values) and read which face
   lands up, call it `L` (a face index).
2. The wanted face is `W`. Find a rotation `R` that maps the **set of face
   normals onto itself** (a rotation symmetry of the die) and sends
   `faces[L].normal` to `faces[W].normal`. Every regular die has several (a
   cube has 24, a d20 has 60). Among the candidates, prefer the one that keeps
   `up` (or `front` for the d4) closest to where it was, so the digit does not
   spin.
3. Turn the **mesh** by `R` inside the physics body (for example the render
   object's local rotation relative to the body). Do not change the physics
   shape: it is symmetric, so the trajectory does not change, but the face
   that was `L` is now the face `W`.
4. Replay the very same throw visibly. The die ends on `W` because the face
   that would have landed up is now `W`.

Do the turn while the die cannot be seen (before the first frame, or throw it
from outside the camera view) or the digits would visibly jump. The demo does
this and checks that the replay matches (same fixed time step, same body order
and start values give the same result); if it does not, it tweens the die onto
the wanted face as a safety net.

**How to find `R`** from `faces[].normal` alone: take two reference normals
`a` (the first face) and `b` (the first not parallel to it). For each ordered
pair `(c, d)` of normals with the same angle between them as `(a, b)`, build
the rotation that sends `a` to `c` and `b` to `d`; keep it if every normal
lands on a normal (dot product above 0.999). The demo's `symsFor` does this in
`physics.js`, and the group sizes are: d4 12, d6 24, d8 24, d10 10, d12 60,
d20 60.

**Sphere variant (the ball, `physics: "sphere"`)**: every rotation is a symmetry
of a sphere, so no group is needed. Use the shortest-arc rotation that sends
`faces[L].normal` to `faces[W].normal` (about their cross product; for exactly
opposite normals, half a turn about any axis perpendicular to the normal). In
other words: point the target face at the final up.

## Numbering layouts (for checking your integration)

Opposite faces add up to a constant on every die except the d4:

| Die | Opposite faces add to | Layout |
| --- | --- | --- |
| d4 | - | Each face shows the three numbers of its corners; the result is the top corner. |
| d6 | 7 | Western: 1, 2, 3 run counter-clockwise round their shared corner. |
| d8 | 9 | Opposite faces add to 9. |
| d10 | 9 | Pentagonal trapezohedron, digits 0-9. Around the even pole the faces read **2-8-0-4-6** by increasing azimuth; the other pole follows by opposites. Face `0` counts as 10. |
| d10t | 9 (in tens: 90) | Same shape and layout as the d10, printed `00 10 ... 90`. |
| d12 | 13 | Round the 12 face, the five neighbours read **9 11 10 8 7** (clockwise seen from above the 12 face); the lower ring is the opposites. |
| d20 | 21 | Standard layout: the 20 touches 2, 8 and 14. |
| d100 ball | 101 | 100 small flat faces. |

You can verify the opposite sums in code: for every pair of faces whose normals
are opposite (dot product below -0.999), the `number`s add up to the constant.

**6 and 9** are underlined on every die, so they cannot be mistaken for each
other when read upside down. (On the d10t the tens faces carry no underline.)

## Physics hints

- The `hull` is the sharp polyhedron. A bevelled model would prop itself on
  invisible sharp tips, so cut each hull corner farther out than the model's
  real tip (measure the farthest vertex in the mesh) by a plane square to its
  direction. The demo's `trim` does that.
- `h` (centre-to-face distance) can be measured from the mesh: per face, the
  farthest vertex along the face normal, averaged. A resting die's centre is at
  height `h`.
- The demo's world step is fixed (1/120 s). A forced result needs the hidden
  run and the visible replay to use the same step; a variable step breaks it.

## 2D alternative: the result stills

`dice/results/<die>/<value>.webp` are 512 x 512 WebP pictures with transparent
background, one for each shown value:

```
d4/1..4   d6/1..6   d8/1..8   d10/0..9   d10t/00..90   d12/1..12   d20/1..20
d100/1..100   (the ball, seen from straight above: the rolled number in the centre)
```

The file name is the value as printed. Examples: `dice/results/d20/17.webp`,
`dice/results/d10t/30.webp`. For a percentile roll show a `d10t` still and a
`d10` still side by side. If you only need a number to show, no 3D is required.
