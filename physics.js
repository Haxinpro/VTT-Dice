// physics.js - dice physics (any convex dice, several in one world) with cannon-es only (no DOM, no three.js), so the very
// same code can run hidden ("headless") for the simulate-then-turn trick and visibly for the replay.
// A die is described by { h, faces, hullDef, tip, sphere }: h = centre-to-face distance, faces = faces.json entries,
// hullDef = { verts, faces } = faces.json "hull" (sharp polyhedron) already times the visual scale, tip = corner trim reach.
// `sphere` (faces.json "physics": "sphere", the d100 ball) swaps the hull for a CANNON.Sphere(h) and changes rest detection.
import * as CANNON from 'cannon-es';

export const DT = 1 / 120;            // fixed physics step; the page runs two per 60 Hz frame
export const HALF_Z = 3.4;            // table inner half-DEPTH (z), in die-units (die ~0.9 wide); dice are drawn smaller than 1 on the table
export const HALF_X_MIN = 3.4, HALF_X_MAX = 6.1;   // the inner half-WIDTH (x) is chosen by the page between these (wide screens: a wider table)
// The table the NEXT world is built for. main.js sets it with setTable while idle; makeSim copies it into the sim, so one throw
// (hidden run and replay) always uses one table even if this changes later.
let table = { hx: HALF_Z, hz: HALF_Z };
export function setTable(hx, hz = HALF_Z) { table = { hx, hz }; }
export const getTable = () => ({ ...table });
const GRAVITY = 55;                   // scaled up: the die is "small", so it should fall fast
const REST_STEPS = 60;                // 60 calm steps at 120 Hz = 0.5 s of rest
export const MAX_STEPS = 120 * 5;     // time limit: after 5 s of simulated time every die is frozen where it is
const REST_V = 0.05, REST_W = 0.12;   // "calm" = linear < 0.05 u/s and angular < 0.12 rad/s
const ROLL_DRAG = 0.985;              // per step while low and slow (~84 % of the spin gone after 1 s)
const SPHERE_DRAG = 0.98;             // sphere (d100 ball): whenever low, a bit stronger (~91 % gone after 1 s), so it stops in a few seconds
const RAMP = 0.3;                     // width of the invisible 45 deg ramp at each wall's foot
const SETTLE = 0.92;                  // rest friction per step for a flat, nearly still die (see settle)
const QUIET_REST = 90;                // 0.75 s of near-stillness while flat counts as rest
export const FLAT = Math.cos(6 * Math.PI / 180);   // a face this close to +Y (within 6 deg) = flat; a die resting less flat is "tilted" (cocked)

// Small seeded PRNG (mulberry32): same seed -> same numbers, in every browser.
export function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Rotate vector v=[x,y,z] by quaternion q={x,y,z,w} (same maths as three.js applyQuaternion).
export function rot(q, v) {
  const [x, y, z] = v;
  const ix = q.w * x + q.y * z - q.z * y, iy = q.w * y + q.z * x - q.x * z;
  const iz = q.w * z + q.x * y - q.y * x, iw = -q.x * x - q.y * y - q.z * z;
  return [ix * q.w - iw * q.x - iy * q.z + iz * q.y,
          iy * q.w - iw * q.y - iz * q.x + ix * q.z,
          iz * q.w - iw * q.z - ix * q.y + iy * q.x];
}

// Index of the face whose world-space normal points most upward, plus how upward (1 = flat).
// d4: the "normal" is the corner direction, so this finds the top corner (the d4 reads at its top).
export function faceUp(q, faces) {
  let best = 0, bestY = -2;
  faces.forEach((f, i) => { const y = rot(q, f.normal)[1]; if (y > bestY) { bestY = y; best = i; } });
  return { index: best, dot: bestY };
}

const mul = (m, v) => [0, 1, 2].map((i) => m[i*3]*v[0] + m[i*3+1]*v[1] + m[i*3+2]*v[2]);
const dot = (a, b) => a[0]*b[0] + a[1]*b[1] + a[2]*b[2];
const cross = (a, b) => [a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0]];
const unit = (v) => { const l = Math.hypot(...v); return v.map((x) => x / l); };

// Right-handed orthonormal frame [e1, e2, e3] from two non-parallel unit vectors: e1 = a, e2 = b made square to a.
const frame = (a, b) => { const e2 = unit(b.map((x, i) => x - dot(b, a) * a[i])); return [a, e2, cross(a, e2)]; };

// Per die: all rotations (3x3 row-major, det +1) that map the set of faces[].normal onto itself; only these may
// "relabel" (the physics shape is identical after them). Counts: d4 12, d6 24, d8 24, d10 10, d12 60, d20 60.
// Any rotation is fixed by where two non-parallel normals go: try every (c, d) with the same angle as (a, b),
// build R = F(c,d) * F(a,b)^T, keep it when all normals land on a normal. Cached per faces array.
const symCache = new WeakMap();
export function symsFor(faces) {                                // not for spheres (100 near-equal normals): see symmetryFor
  let out = symCache.get(faces);
  if (out) return out;
  out = [];
  const ns = faces.map((f) => unit(f.normal)), a = ns[0];
  const b = ns.find((n) => Math.hypot(...cross(a, n)) > 1e-6), ab = dot(a, b), Fab = frame(a, b);
  for (const c of ns) for (const d of ns) {
    if (Math.abs(dot(c, d) - ab) > 1e-4) continue;
    const Fcd = frame(c, d), R = [];
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) R.push(Fcd[0][i]*Fab[0][j] + Fcd[1][i]*Fab[1][j] + Fcd[2][i]*Fab[2][j]);
    if (!ns.every((n) => { const m = mul(R, n); return ns.some((g) => dot(m, g) > 0.999); })) continue;
    if (!out.some((o) => o.every((x, k) => Math.abs(x - R[k]) < 1e-6))) out.push(R);
  }
  symCache.set(faces, out);
  return out;
}

// Row-major 3x3 rotation S with S*normal(from) = normal(to), chosen among the candidates so the
// numeral's "up" (d4: "front") direction also lands as close as possible. Mesh = bodyRotation * S.
// Sphere: every rotation is a symmetry, so take the shortest-arc turn normal(from) -> normal(to) (cheap, deterministic).
export function symmetryFor(faces, from, to, sphere = false) {
  if (sphere) return arc(faces[from].normal, faces[to].normal);
  const key = (f) => f.up ?? f.front;                           // none -> every candidate ties, first wins
  let best = null, bestUp = -9;
  for (const m of symsFor(faces)) {
    if (dot(mul(m, faces[from].normal), faces[to].normal) < 0.99) continue;
    const k = key(faces[from]), u = k ? dot(mul(m, k), key(faces[to])) : 0;
    if (u > bestUp) { bestUp = u; best = m; }
  }
  return best;
}

// Shortest-arc rotation (3x3 row-major) taking direction a onto b: Rodrigues, R = I + [v]x + [v]x^2 / (1 + c), v = a x b, c = a.b.
// Opposite directions (c ~ -1): half a turn about any axis square to a.
export function arc(a, b) {
  a = unit(a); b = unit(b);
  const c = dot(a, b);
  if (c < -0.999999) {
    const t = Math.abs(a[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0], k = unit(cross(a, t)), I = [1, 0, 0, 0, 1, 0, 0, 0, 1];
    return I.map((x, i) => x * -1 + 2 * k[Math.floor(i / 3)] * k[i % 3]);     // 2kk^T - I
  }
  const [x, y, z] = cross(a, b), s = 1 / (1 + c);
  return [1 - (y*y + z*z) * s, -z + x*y * s, y + x*z * s,
          z + x*y * s, 1 - (x*x + z*z) * s, -x + y*z * s,
          -y + x*z * s, x + y*z * s, 1 - (x*x + y*y) * s];
}

// Convex hull from vertices [[x,y,z]..] and index lists; every face is re-wound to point away from the origin
// (the die centre), checked with the face centroid. Works for triangles and planar convex quads. Use hullShape for dice (cached).
function hull(verts, idx) {
  const vertices = verts.map(([x, y, z]) => new CANNON.Vec3(x, y, z));
  const faces = idx.map((f) => {
    const [a, b, c] = f.map((i) => vertices[i]);
    const n = b.vsub(a).cross(c.vsub(a));                       // winding check
    const sum = f.reduce((s, i) => s.vadd(vertices[i]), new CANNON.Vec3());   // centroid * count
    return n.dot(sum) < 0 ? f.slice().reverse() : f.slice();
  });
  return new CANNON.ConvexPolyhedron({ vertices, faces });
}

// Cut every corner that reaches farther than `tip` from the centre with a plane square to that corner's direction
// (the die's bevels, so it cannot prop itself on invisible tips). Faces keep their cyclic order; a cut corner becomes
// two edge points, and each cut corner gets a cap face. Returns [verts, idx] for hull(). Corners within tip stay.
export function trim(verts, idx, tip) {
  const len = (v) => Math.hypot(v[0], v[1], v[2]), cut = verts.map((v) => len(v) > tip);
  if (!cut.some(Boolean)) return [verts, idx];
  const out = [], at = new Map(), nb = new Map();                // new vertices, key -> index, cut corner -> its neighbours
  const add = (key, p) => { if (!at.has(key)) { at.set(key, out.length); out.push(p); } return at.get(key); };
  const edge = (v, w) => {                                       // point on edge v->w where the cut plane of v crosses it
    const a = len(verts[v]), d = verts[v].map((x) => x / a), s = (a - tip) / (a - dot(d, verts[w]));
    return add(`${v}>${w}`, verts[v].map((x, k) => x + (verts[w][k] - x) * s));
  };
  const faces = idx.map((f) => f.flatMap((v, k) => {
    if (!cut[v]) return [add('v' + v, verts[v])];
    const prev = f[(k + f.length - 1) % f.length], next = f[(k + 1) % f.length];
    nb.set(v, (nb.get(v) ?? new Set()).add(prev).add(next));
    return [edge(v, prev), edge(v, next)];                       // along the face: prev side first, then next side
  }));
  for (const [v, ws] of nb) {                                    // cap: the corner's edge points, ordered by angle around d
    const a = len(verts[v]), d = verts[v].map((x) => x / a);
    const t = Math.abs(d[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];      // any axis not parallel to d
    const u0 = [d[1]*t[2] - d[2]*t[1], d[2]*t[0] - d[0]*t[2], d[0]*t[1] - d[1]*t[0]], ul = len(u0), u = u0.map((x) => x / ul);
    const w = [d[1]*u[2] - d[2]*u[1], d[2]*u[0] - d[0]*u[2], d[0]*u[1] - d[1]*u[0]];   // (u, w, d) = right-handed basis
    const ang = (i) => Math.atan2(dot(out[i], w), dot(out[i], u));
    faces.push([...ws].map((x) => at.get(`${v}>${x}`)).sort((i, j) => ang(i) - ang(j)));
  }
  return [out, faces];
}

// Trimmed hull of a hullDef at `tip`, cached per (hullDef object, tip): trimming, winding and the unique axes are done once,
// every call (hidden run, replay, selfTest) gets a NEW ConvexPolyhedron from the cached arrays, so no shape is shared
// between worlds. `axes` = face normals without antiparallel/parallel duplicates (dot > 0.999): cannon's SAT then tests
// half the directions on a d6/d12/d20. Do not mutate hullDef after its first use (the cache would go stale).
const hullCache = new WeakMap();
function hullShape(def, tip) {
  let byTip = hullCache.get(def);
  if (!byTip) hullCache.set(def, byTip = new Map());
  let d = byTip.get(tip);
  if (!d) {
    const s = hull(...trim(def.verts, def.faces, tip)), axes = [];
    for (const n of s.faceNormals) if (!axes.some((a) => Math.abs(a.dot(n)) > 0.999)) axes.push(n.clone());
    byTip.set(tip, d = { v: s.vertices.map(({ x, y, z }) => [x, y, z]), f: s.faces, a: axes });
  }
  return new CANNON.ConvexPolyhedron({ vertices: d.v.map(([x, y, z]) => new CANNON.Vec3(x, y, z)), faces: d.f.map((f) => f.slice()), axes: d.a.map((a) => a.clone()) });
}

// A world with gravity and the three contact materials (felt, wood rim, die), as makeSim and makeHand both need them.
function newWorld() {
  const world = new CANNON.World({ gravity: new CANNON.Vec3(0, -GRAVITY, 0) });
  world.broadphase = new CANNON.NaiveBroadphase();
  world.solver.iterations = 14;
  world.allowSleep = false;                                     // we detect rest ourselves

  const felt = new CANNON.Material('felt'), wood = new CANNON.Material('wood'), die = new CANNON.Material('die');
  // Felt: grippy and dead (low bounce). Wood rim: livelier, slippery. Die on die: a hard knock, some slip.
  world.addContactMaterial(new CANNON.ContactMaterial(die, felt, { friction: 0.5, restitution: 0.22 }));
  world.addContactMaterial(new CANNON.ContactMaterial(die, wood, { friction: 0.2, restitution: 0.45 }));
  world.addContactMaterial(new CANNON.ContactMaterial(die, die, { friction: 0.1, restitution: 0.35 }));   // slippery: a die leaning on a die slides down
  return { world, felt, wood, die };
}

const reach = (d) => (Number.isFinite(d.tip) ? d.tip : d.h);                 // farthest point of a die from its centre (the model tip)

// One die body added to the world: the exact trimmed hull (or the ball's sphere of radius h) for a throw; with `loose`
// (the hand box) a sphere of radius = the tip instead, which holds the whole die and is far cheaper than hull-on-hull SAT.
function addDie(world, mat, spec, loose = false) {
  const { h, faces, hullDef, tip = Infinity, sphere = false } = spec;
  if (!loose && !sphere && (!hullDef?.verts || !hullDef.faces)) throw new Error('faces.json has no hull');
  const shape = loose ? new CANNON.Sphere(reach(spec)) : sphere ? new CANNON.Sphere(h) : hullShape(hullDef, tip);   // ball: h = its radius
  const body = new CANNON.Body({ mass: 1, shape, material: mat, linearDamping: 0.02, angularDamping: 0.1 });
  body.allowSleep = false;
  world.addBody(body);
  return { body, faces, h, sphere, calm: 0, quiet: 0, anchor: null };
}

// Build a fresh world: felt floor + 4 wall planes + ramps + one body per die. `tbl` = { hx, hz } inner half-width / half-depth
// of the table (default: the current setTable value; the sim keeps its own copy in sim.table). dice = [{ h, faces, hullDef, tip, sphere }]:
// h = centre-to-face distance (times the visual scale), hullDef = { verts, faces } = the sharp polyhedron from faces.json
// "hull" (times the scale), tip = farthest model vertex from the centre (times the scale; hull corners beyond it are trimmed),
// sphere = ball shape (h = its radius). Bodies are added in array order: same order + same specs = same contacts = same bits.
// A fresh world per throw guarantees the hidden run and the replay start identically.
export function makeSim(dice, tbl = table) {
  const { world, felt, wood, die } = newWorld(), { hx, hz } = tbl;

  const plane = (mat, pos, axis, angle) => {
    const b = new CANNON.Body({ mass: 0, shape: new CANNON.Plane(), material: mat });
    b.quaternion.setFromAxisAngle(new CANNON.Vec3(...axis), angle);
    b.position.set(...pos);
    world.addBody(b);
  };
  const P = Math.PI / 2;
  plane(felt, [0, 0, 0], [1, 0, 0], -P);                        // floor, normal +Y
  plane(wood, [-hx, 0, 0], [0, 1, 0], P);                     // left wall, normal +X
  plane(wood, [hx, 0, 0], [0, 1, 0], -P);                     // right wall, normal -X
  plane(wood, [0, 0, -hz], [0, 1, 0], 0);                     // back wall, normal +Z
  plane(wood, [0, 0, hz], [0, 1, 0], 2 * P);                  // front wall, normal -Z
  // Invisible 45 deg ramps along each wall's foot: a die can't prop its edge in the corner and lean on
  // the wall; it slides back onto the felt. A tilted plane is solid below it, so it only matters next to the wall.
  for (const [sx, sz] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
    const b = new CANNON.Body({ mass: 0, shape: new CANNON.Plane(), material: wood });
    b.quaternion.setFromVectors(new CANNON.Vec3(0, 0, 1), new CANNON.Vec3(-sx, 1, -sz).unit());   // normal: up and inward
    b.position.set(sx * (hx - RAMP), 0, sz * (hz - RAMP));   // x ramps hug the x walls, z ramps the z walls
    world.addBody(b);
  }

  const list = dice.map((spec) => addDie(world, die, spec));
  return { world, dice: list, steps: 0, done: false, table: { hx, hz } };
}

// ---------- hand box: the dice shaken in a closed kinematic box (the pointer carries it), thrown on release ----------
const BOX_WALL = 0.5;                 // half thickness of a box wall: 0.5 thick, so a die cannot tunnel at 25 u/s (0.21 u per step)
export const BOX_SPEED = 25;          // cap of the box's speed (u/s), also the cap for a thrown die
const BOX_LOOSE = 0.6;                // a die farther than this beyond the inner box is put back (safety net)
// Inner size of the box for these dice (each is a sphere of radius `reach` in the box): s wide and deep (1.1 + 0.35 sqrt(n),
// but at least cols grid cells of 2.05 x the biggest radius, so the spheres start without touching) and hh high (0.9, but at
// least 2.1 x the biggest radius so a die can tumble).
export function handBox(dice) {
  const n = dice.length, cols = Math.ceil(Math.sqrt(n)), big = Math.max(...dice.map(reach));
  return { s: Math.max(1.1 + 0.35 * Math.sqrt(n), cols * 2.05 * big), hh: Math.max(0.9, 2.1 * big) };
}

// Hand world: same gravity and contact materials as the throw, the dice (SPHERES of radius = tip, same body order; they
// still spin from friction and wall hits, so the dice visibly tumble) and ONE kinematic
// body made of six thin boxes (floor, lid, 4 walls) around the inner space; no table. `quats[i]` = die i's orientation,
// `at` = [x, y, z] box centre. The dice start on a small grid (rows of ceil(sqrt n)) on the box floor, zero velocity.
export function makeHand(dice, quats, at) {
  const { world, wood, die } = newWorld(), { s, hh } = handBox(dice), t = BOX_WALL;
  const box = new CANNON.Body({ mass: 0, type: CANNON.Body.KINEMATIC, material: wood });
  const part = (hx, hy, hz, x, y, z) => box.addShape(new CANNON.Box(new CANNON.Vec3(hx, hy, hz)), new CANNON.Vec3(x, y, z));
  const o = s / 2 + t, oy = hh / 2 + t;
  part(o, t, o, 0, -oy, 0); part(o, t, o, 0, oy, 0);              // floor, lid
  part(t, oy, o, -o, 0, 0); part(t, oy, o, o, 0, 0);              // walls -x, +x
  part(o, oy, t, 0, 0, -o); part(o, oy, t, 0, 0, o);              // walls -z, +z
  box.position.set(...at);
  world.addBody(box);
  const list = dice.map((spec) => addDie(world, die, spec, true));
  const n = list.length, cols = Math.ceil(Math.sqrt(n)), rows = Math.ceil(n / cols);
  list.forEach(({ body: b }, i) => {
    const c = i % cols, r = Math.floor(i / cols), spec = dice[i];
    b.position.set(at[0] + (c - (cols - 1) / 2) * s / cols, at[1] - hh / 2 + reach(spec) + 0.01, at[2] + (r - (rows - 1) / 2) * s / rows);
    b.quaternion.set(...quats[i]);
  });
  return { world, dice: list, box, s, hh, y: at[1] };
}

// One fixed step of the hand world with the box heading for (tx, tz) at its own height. The box MOVES by velocity
// v = (target - position) / DT, capped to BOX_SPEED, never by teleporting: cannon then sees the moving walls and resolves
// every hit on the dice (a teleport would let the dice be skipped through). A die that still got out is put back.
export function stepHand(hand, tx, tz) {
  const b = hand.box, p = b.position;
  const vx = (tx - p.x) / DT, vy = (hand.y - p.y) / DT, vz = (tz - p.z) / DT;
  const k = Math.min(1, BOX_SPEED / (Math.hypot(vx, vy, vz) || 1));
  b.velocity.set(vx * k, vy * k, vz * k);
  hand.world.step(DT);
  const lim = hand.s / 2 + BOX_LOOSE, limY = hand.hh / 2 + BOX_LOOSE;
  for (const { body: d } of hand.dice) {
    if (Math.abs(d.position.x - p.x) > lim || Math.abs(d.position.z - p.z) > lim || Math.abs(d.position.y - p.y) > limY) {
      d.position.set(p.x, p.y, p.z); d.velocity.set(0, 0, 0); d.angularVelocity.set(0, 0, 0); hand.resets = (hand.resets || 0) + 1;
    }
  }
}

// specs[i] = { pos:[x,y,z], quat:[x,y,z,w], vel:[..], ang:[..] } for die i (plain numbers, easy to replay)
export function launch(sim, specs) {
  sim.dice.forEach(({ body: b }, i) => {
    const s = specs[i];
    b.position.set(...s.pos); b.quaternion.set(...s.quat);
    b.velocity.set(...s.vel); b.angularVelocity.set(...s.ang);
  });
}

// One fixed step plus rest detection. Used by BOTH the hidden run and the visible replay,
// so their step sequences are identical. Done when every die rests at the same step (or at the MAX_STEPS limit).
export function stepOnce(sim) {
  sim.world.step(DT);                                           // single arg = fixed step, no sub-stepping
  sim.steps++;
  let all = true;
  for (const d of sim.dice) if (!settle(sim, d)) all = false;   // array order, so the drag replays identically
  if (all || sim.steps >= MAX_STEPS) sim.done = true;
}

// One die after a step: drag and rest tracking. True = it rests this step: still or calm for REST_STEPS, flat or not (a die
// leaning on a wall or on another die stays cocked and is read by its face closest to up, as at a real table), or flat and
// nearly still for QUIET_REST.
function settle(sim, d) {
  const b = d.body;
  // Rolling resistance (cannon-es has none): low on the felt and slow -> spin fades, so round dice (d12, d20) stop rolling.
  // A sphere has no flat side to settle on, so for it drag works whenever it is low, not only when slow, and stronger.
  if (b.position.y < d.h * 1.6 && (d.sphere || b.velocity.lengthSquared() < 4)) b.angularVelocity.scale(d.sphere ? SPHERE_DRAG : ROLL_DRAG, b.angularVelocity);
  const v2 = b.velocity.lengthSquared(), w2 = b.angularVelocity.lengthSquared();
  d.calm = v2 < REST_V * REST_V && w2 < REST_W * REST_W ? d.calm + 1 : 0;
  d.quiet = v2 < 0.09 && w2 < 0.36 ? d.quiet + 1 : 0;          // looser: also catches slow creeping
  const flat = d.sphere || faceUp(b.quaternion, d.faces).dot >= FLAT;   // sphere: never "tilted", done on rest alone
  // Rest friction: a die lying flat on the felt and nearly still loses 8 % of its speed and spin per step, so a die wedged
  // in a row of dice stops instead of creeping for seconds (measured: 15-30 % of hand throws ran to the old 12 s stop).
  if (!d.sphere && flat && b.position.y < d.h * 1.6 && v2 < 0.36 && w2 < 4) { b.velocity.scale(SETTLE, b.velocity); b.angularVelocity.scale(SETTLE, b.angularVelocity); }
  // Still = has not left a small box (0.01 u, ~1 deg) for REST_STEPS steps. Unlike `calm` this ignores the solver's
  // contact jitter, which on the d10's thin kites kept resetting `calm` until the time limit.
  const a = d.anchor, q = b.quaternion;
  if (!a || b.position.distanceTo(a.p) > 0.01 || Math.abs(q.x * a.q.x + q.y * a.q.y + q.z * a.q.z + q.w * a.q.w) < 0.99996) {
    d.anchor = { p: b.position.clone(), q: q.clone(), at: sim.steps };
  }
  const still = sim.steps - d.anchor.at >= REST_STEPS;
  return d.calm >= REST_STEPS || still || (flat && d.quiet >= QUIET_REST);   // quiet: a flat die jammed in a row trembles, its face is settled
}

// Run a throw without drawing anything; per die the face (index) it lands on and its final body quaternion.
export function runHeadless(specs, dice, tbl = table) {
  const sim = makeSim(dice, tbl);
  launch(sim, specs);
  while (!sim.done) stepOnce(sim);
  return { steps: sim.steps, dice: sim.dice.map((d) => {
    const q = d.body.quaternion, up = faceUp(q, d.faces);
    return { face: up.index, tilted: !d.sphere && up.dot < FLAT, quat: [q.x, q.y, q.z, q.w] };
  }) };
}
