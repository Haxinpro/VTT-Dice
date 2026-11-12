# Third-party notices

| Component | Version | Licence | Where |
| --- | --- | --- | --- |
| three.js | r186 (npm 0.186.1) | MIT | `vendor/three/` (licence: `vendor/three/LICENSE`) |
| cannon-es | 0.20.0 | MIT | `vendor/cannon-es/` (licence: `vendor/cannon-es/LICENSE`) |
| Noto Sans Bold | - | SIL Open Font License 1.1 | letter shapes only, see below |
| Blender | 5.2 | GPL (used as a tool) | not distributed |

## three.js

Copyright 2010-2026 three.js authors, MIT licence. Only the files the demo
needs are included: `build/three.module.js`, `build/three.core.js`,
`examples/jsm/loaders/GLTFLoader.js`, `examples/jsm/utils/BufferGeometryUtils.js`
and `examples/jsm/utils/SkeletonUtils.js`. The folder layout mirrors the npm
package so the loader's relative imports work.

## cannon-es

Copyright (c) 2015 cannon.js authors (derived from cannon.js), MIT licence.
Included as `dist/cannon-es.js`, renamed `cannon-es.js`.

## Noto Sans Bold

The digits on the dice are engraved using the letter shapes of Noto Sans Bold
(Copyright The Noto Project Authors, SIL Open Font License 1.1,
https://openfontlicense.org). The shapes are part of the models and pictures in
`dice/`. The font file itself is not distributed in this repository.

## Blender

`tools/dice3d.py` runs inside Blender (https://www.blender.org) and uses its
Python API; because of that the script is licensed GPL-3.0-or-later. Blender is
a tool and is not distributed here. The files it produces (models, pictures)
belong to the person who runs it; the ones in `dice/` are licensed as stated in
`LICENSE-ASSETS.md`.
