# Tools: regenerate the models and pictures

`dice3d.py` builds the dice and renders them. It runs inside **Blender 5.2**
(headless) using Blender's Python API and Cycles; it is not a normal Python
script. It is licensed GPL-3.0-or-later (see `LICENSE` in this folder).

It makes:

- the web models: `<die>.glb` and `<die>.faces.json` (what goes into
  `dice/models/`);
- the still pictures: a PNG of a die showing a chosen value (the source of the
  WebP files in `dice/results/`).

Needs: Blender 5.2 (`blender` on your PATH), and a bold sans font. The script
looks for `/usr/share/fonts/noto/NotoSans-Bold.ttf`, then Fira Sans SemiBold,
then DejaVu Sans Bold; pass `--font <file>` for another one.

Always cap the threads (`-t 8`) so the machine stays responsive. Run these from
the repository root.

## Commands

```
# Web model + face data (no render)
blender -b -t 8 -P tools/dice3d.py -- --die d20 --glb dice/models/d20.glb

# Only the .faces.json (no scene, font, render or bake; quick)
blender -b -t 8 -P tools/dice3d.py -- --die d10 --faces dice/models/d10.faces.json

# One still picture showing a value
blender -b -t 8 -P tools/dice3d.py -- --die d20 --result 17 --out d20_17.png --res 1024 --samples 128

# Percentile tens die: --result is the d10 digit, 7 shows "70"
blender -b -t 8 -P tools/dice3d.py -- --die d10t --result 7 --out d10t_70.png

# A batch in one Blender run (the die is built once): {n} = the printed value
blender -b -t 8 -P tools/dice3d.py -- --die d100 --results 1-20 --out ball_{n}.png --res 1024 --samples 128

# The d4: pose of the camera view
blender -b -t 8 -P tools/dice3d.py -- --die d4 --result 2 --out d4_2.png --pose edge --tilt 25
```

The pictures in `dice/results/` are the PNG renders converted to 512 x 512 WebP
with transparency (ImageMagick: `magick in.png -resize 512x512 -quality 90 out.webp`).
After re-exporting a model, bump `MODEL_V` in `main.js` so browsers do not use
a cached copy.

## Options

`--die` is one of `d4 d6 d8 d10 d10t d12 d20 d100`.

| Option | Meaning |
| --- | --- |
| `--die` | Which die to build. |
| `--result N` | The face to show in a still: its number. For `d10` the digit 0-9; for `d10t` the d10 digit, so `3` shows "30" and `0` shows "00". |
| `--out FILE.png` | Render a still here (square PNG, transparent background). Skipped when empty. With `--results`, `{n}` in the name becomes each face's printed value. |
| `--results LIST` | Batch: several stills in one run, `1-20`, `0-9`, `1,5,9` or `all`. Much faster than one run per value. |
| `--res` | Still size in pixels (default 1024). |
| `--samples` | Cycles samples, more is cleaner and slower (default 128). |
| `--seed` | Varies the marble veins (default 1). |
| `--tilt DEG` | How far the rolled face leans back: positive shows the face below it, negative looks down from above (default: the die's own, else 2). |
| `--yaw DEG` | For dice shown from the top (the d6): how far the view turns off the digit. |
| `--pose edge\|face` | The d4 only: what faces the camera, an edge or a face. |
| `--lens MM` | Camera focal length (default 250; shorter means more perspective). |
| `--fill` | Die size as a share of the canvas (default 0.80). |
| `--font FILE` | Font file for the digits. |
| `--mirror` | Opposite handedness of the numbering (d8: 7 right and 5 left of the 1; d4: corners 3 and 4 swap; d6: faces 2 and 5 swap; d10, d12: numbered by mirrored azimuth; d20: 8, 2, 14 counter-clockwise round the 20; d100: no mirror variant). |
| `--faces FILE` | Write only the `.faces.json` here and exit. |
| `--glb FILE` | Export a web-ready `.glb` (and the matching `.faces.json` next to it) with baked textures. |
| `--tex N` | Baked texture size for `--glb` (default 2048). |
| `--max-tris N` | Decimate the `--glb` model above this triangle count (default 20000; a die's own limit wins, the d100 ball uses 80000). |
| `--digit-res N` | Segments per curve piece of the digits (default: the die's own, else `DIGIT_RES` = 4; it was 10). |
| `--bevel-seg N` | Segments across the rounded edges (default: the die's own, else `BEVEL_SEGMENTS` = 3; it was 6). |
| `--groove-sides N` | d100: sides of the groove cutter (default `GROOVE_SIDES` = 6; it was 12). |
| `--no-beauty` | `--glb`: do not re-triangulate the flat regions with beauty (Blender's default triangles). |
| `--no-frames` | Do not split the faces into frames round the numbers first (the old triangulation around the digits). |
| `--drop-hidden` | `--glb`: drop the gold fill walls and bottoms and the cut floors. Smaller, but the caps then touch the walls without shared points (open edges in the visible strip), so it is off by default. |
| `--no-mark` | Do not cut the maker's mark (see below). By default the mark is on. |
| `--blend FILE` | Also save the finished scene as a `.blend` to open in Blender. |
| `--device auto\|cpu\|gpu` | Cycles device. `auto` (default) tries NVIDIA OptiX, then CUDA, else the CPU; `cpu` forces the CPU. On an RTX 3080 Ti the 100 ball stills took about 12 min with OptiX. |

## Triangle budget

The `--glb` export prints `triangles before decimation: N (limit M, UNDER|OVER)` and then `decimate: skipped` or `decimate: ran`.
The goal is UNDER on every die, so the mesh keeps its clean topology. The levers are named constants (`DIGIT_RES`,
`BEVEL_SEGMENTS`, `GROOVE_SIDES`, and the d100's own `digit_res` / `bevel_segments` in `DICE`). The export also drops geometry
that cannot be seen: the gold fills' side walls and bottoms (they lie on the gold wall of the cut) and the floors of the cuts
(under the fill). The export also re-triangulates the flat regions (stone round the numbers, gold tops of the digits) with the beauty method and
flips edges until the triangles are evenly spaced; the log prints `flat regions: N triangles, long-thin A -> B, worst ratio ...`.
Before the numbers are cut, every face is split into a frame round each label (one cell per digit, `FRAME_MARGIN`) and a
triangle fill to the face outline, so the cut leaves short, well-shaped triangles instead of long fans to the face corners; the log
prints `framed faces: N of M`. Compare with the old build by adding `--digit-res 10 --bevel-seg 6 --groove-sides 12`.

## Maker's mark and metadata

- **Mark**: unless `--no-mark` is given, the text "Haxinpro" is cut into the right-hand side wall of the stem of the digit 1,
  at the same spot on every die: the 1 on the d4, d6, d8, d10, d12, d20 and the d100 ball, and on the tens die the 1 of "10"
  (on the d4, the 1 on the face with corners 1, 2, 3). It is real mesh geometry in the gold wall, tiny and facing sideways:
  `MARK_LENGTH` (0.0368 of the digit height, 0.0085 on the d20), `MARK_DEPTH` (2e-4), centred along the stem and in the
  visible wall above the gold fill. It is invisible in play and in ordinary pictures and shows only when you look straight
  into the recess wall from very close. In a `--glb` export the decimation leaves the wall piece alone, and the export stops
  with an error if the mark is missing from the model or the file is compressed or quantized (the export is plain float
  positions). Before the cut the wall is split into a small frame round the text box (`MARK_FRAME`), cut into one cell per letter, and
  triangles to the wall's corners, so each letter connects only to its own cell and not to the far ends of the wall; the log shows the triangles this uses.
  Size: a d20 is about 1 unit (metre in glTF) across, so the text is about 4 mm long and 1 mm high. In Blender it shows
  when you zoom in close; the viewport's default clip start is 0.01 (10 mm), so look from just beyond that, where the text
  fills about half the view.
- **Flat faces**: a `--glb` export makes the flat stone polygons shade flat (custom normals, sharp edges at the bevel) and
  prints `flat faces: N polygons, shading lean max A -> B deg`; B should be about 0.
- **glTF metadata**: every `--glb` export gets `asset.copyright` ("(c) Haxinpro") and `asset.extras` (`licence`, and
  `source` once `REPO_URL` in the script is set) written into the file's JSON chunk. The binary data is not touched.
- **WebP metadata**: `stamp_xmp.py` (standard library only, no Blender) adds XMP (creator, rights, licence URL) to
  WebP files in place; running it again replaces the old XMP:

```
python3 tools/stamp_xmp.py dice/results/d20/*.webp dice/icons/*.webp
```

## Lighter texture sets (high, light)

`glb_tiers.py` makes smaller copies of the models for phones and weaker GPUs: `dice/models/high/` with 1024 px textures and
`dice/models/light/` with 512 px textures (the full set in `dice/models/` has 2048 px). The meshes, the `.faces.json` files and
the `asset` metadata (copyright, extras) are the same as in the full set; only the two embedded textures of each die are
scaled down. It needs Pillow (`pip install pillow`, or the distro package) and no Blender. Run it from the repository root
after every model re-export:

```
python3 tools/glb_tiers.py dice/models --size 1024 --out dice/models/high
python3 tools/glb_tiers.py dice/models --size 512  --out dice/models/light
```

Each output file is read back and compared with its source before the next one starts.

## Adding a die

The dice are plain data in the `DICE` table of `dice3d.py` (vertices, faces,
numbers, an "up" vertex per face, digit size, bevel, view). A new die is one more
table entry. Export it with `--glb`, then add it to `DICE` and `KINDS` in
`main.js` and an icon to `dice/icons/` to show it in the demo.

**Note (10/11/2026):** the shipped `dice/models/d100.glb` is the build from commit 7147cf2 (old digit, bevel and groove settings, decimated to 80000). The optimized ball settings in `DICE["d100"]` still produce sliver triangles in the grooves, so the ball is not re-exported until that is fixed. All other dice are `--glb` exports of this script.
