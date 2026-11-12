// main.js - 3D dice throw demo (d4 to d20, d100 pair, d100 ball; one die or a handful of up to 10): three.js draws,
// physics.js (cannon-es) simulates. Forced results use "simulate, then turn": a hidden run finds the face that lands up
// on every die, each mesh is turned (by a symmetry of its hull) so its wanted face takes that place, then the SAME throw
// is replayed visibly. The physics shapes are symmetric, so the turns never change the trajectories.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DT, HALF_Z, HALF_X_MIN, HALF_X_MAX, setTable, BOX_SPEED, MAX_STEPS, mulberry32, faceUp, makeSim, launch, stepOnce, runHeadless, makeHand, handBox, stepHand, symmetryFor, symsFor, arc, rot } from './physics.js';

const $ = (id) => document.getElementById(id);
const canvas = $('c'), elResult = $('result'), elParts = $('parts'), elHistory = $('history'), elStatus = $('status');
const elHud = $('hud'), btnLift = $('lifttoggle'), btnThrow = $('throw'), selTarget = $('target'), btnQuality = $('quality'), btnTex = $('texq'), selDie = $('dieSel');
const elStats = $('stats'), btnStats = $('statstoggle'), elLand = $('landOn'), btnServer = $('server');
const elTray = $('tray'), elRows = $('rows'), elCount = $('trCount'), btnClear = $('clear'), btnTray = $('trayBtn'), btnTrClose = $('trClose'), selStat = $('stDie');

const WALL_H = 0.5, WALL_T = 0.4;   // visual rim (physics walls are infinite planes at x = +-HALF_X, z = +-HALF_Z)
let HALF_X = HALF_Z, wantX = HALF_X;   // table inner half-width now / wanted for the current screen (applied when idle, see applyTable)
const HAND_Y = 2.4;                 // height of the hand box centre while held
const UP = new THREE.Vector3(0, 1, 0);
// Models: scale = visual size (model and physics together) so the set looks even; all polyhedra smaller, the ball a bit
// larger. file = dice/models/<file>.glb/.faces.json (default: the key). faces.json "physics": "sphere" = ball (sphere shape, no hull).
// lift = size when lifted (default LIFT_SCALE). Add a die: entry here + its files + a KINDS entry.
const DICE = { d4: { scale: 0.92 }, d6: { scale: 0.88 }, d8: { scale: 0.8 }, d10: { scale: 0.76 }, d10t: { scale: 0.76 },
               d12: { scale: 0.8 }, d20: { scale: 0.84 }, ball: { scale: 1.1, label: 'd100 ball', lift: 1.8, file: 'd100' } };
// Handful kinds (tray, picker and tally order): the models one entry throws (d100 = tens die 00-90 + d10) and its values 1..sides.
const KINDS = { d4: { dice: ['d4'], sides: 4 }, d6: { dice: ['d6'], sides: 6 }, d8: { dice: ['d8'], sides: 8 }, d10: { dice: ['d10'], sides: 10 },
                d12: { dice: ['d12'], sides: 12 }, d20: { dice: ['d20'], sides: 20 }, d100: { dice: ['d10t', 'd10'], sides: 100, label: 'd100 pair' },
                ball: { dice: ['ball'], sides: 100, label: DICE.ball.label } };
const MAX_DICE = 10;                // the d100 pair counts 2
const kLabel = (k) => KINDS[k].label ?? k;
const MODEL_V = '6';   // bump after every Blender re-export so a normal reload fetches the new model, not the cached copy
const LEAN = 25 * Math.PI / 180;  // vertex dice (d4) in the lift: top corner leans toward the camera

// ---------- renderer, scene, light ----------
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
} catch (err) {
  elResult.textContent = 'WebGL is not available here.';
  throw err;
}
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0d130f);
const camera = new THREE.PerspectiveCamera(38, 1, 0.5, 120);

scene.add(new THREE.HemisphereLight(0xfff4e0, 0x1b2a20, 0.9));              // soft fill
const sun = new THREE.DirectionalLight(0xfff0d8, 2.6);                       // key light, upper left
sun.position.set(-4, 8, 3);
sun.castShadow = true;
const coarse = matchMedia('(pointer: coarse)').matches;
sun.shadow.mapSize.set(coarse ? 1024 : 2048, coarse ? 1024 : 2048);
Object.assign(sun.shadow.camera, { left: -4, right: 4, top: 4, bottom: -4, near: 1, far: 30 });
sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.02;
scene.add(sun);

// ---------- table: felt + low wooden rim ----------
function feltTexture() {                                   // tiny noise texture, purely cosmetic
  const c = document.createElement('canvas'); c.width = c.height = 256;
  const g = c.getContext('2d'), img = g.createImageData(256, 256);
  for (let i = 0; i < img.data.length; i += 4) { const v = 190 + Math.random() * 65; img.data.set([v, v, v, 255], i); }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(12, 12);
  t.colorSpace = THREE.SRGBColorSpace; return t;
}
// The table (felt + 4 rim pieces) lives in one group and is rebuilt by buildTable whenever the half-width changes. Only the
// x size varies (wide screens); z stays HALF_Z. fitPts = the 8 corners of the table box the camera must fit.
const feltTex = feltTexture(), tableGroup = new THREE.Group(), fitPts = [];
const feltMat = new THREE.MeshStandardMaterial({ color: 0x226a45, map: feltTex, roughness: 1 });
const woodMat = new THREE.MeshStandardMaterial({ color: 0x4a3020, roughness: 0.7 });
scene.add(tableGroup);
function buildTable() {
  for (const o of tableGroup.children) o.geometry.dispose();             // materials and the texture are shared, kept
  tableGroup.clear();
  const ox = HALF_X + WALL_T, oz = HALF_Z + WALL_T;                       // outer half sizes (rim included)
  feltTex.repeat.set(12 * ox / oz, 12);                                   // same grain size on a wider felt
  const felt = new THREE.Mesh(new THREE.PlaneGeometry(ox * 2, oz * 2), feltMat);
  felt.rotation.x = -Math.PI / 2; felt.receiveShadow = true; tableGroup.add(felt);
  for (const [sx, sz, px, pz] of [[ox * 2, WALL_T, 0, HALF_Z + WALL_T / 2], [ox * 2, WALL_T, 0, -HALF_Z - WALL_T / 2],
                                   [WALL_T, HALF_Z * 2, HALF_X + WALL_T / 2, 0], [WALL_T, HALF_Z * 2, -HALF_X - WALL_T / 2, 0]]) {
    const w = new THREE.Mesh(new THREE.BoxGeometry(sx, WALL_H, sz), woodMat);
    w.position.set(px, WALL_H / 2, pz); w.castShadow = w.receiveShadow = true; tableGroup.add(w);
  }
  fitPts.length = 0;
  for (const x of [-ox, ox]) for (const z of [-oz, oz]) for (const y of [0, WALL_H]) fitPts.push(new THREE.Vector3(x, y, z));
  const e = 4 * Math.max(1, ox / (HALF_Z + WALL_T));                      // the shadow frustum grows with the table (4 = the square table)
  Object.assign(sun.shadow.camera, { left: -e, right: e, top: e, bottom: -e }); sun.shadow.camera.updateProjectionMatrix();
}
buildTable();
// A new width only while nothing is simulated (loading / idle); a throw or hold in progress keeps its table and the frame loop
// applies the wanted one right after. Dice resting outside a narrower table are pulled in along x (a lifted row: its rest poses).
const tableFree = () => state === 'idle' || state === 'loading';
function applyTable() {
  if (wantX === HALF_X || !tableFree()) return;
  HALF_X = wantX; setTable(HALF_X, HALF_Z); buildTable();
  hand.forEach((d, i) => {
    const lim = Math.max(HALF_X - d.m.tip - 0.05, 0), p = lift?.items ? lift.items[i].p0 : d.g.position;
    p.x = Math.max(-lim, Math.min(lim, p.x));
  });
  dirty = true;
}

// Cheap fake shadow (one per die) shown when real shadows are off (weak phones).
const blobTex = (() => {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d'), r = g.createRadialGradient(32, 32, 2, 32, 32, 32);
  r.addColorStop(0, 'rgba(0,0,0,0.8)'); r.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = r; g.fillRect(0, 0, 64, 64); return new THREE.CanvasTexture(c);
})();
const blobGeo = new THREE.PlaneGeometry(1.1, 1.1);

// ---------- camera: look down at an angle, fit the table between the UI bars ----------
const camDir = new THREE.Vector3(0, 0.84, 0.54).normalize();
let dirty = true;
let view = { l: 16, r: 16, t: 0, b: 0 };  // free screen area (px) for the lifted row: 16 px side margins, between the wide side panels, between top area and bar
// Tally panel: wide screens show it by default (fixed at the right, the table is fitted left of it); narrow screens hide it
// (overlay sheet, covers the table). The Stats button / x flips the state of the current layout.
const wideMq = matchMedia('(min-width: 760px)'), statsOn = { wide: true, narrow: false };
// Shows/hides and places the panel between the top area and the bar; returns the x (px) the 3D view may extend to.
function layoutStats(top, barTop) {
  const wide = wideMq.matches, on = statsOn[wide ? 'wide' : 'narrow'];
  elStats.hidden = !on;
  btnStats.textContent = 'Stats: ' + (on ? 'on' : 'off'); btnStats.setAttribute('aria-pressed', String(on)); btnStats.setAttribute('aria-expanded', String(on));
  if (!on) return innerWidth;
  const optsBot = $('opts').getBoundingClientRect().bottom + 6, t0 = wide ? Math.max(top, optsBot) : optsBot;
  elStats.style.top = (wide ? (t0 + barTop) / 2 : t0) + 'px';                   // wide: centred in the band (CSS translateY(-50%))
  elStats.style.maxHeight = Math.max(barTop - t0 - (wide ? 16 : 8), 120) + 'px';
  return wide ? elStats.getBoundingClientRect().left : innerWidth;              // narrow: overlay, the table is not moved
}
// Handful panel: wide screens fix it at the left edge, centred in the band between the top area and the bar (CSS translateY(-50%));
// narrow ones show it as a sheet above the bar (opened by the Dice button, see openTray). Returns the x (px) the 3D view may start at.
function layoutTray(top, barTop) {
  const wide = wideMq.matches, s = elTray.style;
  if (wide) {
    if (elTray.classList.contains('open')) openTray(false);                      // the sheet state means nothing here
    const t0 = 40;                                                                // the left side is free from just under the fps line
    s.top = (t0 + barTop) / 2 + 'px'; s.bottom = '';
    s.maxHeight = Math.max(barTop - t0 - 8, 120) + 'px';                         // taller content scrolls inside (#rows)
    return elTray.getBoundingClientRect().right;
  }
  s.top = ''; s.bottom = innerHeight - barTop + 4 + 'px';
  s.maxHeight = Math.max(barTop - 4 - ($('opts').getBoundingClientRect().bottom + 6), 140) + 'px';
  return 0;                                                                      // overlay: the table is not moved
}
function showStats(on) { statsOn[wideMq.matches ? 'wide' : 'narrow'] = on; fitCamera(); }
btnStats.addEventListener('click', () => showStats(elStats.hidden));
$('stClose').addEventListener('click', () => { showStats(false); btnStats.focus(); });

function fitCamera() {
  const W = innerWidth, H = innerHeight;
  const top = $('top').getBoundingClientRect().bottom, bot = H - $('bar').getBoundingClientRect().top;
  const R = layoutStats(top, H - bot), L = layoutTray(top, H - bot);   // right / left limit of the free area (W / 0 when no wide panel)
  $('note').style.bottom = bot + 8 + 'px';                  // the bar's height changes with Land on / Server roll
  camera.aspect = W / H;
  camera.setViewOffset(W, H, (W - L - R) / 2, -(top - bot) / 2, W, H);    // centre the table in the free area (band x area between the panels)
  const yMax = 1 - 2 * (top + 2) / H, yMin = -1 + 2 * (bot + 2) / H, xMax = R < W ? 2 * (R - 8) / W - 1 : 0.99, xMin = L > 0 ? 2 * (L + 8) / W - 1 : -0.99;
  view = { l: L + 16, r: Math.min(R, W) - 16, t: top + 4, b: H - bot - 4 };
  // Table width from the free area's shape: 1.25 = width / height the square table fits best; wider area -> wider table (rounded to 0.1).
  const aspect = (Math.min(R, W) - L) / Math.max(H - bot - top, 1) / 1.25;
  wantX = Math.round(Math.max(HALF_X_MIN, Math.min(HALF_X_MAX, HALF_Z * aspect)) * 10) / 10;
  applyTable();                                             // only when idle / loading; otherwise the frame loop retries
  for (let d = 5; d < 90; d += 0.2) {                       // smallest distance where every corner fits
    camera.position.copy(camDir).multiplyScalar(d);
    camera.lookAt(0, 0, 0); camera.updateMatrixWorld(); camera.updateProjectionMatrix();
    if (fitPts.every((p) => { const q = p.clone().project(camera); return q.x > xMin && q.x < xMax && q.y < yMax && q.y > yMin; })) break;
  }
  if (lift && lift.phase === 'held') applyLift(1);          // keep a lifted row glued to the new view
  dirty = true;
}
let dprCap = 2;
function resize() {
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, dprCap));
  renderer.setSize(innerWidth, innerHeight, false);
  fitCamera();
}
addEventListener('resize', resize);

// ---------- quality toggle (shadows + pixel ratio) ----------
let shadowsOn = true;
function setQuality(on) {
  shadowsOn = on;
  renderer.shadowMap.enabled = on; sun.castShadow = on; for (const d of hand) d.blob.visible = !on;
  dprCap = on ? 2 : 1;
  scene.traverse((o) => { if (o.material) o.material.needsUpdate = true; });
  btnQuality.textContent = 'Shadows: ' + (on ? 'on' : 'off'); btnQuality.setAttribute('aria-pressed', String(on));
  resize();
}
btnQuality.addEventListener('click', () => setQuality(!shadowsOn));

// ---------- load dice + face data ----------
// hand = the dice on the table, one per model instance: { name (DICE key), kind (KINDS key), entry (index in kinds; the
// d100 pair = two dice, one entry), m (loaded model data), g (THREE.Group the physics/lift move; a clone of the model
// inside), offQ (relabel turn: mesh = body * offQ), blob, pp/pq (previous step, for drawing between steps) }.
let hand = [], kinds = [];                     // kinds = handful entries in KINDS order, e.g. ['d6', 'd6', 'd100']
const models = {};                             // `${tier}:${name}` -> promise of { faces, read, h, tip, hull, root, scale, sphere }
// Texture tiers: same meshes and faces.json in every folder, only the texture size differs. Cycle order = key order.
const TEX = { full: { label: 'Full', dir: 'dice/models/' }, high: { label: 'High', dir: 'dice/models/high/' }, light: { label: 'Light', dir: 'dice/models/light/' } };
let tex = coarse ? 'light' : 'full';           // phones start light; a saved choice wins
try { const t = localStorage.getItem('vtt-dice.tex'); if (TEX[t]) tex = t; } catch { /* no storage: keep the default */ }
const val = (f) => f.value ?? f.number;        // shown/read value of a face (d10: the face numbered 0 reads 10; d10t: 0..90)

function fetchDie(name) {
  const key = `${tex}:${name}`, dir = TEX[tex].dir;   // per tier, so switching back is instant
  return models[key] ??= (async () => {
    const file = DICE[name].file ?? name;
    const [json, gltf] = await Promise.all([fetch(`${dir}${file}.faces.json?v=${MODEL_V}`).then((r) => r.json()), new GLTFLoader().loadAsync(`${dir}${file}.glb?v=${MODEL_V}`)]);
    const fs = json.faces, rd = json.read ?? 'face', sc = DICE[name].scale, root = gltf.scene;
    const sph = json.physics === 'sphere';     // ball: no hull needed (the physics shape is a sphere of radius h)
    if (!sph && (!json.hull?.verts || !json.hull.faces)) throw new Error(`${file}.faces.json has no hull`);
    const hl = json.hull?.verts ? { verts: json.hull.verts.map((v) => v.map((x) => x * sc)), faces: json.hull.faces } : null;   // sharp physics shape, same scale as the model
    // Face directions: face dice use the normal, vertex dice (d4) rest on the face opposite the corner, so -normal.
    const dirs = fs.map((f) => f.normal.map((x) => (rd === 'vertex' ? -x : x)));
    // Face plane distance: per face, the farthest vertex along its direction over ALL parts of the model (body and the
    // recessed numbers mesh), then averaged over the faces; a recessed part never makes the die look smaller.
    const far = fs.map(() => -1);
    let reach = 0;                             // farthest vertex from the centre (bevelled corners): trims the physics hull
    root.traverse((o) => {
      if (!o.isMesh) return;
      o.castShadow = o.receiveShadow = true;
      // The "numbers" material is metallic gold in the file; without an environment map a metal renders almost black,
      // so here it is a mostly non-metal gold with a faint glow that reads as gold under the scene's lights.
      for (const m of [o.material].flat()) {
        if (m && m.name === 'numbers') { m.metalness = 0.15; m.roughness = 0.4; m.emissive.copy(m.color).multiplyScalar(0.18); }
      }
      const p = o.geometry.attributes.position;
      for (let i = 0; i < p.count; i++) reach = Math.max(reach, Math.hypot(p.getX(i), p.getY(i), p.getZ(i)));
      dirs.forEach((d, k) => {
        for (let i = 0; i < p.count; i++) far[k] = Math.max(far[k], p.getX(i) * d[0] + p.getY(i) * d[1] + p.getZ(i) * d[2]);
      });
    });
    const hh = far.reduce((a, b) => a + b, 0) / far.length * sc;
    const tp = reach * sc;
    root.scale.setScalar(sc);                  // the group's scale stays free for the lift; every die clones this root
    console.log(`[dice] ${name}: face distance h=${hh.toFixed(4)} (model ${(hh / sc).toFixed(4)} x scale ${sc}), tip ${tp.toFixed(4)} (model ${reach.toFixed(4)}), read at ${rd}${sph ? ', sphere physics' : ''}`);
    return { faces: fs, read: rd, h: hh, tip: tp, hull: hl, root, scale: sc, sphere: sph };
  })().catch((err) => { delete models[key]; throw err; });
}

// One visible die: its own group with a clone of the cached model (geometry and materials shared) and its own blob shadow.
function makeDie(name, m, kind, entry) {
  const g = new THREE.Group(); g.add(m.root.clone(true)); scene.add(g);
  const blob = new THREE.Mesh(blobGeo, new THREE.MeshBasicMaterial({ map: blobTex, transparent: true, depthWrite: false }));
  blob.rotation.x = -Math.PI / 2; blob.position.y = 0.01; blob.visible = !shadowsOn; scene.add(blob);
  return { name, kind, entry, m, g, blob, offQ: new THREE.Quaternion(), pp: new THREE.Vector3(), pq: new THREE.Quaternion() };
}
const countDice = (list) => list.reduce((n, k) => n + KINDS[k].dice.length, 0);
const order = Object.keys(KINDS), sortKinds = (list) => [...list].sort((a, b) => order.indexOf(a) - order.indexOf(b));

// Swap the handful (any state): rest pose, fresh Land on list, no old roll. Throws when a model cannot load (hand unchanged).
async function loadHand(list) {
  state = 'loading'; cancelLift(); syncUi();
  elResult.className = 'busy'; elResult.textContent = 'Loading...'; elParts.replaceChildren();
  try {
    const names = [], ents = [];
    list.forEach((k, e) => KINDS[k].dice.forEach((n) => { names.push(n); ents.push([k, e]); }));
    const ms = await Promise.all(names.map(fetchDie));
    for (const d of hand) { scene.remove(d.g, d.blob); d.blob.material.dispose(); }
    kinds = list; hand = names.map((n, i) => makeDie(n, ms[i], ...ents[i]));
    const one = hand.length === 1 ? hand[0].m.faces : [];   // Land on: one die only (option value = face index; 0 is a real face)
    selTarget.replaceChildren(new Option('free', 'free'), ...one.map((f, i) => new Option(String(val(f)), String(i))));
    roll = null; window.dice.last = null; elStatus.textContent = 'forced: - | replay matched: -';
    restPose(); renderTray(); renderTally();
  } finally {
    state = 'idle'; syncUi(); syncPicker();
  }
  setIdleText(); fitCamera();                   // Land on vs Server roll change the bar height
}
// Picker / tray / test hook: only when idle. Resolves true when the handful is now `list`, false if it could not switch.
async function setHand(list) {
  for (const k of list) if (!KINDS[k]) throw new Error('unknown die ' + k);
  if (countDice(list) > MAX_DICE) throw new Error(`at most ${MAX_DICE} dice (the d100 pair counts 2)`);
  list = sortKinds(list);
  if (state !== 'idle') { syncPicker(); return false; }
  if (list.join() === kinds.join()) return true;
  try { await loadHand(list); return true; }
  catch (err) { console.error(err); note('Could not load ' + list.join(', ')); setIdleText(); return false; }
}
const setDie = (name) => setHand([name]);       // picker: a handful of one
// Texture tier: only when idle. Reloads the same handful from the new tier's folder (loadHand directly: setHand skips an unchanged list).
const showTex = () => { btnTex.textContent = 'Textures: ' + TEX[tex].label; };
async function setTex(t) {
  if (!TEX[t] || state !== 'idle') return false;
  if (t === tex) return true;
  const prev = tex; tex = t;
  try { await loadHand(kinds); }
  catch (err) { console.error(err); tex = prev; note('Could not load ' + TEX[t].label + ' textures'); setIdleText(); return false; }   // hand unchanged
  try { localStorage.setItem('vtt-dice.tex', t); } catch { /* not remembered */ }
  showTex(); return true;
}
btnTex.addEventListener('click', () => { const k = Object.keys(TEX); setTex(k[(k.indexOf(tex) + 1) % k.length]); });
selDie.add(new Option('handful', ''));           // shown while the handful is not exactly one entry
for (const k of order) selDie.add(new Option(kLabel(k), k));
function syncPicker() {
  const one = kinds.length === 1;
  selDie.options[0].text = kinds.length ? 'handful' : '-'; selDie.options[0].hidden = one;
  selDie.value = one ? kinds[0] : '';
}
selDie.addEventListener('change', () => { if (selDie.value) { statKind = selDie.value; setDie(selDie.value); } });

// Put the dice at rest, a face up (d4: a corner up), on a grid in the middle of the table (one die: the centre).
function restPose() {
  const s = grid(hand.length);
  hand.forEach((d, i) => {
    d.offQ.identity(); d.g.scale.setScalar(1); d.g.position.set(s[i][0], d.m.h, s[i][1]);
    d.g.quaternion.setFromUnitVectors(new THREE.Vector3(...d.m.faces[0].normal), UP);
  });
  dirty = true;
}
// Centred [dx, dz] slots for n dice, front row (toward the camera) first; GAP fits the ball (1.1 wide) with room. Rows of 5 on
// the square table; a wider table takes as many per row as fit (the dice are then spread evenly over the rows needed).
const GAP = 1.3;
function grid(n) {
  const fit = Math.max(5, Math.floor((2 * HALF_X - 1.5) / GAP) + 1), rows = Math.ceil(n / fit), per = fit > 5 ? Math.ceil(n / rows) : 5;
  const out = [];
  for (let i = 0; i < n; i++) {
    const row = Math.floor(i / per), inRow = Math.min(per, n - row * per);
    out.push([(i % per - (inRow - 1) / 2) * GAP, ((rows - 1) / 2 - row) * GAP]);
  }
  return out;
}

// ---------- handful panel ----------
// One row per kind, built from KINDS (dice/icons/<kind>.webp): [-] [icon, count badge, name] [+]. Rows are built once; renderTray
// updates counts, syncUi the disabled state. The clicks go through setHand, the same path as the picker and the test hooks.
const rows = {};                                // kind -> { li, dn (badge), minus, plus }
const countOf = (k) => kinds.filter((x) => x === k).length;
for (const k of order) {
  const li = document.createElement('li'); li.className = 'drow';
  li.innerHTML = `<button type="button" data-del="${k}" aria-label="Remove one ${kLabel(k)}">\u2212</button>` +
    `<span class="dpic"><span class="ico"><img src="dice/icons/${k}.webp" alt="" width="56" height="56" draggable="false"><b class="dn" hidden></b></span>` +
    `<span class="dname">${k === 'd100' ? 'd100' : kLabel(k)}</span></span>` +
    `<button type="button" data-add="${k}" aria-label="Add ${kLabel(k)}">+</button>`;
  rows[k] = { li, dn: li.querySelector('.dn'), minus: li.querySelector('[data-del]'), plus: li.querySelector('[data-add]') };
  elRows.append(li);
}
function renderTray() {
  for (const k of order) {
    const c = countOf(k), r = rows[k];
    r.dn.textContent = c; r.dn.hidden = !c; r.li.classList.toggle('on', c > 0);
  }
  elCount.textContent = `${countDice(kinds)} / ${MAX_DICE}`;
  btnTray.textContent = `Dice (${hand.length})`;
}
elTray.addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  if (b === btnTrClose) { openTray(false); btnTray.focus(); return; }
  if (state !== 'idle') return;
  if (b.dataset.add) { statKind = b.dataset.add; setHand([...kinds, b.dataset.add]); }
  else if (b.dataset.del) { const i = kinds.lastIndexOf(b.dataset.del); setHand(kinds.filter((_, j) => j !== i)); }
  else if (b === btnClear) setHand([]);
});
// Narrow screens only (wide: the panel is always there): the Dice button opens the sheet; x, Escape, Throw or a tap outside close it.
function openTray(on) {
  elTray.classList.toggle('open', on); btnTray.setAttribute('aria-expanded', String(on));
  if (on) fitCamera();                          // place the sheet above the bar as it is now
}
btnTray.addEventListener('click', () => openTray(!elTray.classList.contains('open')));
addEventListener('keydown', (e) => { if (e.key === 'Escape' && elTray.classList.contains('open')) { openTray(false); btnTray.focus(); } });
document.addEventListener('pointerdown', (e) => {   // capture phase: the tap that closes the sheet must not also scoop the dice
  if (!elTray.classList.contains('open') || elTray.contains(e.target) || btnTray.contains(e.target)) return;
  openTray(false);
  if (e.target === canvas) e.stopPropagation();
}, true);

// Buttons follow the state: everything locked while not idle; - at count 0; + also when the die would not fit (max 10).
// Several dice: the Server roll switch replaces Land on.
function syncUi() {
  const busy = state !== 'idle', multi = hand.length > 1, n = countDice(kinds);
  btnThrow.disabled = busy || !hand.length;
  selTarget.disabled = selDie.disabled = btnServer.disabled = btnTex.disabled = busy;
  btnClear.disabled = busy || !kinds.length;
  for (const k of order) { rows[k].minus.disabled = busy || !countOf(k); rows[k].plus.disabled = busy || n + KINDS[k].dice.length > MAX_DICE; }
  elLand.hidden = multi; btnServer.hidden = !multi;
  if (multi) selTarget.value = 'free';
}
let serverOn = false;
btnServer.addEventListener('click', () => {
  serverOn = !serverOn; btnServer.textContent = 'Server roll: ' + (serverOn ? 'on' : 'off'); btnServer.setAttribute('aria-pressed', String(serverOn));
});

// ---------- throws ----------
let state = 'loading';                         // loading | idle | holding | rolling | settling
let sim = null, roll = null, acc = 0, tween = null;
const curQ = new THREE.Quaternion();
const history = [];

function randomQuat(r) {                       // uniform random rotation (Shoemake)
  const u = r(), v = r() * 2 * Math.PI, w = r() * 2 * Math.PI;
  return [Math.sqrt(1 - u) * Math.sin(v), Math.sqrt(1 - u) * Math.cos(v), Math.sqrt(u) * Math.sin(w), Math.sqrt(u) * Math.cos(w)];
}
function randomSpin(r, speed) {                // random axis, 14..32 rad/s
  const a = [r() - 0.5, r() - 0.5, r() - 0.5], m = Math.hypot(...a) || 1, s = Math.min(14 + r() * 18 + speed, 40);
  return a.map((x) => (x / m) * s);
}
// Is a die at p (conservative radius rad) inside the camera view?
const frustum = new THREE.Frustum(), pv = new THREE.Matrix4(), bsph = new THREE.Sphere(new THREE.Vector3(), 0.6);
function inView(p, rad) {
  camera.updateMatrixWorld(); pv.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
  frustum.setFromProjectionMatrix(pv); bsph.center.copy(p); bsph.radius = rad; return frustum.intersectsSphere(bsph);
}
// One spec per die from one seed, drawn in hand order from one stream; dice start on the grid (front row at the old spot).
// Free: thrown from the near edge toward the back. Forced: each die starts high above the table, outside the camera view,
// so the face relabel (applied at launch) can never be seen; it drops into view already relabelled.
// A handful of one draws exactly the old single-die numbers (jitter factor 1, grid offset 0).
function handSpecs(seed, forced) {
  const r = mulberry32(seed), s = grid(hand.length), j = hand.length === 1 ? 1 : 0.1, back = s.length ? s[0][1] : 0;
  return hand.map((d, i) => {
    const quat = randomQuat(r), dx = s[i][0], dz = s[i][1] - back;
    if (forced) {
      const p = new THREE.Vector3((r() - 0.5) * 1.4 * j + dx, 5, HALF_Z - 0.9 + (r() - 0.5) * 0.6 * j + dz);
      while (p.y < 40 && inView(p, 0.6 * d.m.scale)) p.y += 0.5;
      return { pos: p.toArray(), quat, vel: [(r() - 0.5) * 3, -4, -(1 + r() * 2.5)], ang: randomSpin(r, 0) };
    }
    const pos = [(r() - 0.5) * 1.4 * j + dx, 2.4 + r() * 0.8, HALF_Z - 0.6 + dz];
    return { pos, quat, vel: [(r() - 0.5) * 3, 1 + r() * 2, -(4 + r() * 3)], ang: randomSpin(r, 0) };   // a bit stronger for the bigger table
  });
}
const newSeed = () => crypto.getRandomValues(new Uint32Array(1))[0];
function randInt(n) {                           // uniform 0..n-1 from crypto (rejection, no modulo bias)
  const lim = 2 ** 32 - (2 ** 32 % n), a = new Uint32Array(1);
  do crypto.getRandomValues(a); while (a[0] >= lim);
  return a[0] % n;
}
// Server roll: a uniform face per die, like a server or game master would pick (d100 pair: tens 0-9 and ones 0-9, 00 + 0 = 100).
const pickTargets = () => hand.map((d) => randInt(d.m.faces.length));
// Physics description per die, in hand order; the hidden run and the replay get the very same list.
const physDefs = () => hand.map(({ m }) => ({ h: m.h, faces: m.faces, hullDef: m.hull, tip: m.tip, sphere: m.sphere }));

function setOffset(q, S) {                     // 3x3 row-major -> quaternion q
  q.setFromRotationMatrix(new THREE.Matrix4().set(S[0], S[1], S[2], 0, S[3], S[4], S[5], 0, S[6], S[7], S[8], 0, 0, 0, 0, 1));
}

// targets[i] = face index die i must land on, -1 = free.
function launchRoll(seed, specs, targets) {
  cancelLift();
  state = 'rolling'; syncUi();
  elResult.className = 'busy'; elResult.textContent = 'Rolling...'; elParts.replaceChildren();
  $('hint').style.display = 'none';
  const forced = targets.some((t) => t >= 0), one = hand.length === 1;
  roll = { seed, target: one ? targets[0] : targets, forced, predicted: null, matched: null, hiddenMs: 0, fallback: false,
           dice: hand.map((d, i) => ({ kind: d.kind, name: d.name, target: targets[i], want: targets[i] >= 0 ? val(d.m.faces[targets[i]]) : null, predicted: null, matched: null })) };
  hand.forEach((d) => d.offQ.identity());
  const defs = physDefs(), tb = { hx: HALF_X, hz: HALF_Z };               // one table for the hidden run and the replay
  let replay = specs;
  if (forced) {
    const t0 = performance.now();
    const hidden = runHeadless(specs, defs, tb);                          // 1) hidden run, same fixed steps
    roll.hiddenMs = performance.now() - t0;
    hand.forEach((d, i) => {                                              // 2) per die: target face takes the landed face's place
      const t = targets[i], hd = hidden.dice[i], fs = d.m.faces;
      roll.dice[i].predicted = hd.face;
      if (t < 0) return;
      // Ball: point the target exactly at the hidden run's final "up" (irregular faces: after a plain swap a neighbour
      // could end up higher; any turn is safe for a sphere). Polyhedra: a symmetry of the hull.
      if (d.m.sphere) { const [x, y, z, w] = hd.quat; setOffset(d.offQ, arc(fs[t].normal, rot({ x: -x, y: -y, z: -z, w }, [0, 1, 0]))); }
      else setOffset(d.offQ, symmetryFor(fs, t, hd.face));
    });
    roll.predicted = one ? hidden.dice[0].face : hidden.dice.map((x) => x.face);
    if (!one) { roll.server = entryResults(targets).map((e) => e.value); elParts.replaceChildren(small('srv', 'server: ' + roll.server.join(', '))); }
    if (window.dice.breakReplay) replay = specs.map((s, i) => (i ? s : { ...s, vel: [s.vel[0] + 0.7, s.vel[1], s.vel[2]] }));   // test hook
  }
  sim = makeSim(defs, tb); launch(sim, replay);                               // 3) identical throw, visible
  acc = 0;
  hand.forEach((d, i) => { d.pp.set(...replay[i].pos); d.pq.set(...replay[i].quat); placeDie(d, d.pp, d.pq); });
  setStatus();
  if (window.dice.fast) { while (!sim.done) stepOnce(sim); finishRoll(); }
}

function placeDie(d, pos, q) { d.g.position.copy(pos); d.g.quaternion.copy(q).multiply(d.offQ); }

// Per die: forced and off its predicted face -> settle tween onto the target (safety net); the ball (never flat on one
// face) -> turn onto the nearest face and sink to h; a cocked die stays as it is. All tweens run together, then beginTurn.
function finishRoll() {
  const fix = [];
  hand.forEach((d, i) => {
    const b = sim.dice[i].body, x = roll.dice[i];
    placeDie(d, new THREE.Vector3(b.position.x, b.position.y, b.position.z), new THREE.Quaternion(b.quaternion.x, b.quaternion.y, b.quaternion.z, b.quaternion.w));
    if (x.target >= 0) {
      x.matched = faceUp(b.quaternion, d.m.faces).index === x.predicted;
      if (!x.matched) {
        console.warn(`[dice] ${d.name} (#${i}) replay landed on another face than predicted - using settle tween`);
        roll.fallback = true; fix.push(fixTween(d, x.target, false)); return;
      }
    }
    // A cocked die (tilted against a wall or a die) stays as it froze, read by its face closest to up; the ball has no flat
    // side, so it turns onto its nearest face.
    if (d.m.sphere) { roll.tiltFix = true; fix.push(fixTween(d, faceUp(d.g.quaternion, d.m.faces).index, true)); }
  });
  if (roll.forced) roll.matched = roll.dice.every((x) => x.target < 0 || x.matched);
  runTweens(fix, 'fix', beginTurn);
}
// Turn face fi of die d (mesh) to +Y; sink = also settle to rest height h (tilted stop / ball).
function fixTween(d, fi, sink) {
  const from = d.g.quaternion.clone(), want = new THREE.Vector3(...d.m.faces[fi].normal).applyQuaternion(from);
  const low = d.g.position.y < d.m.h * 1.5;     // only near the felt: a die resting on another die is laid flat where it is
  return { d, from, to: new THREE.Quaternion().setFromUnitVectors(want, UP).multiply(from), y: sink && low ? [d.g.position.y, d.m.h] : null };
}
// Per-die tweens of one kind, all 0.35 s together; none, fast mode or `instant` -> jump to the end. `next` runs after.
function runTweens(list, kind, next, instant = false) {
  if (!list.length || instant || window.dice.fast) { for (const w of list) setTween(w, 1); next(); return; }
  tween = { list, kind, next, t: 0, dur: 0.35 }; state = 'settling'; setStatus();
}
function setTween(w, e) {                       // e = 1 lands exactly on `to` (three.js slerp copies qb at t = 1)
  w.d.g.quaternion.slerpQuaternions(w.from, w.to, e);
  if (w.y) w.d.g.position.y = w.y[0] + (w.y[1] - w.y[0]) * e;
}

// Yaw of die d's rolled digit (dice without `up`, the d4, have none -> 0): 0 = its "up" vector (faces.json) points to the
// top of the screen (-Z, away from the camera), positive/negative = turned to one side. Degrees, in (-180, 180].
function digitYaw(d) {
  const f = d.m.faces[faceUp(d.g.quaternion, d.m.faces).index];
  if (!f.up) return 0;
  const u = new THREE.Vector3(...f.up).applyQuaternion(d.g.quaternion);
  return Math.atan2(u.x, -u.z) * 180 / Math.PI;
}

// Settle turn (only with Lift result off): once the dice rest, spin each about the vertical axis through its centre until
// its digit reads upright. Pure yaw, so the face stays flat on the felt (the next throw builds a fresh world).
function beginTurn() {
  if (liftOn) { showResult(); return; }                                  // lift on: the dice turn in the air later, not on the table
  const list = hand.map((d) => {
    const phi = digitYaw(d) * Math.PI / 180, from = d.g.quaternion.clone();   // rotating by phi about +Y brings the angle to 0
    return { d, phi, from, to: new THREE.Quaternion().setFromAxisAngle(UP, phi).multiply(from) };
  });
  runTweens(list, 'yaw', showResult, list.every((w) => Math.abs(w.phi) < 1e-3));
}

// Per handful entry { kind, value, parts } from a face index per die: one die = its value; the d100 pair = tens value
// (0..90) + the d10's number (0..9), 00 + 0 = 100.
function entryResults(faceIdx) {
  return kinds.map((kind, e) => {
    const fs = [];
    hand.forEach((d, i) => { if (d.entry === e) fs.push(d.m.faces[faceIdx[i]]); });
    if (kind === 'd100') { const t = val(fs[0]), o = fs[1].number; return { kind, value: t + o || 100, parts: [t, o] }; }
    return { kind, value: val(fs[0]), parts: [val(fs[0])] };
  });
}
const small = (cls, text) => Object.assign(document.createElement('span'), { className: cls, textContent: text });
function chip(label, n, cls, title, extra) {
  const c = Object.assign(document.createElement('span'), { className: 'chip' + (cls ? ' ' + cls : ''), title: title ?? '' });
  c.append(Object.assign(document.createElement('i'), { textContent: label }), ' ' + n);
  if (extra) c.append(' ', Object.assign(document.createElement('i'), { textContent: extra }));
  return c;
}
const pairText = (p) => `${String(p[0]).padStart(2, '0')} + ${p[1]}`;
const partsText = (es) => es.map((e) => `${e.kind} ${e.value}` + (e.kind === 'd100' ? ` (${pairText(e.parts)})` : '')).join(', ');
function handName() {                           // '2d6 + d8 + d100 + ball'
  return order.map((k) => [k, kinds.filter((x) => x === k).length]).filter(([, c]) => c)
    .map(([k, c]) => (c === 1 ? k : k === 'ball' ? `${c} balls` : c + k)).join(' + ');
}

function showResult() {
  state = 'idle'; sim = null;
  const fis = hand.map((d) => faceUp(d.g.quaternion, d.m.faces).index);   // face most aligned with +Y, per die
  hand.forEach((d, i) => Object.assign(roll.dice[i], { face: fis[i], value: val(d.m.faces[fis[i]]), yaw: digitYaw(d) }));
  const es = entryResults(fis), total = es.reduce((a, e) => a + e.value, 0), single = hand.length === 1;
  Object.assign(roll, { entries: es, total, result: total, yaw: roll.dice[0].yaw, die: single ? kinds[0] : handName(),
                        ok: roll.dice.every((x) => x.want === null || x.value === x.want) });
  window.dice.last = roll;
  if (!roll.forced) { for (const e of es) bump(e.kind, e.value); saveTally(); renderTally(); }   // Land on / server rolls are not counted
  elResult.className = '';
  elResult.innerHTML = `Rolled <b>${total}</b>` + (kinds.length === 1 ? ` <small>${kLabel(kinds[0])}</small>` : '');
  const how = roll.forced ? 'forced' : 'free';
  elParts.replaceChildren(...(single ? [] : es.map((e) => chip(e.kind, e.value, roll.forced && 'forced', '', e.kind === 'd100' ? pairText(e.parts) : ''))));
  history.unshift(single ? { n: total, d: kinds[0], forced: roll.forced, title: `${kinds[0]}, ${how}` }
                         : { n: total, d: kinds.length === 1 ? kinds[0] : 'sum', forced: roll.forced, title: `${handName()}: ${partsText(es)}, ${how}` });
  history.length = Math.min(history.length, 10);
  elHistory.replaceChildren(...history.map((e) => chip(e.d, e.n, e.forced && 'forced', e.title)));
  syncUi(); setStatus(); dirty = true;
  lift = liftOn && !window.dice.fast ? { phase: 'wait', t: 0 } : null;
}

function setIdleText() {
  elResult.className = 'busy'; elParts.replaceChildren();
  elResult.textContent = !hand.length ? 'Add dice to throw' : hand.length === 1 ? 'Throw the ' + kLabel(kinds[0]) : 'Throw ' + handName();
}
function setStatus() {
  if (!roll) return;
  const m = roll.matched === null ? '-' : roll.matched ? 'yes' : 'no (settle tween used)';
  elStatus.textContent = `forced: ${roll.forced ? 'yes' : 'no'} | replay matched: ${m} | seed ${roll.seed}` +
    (roll.forced ? ` | hidden run ${roll.hiddenMs.toFixed(1)} ms` : '') + (roll.server ? ` | server: ${roll.server.join(', ')}` : '');
}

let noteTimer = 0;
function note(text) {                           // short-lived hint above the bar
  const el = $('note'); el.textContent = text; el.hidden = false;
  clearTimeout(noteTimer); noteTimer = setTimeout(() => { el.hidden = true; }, 3500);
}
const targetIdx = () => (selTarget.value === 'free' ? -1 : Number(selTarget.value));   // face index, -1 = free (one die only)
function throwNow(seed, server) {               // Throw button / test hook: one die uses Land on, several the server switch
  const srv = server ?? serverOn, t = hand.length > 1 || server !== undefined ? (srv ? pickTargets() : hand.map(() => -1)) : [targetIdx()];
  launchRoll(seed, handSpecs(seed, t.some((x) => x >= 0)), t);
}
btnThrow.addEventListener('click', () => { if (state === 'idle' && hand.length) { openTray(false); throwNow(newSeed()); } });
// Space throws, unless a select or another button has the focus (Space presses that button, e.g. + d6).
addEventListener('keydown', (e) => { if (e.code === 'Space' && state === 'idle' && !['SELECT', 'BUTTON'].includes(document.activeElement?.tagName)) { e.preventDefault(); btnThrow.click(); } });

// ---------- tally: how often each number came up (free throws only) ----------
// tally = { d6: { '1': 3, '4': 1 }, d100: {..}, ball: {..} } keyed by the SHOWN value (d10 zero face = '10'; d100 pair =
// its combined value 1..100). The in-memory object is the truth; localStorage is only a mirror, so everything still works
// (until reload) when storage is blocked. Stored as { v: 2, ...tally }; without v it is the old layout where 'd100' was the ball.
const TALLY_KEY = 'dice-demo-tally-v1';
let migrated = false;
function loadTally() {
  const out = {};
  try {
    const raw = JSON.parse(localStorage.getItem(TALLY_KEY));
    const old = raw && raw.v !== 2;                                        // older saves used 'd100' for the ball: move it once
    migrated = !!(old && raw.d100);
    for (const k of order) {                                               // only known kinds, only plain counts: stored data is not trusted
      const src = old ? (k === 'ball' ? raw.d100 : k === 'd100' ? null : raw[k]) : raw?.[k];
      for (const [v, n] of Object.entries(src ?? {})) if (/^\d+$/.test(v) && Number.isInteger(n) && n > 0) (out[k] ??= {})[v] = n;
    }
  } catch { /* no storage or bad JSON: start empty */ }
  return out;
}
let tally = loadTally(), statKind = 'd8';       // statKind = the kind the panel shows
function saveTally() { try { localStorage.setItem(TALLY_KEY, JSON.stringify({ v: 2, ...tally })); } catch { /* keep in memory */ } }
if (migrated) saveTally();
const elStTitle = $('stTitle'), elStExp = $('stExp'), elStBody = $('stTable').tBodies[0];
for (const k of order) selStat.add(new Option(kLabel(k), k));
selStat.addEventListener('change', () => { statKind = selStat.value; renderTally(); });

function renderTally() {
  const k = statKind, t = tally[k] ?? {}, sides = KINDS[k].sides, vals = Array.from({ length: sides }, (_, i) => i + 1);
  const counts = vals.map((v) => t[v] ?? 0), n = counts.reduce((a, b) => a + b, 0), max = Math.max(0, ...counts);
  selStat.value = k;
  elStTitle.textContent = `${kLabel(k)} · ${n} ${n === 1 ? 'throw' : 'throws'}`;
  elStExp.textContent = `expected ${(100 / sides).toFixed(1).replace('.', ',')} % each`;
  elStBody.innerHTML = vals.map((v, i) => `<tr><th scope="row">${v}</th><td>${counts[i]}</td>` +
    `<td><span class="b" aria-hidden="true"><i style="width:${max ? (100 * counts[i] / max).toFixed(1) : 0}%"></i></span></td>` +
    `<td>${n ? (100 * counts[i] / n).toFixed(1).replace('.', ',') +' %' : '–'}</td></tr>`).join('');
}
function bump(k, v) { const t = tally[k] ??= {}; t[v] = (t[v] ?? 0) + 1; }
function resetTally(all) { if (all) tally = {}; else delete tally[statKind]; saveTally(); renderTally(); }
$('stReset').addEventListener('click', () => resetTally(false));
$('stResetAll').addEventListener('click', () => { if (confirm('Reset the tally of all dice?')) resetTally(true); });

// ---------- lift: present the result ----------
// ~1 s after they come to rest (as physics left them) the dice float toward the camera into one row along screen-right,
// each rolled face square to the view with its digit upright (turning in the air), and grow a little. A click drops them
// as a new throw; pressing the table scoops the dice into the hand box instead (see below).
// LIFT_REACH: how far the held row floats from the table centre toward the camera (0 = table, 1 = camera); not too close.
const LIFT_WAIT = 1.0, LIFT_UP = 0.6, LIFT_DOWN = 0.35, LIFT_SCALE = 1.05, LIFT_REACH = 0.25;
const ROW_GAP = 0.2, PAIR_GAP = 0.04;          // space between lifted dice (the d100 pair sits closer)
let liftOn = true, lift = null;                // lift = { phase: wait|move|held, t, k (0 rest..1 held), dir, items: [{ p0, q0, face }] }
const smooth = (k) => k * k * (3 - 2 * k);     // ease-in-out
const liftScale = (d) => DICE[d.name].lift ?? LIFT_SCALE;

// Row centre (on the camera ray through the table centre, which sits in the middle of the free screen band) and the
// screen axes there: v toward the camera, u screen-up, r screen-right.
function viewAxes() {
  const pos = camera.position.clone().multiplyScalar(LIFT_REACH), v = camera.position.clone().sub(pos).normalize();
  const cu = new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion);
  const u = cu.addScaledVector(v, -cu.dot(v)).normalize();
  return { pos, v, u, r: u.clone().cross(v) };
}
// Where die d hovers, `off` units along screen-right from the row centre. Face dice: the face normal toward the camera
// and the face's `up` toward screen-up. Vertex dice (d4): the corner (normal) toward screen-up and `front` toward the
// camera, then the top leans LEAN toward the camera about the screen-right axis (seen from above, an edge toward the viewer).
function heldPose(d, faceIdx, off) {
  const { pos, v, u, r } = viewAxes(), f = d.m.faces[faceIdx];
  const n = new THREE.Vector3(...f.normal).normalize(), vtx = d.m.read === 'vertex', ref = f.up ?? f.front;
  const lu = ref ? new THREE.Vector3(...ref) : n.clone().cross(new THREE.Vector3(...(Math.abs(n.z) < 0.9 ? [0, 0, 1] : [1, 0, 0])));
  lu.addScaledVector(n, -lu.dot(n)).normalize();                          // reference direction, made exactly square to the normal
  const mk = (y, z) => new THREE.Matrix4().makeBasis(y.clone().cross(z), y, z);   // right-handed frame from two square axes
  const L = vtx ? mk(n, lu) : mk(lu, n);                                  // local frame: vertex y=corner z=front; face y=up z=normal
  const W = mk(u, v);                                                     // wanted frame: y -> screen up, z -> camera
  const q = new THREE.Quaternion().setFromRotationMatrix(W.multiply(L.invert()));
  if (vtx) q.premultiply(new THREE.Quaternion().setFromAxisAngle(r, LEAN));   // positive angle about right = top toward camera
  return { pos: pos.addScaledVector(r, off), q };
}
// Per die: offset along the row and held scale. A die's drawn width = 2 x tip (farthest vertex) x lift. In a row of 2+ the
// lift is capped at ROW_LIFT (the ball, lift 1.8 alone, would swamp its neighbours). The WHOLE row must fit the free screen
// area (rowRoom): spacing shrinks first (down to touching), then the size of everything (also when the tallest die is too
// tall for the band). The row stays centred on the area. One die: its own lift, centred, never shrunk.
const ROW_LIFT = 1.15;
function rowLayout() {
  if (hand.length === 1) return [{ off: 0, s: liftScale(hand[0]) }];
  const lf = hand.map((d) => Math.min(liftScale(d), ROW_LIFT)), w = hand.map((d, i) => 2 * d.m.tip * lf[i]);
  const gap = hand.map((d, i) => (i ? (d.entry === hand[i - 1].entry ? PAIR_GAP : ROW_GAP) : 0));
  const sumW = w.reduce((a, b) => a + b, 0), sumG = gap.reduce((a, b) => a + b, 0), room = rowRoom();
  const size = Math.min(1, room.h / Math.max(...w), room.w / sumW);               // size factor (1 = no shrink)
  const gf = sumG > 0 ? Math.max(0, Math.min(1, (room.w - sumW * size) / sumG)) : 1;   // spacing factor, shrunk before the size
  const x = [];
  let len = 0;
  hand.forEach((d, i) => { len += gap[i] * gf; x.push(len + w[i] * size / 2); len += w[i] * size; });
  return hand.map((d, i) => ({ off: x[i] - len / 2, s: lf[i] * size }));
}
// World size { w along screen-right, h along screen-up } at the row centre that fits `view`, symmetric about the row centre
// (the table centre is centred in the free area, so this is also the centre of the area).
function rowRoom() {
  const { pos, r, u } = viewAxes(), W = innerWidth, H = innerHeight, c = pos.clone().project(camera);
  const px = (c.x + 1) / 2 * W, py = (1 - c.y) / 2 * H;                            // row centre on screen (px)
  const perX = Math.abs(pos.clone().add(r).project(camera).x - c.x) / 2 * W;       // px per world unit along r / u
  const perY = Math.abs(pos.clone().add(u).project(camera).y - c.y) / 2 * H;
  const hw = Math.max(Math.min(px - view.l, view.r - px), 20), hh = Math.max(Math.min(py - view.t, view.b - py), 20);
  return { w: perX > 0 ? 2 * hw / perX : Infinity, h: perY > 0 ? 2 * hh / perY : Infinity };
}
function applyLift(k) {                         // k: 0 = resting pose, 1 = held row
  const e = smooth(k), row = rowLayout();
  hand.forEach((d, i) => {
    const it = lift.items[i], t = heldPose(d, it.face, row[i].off);
    d.g.position.lerpVectors(it.p0, t.pos, e);
    d.g.quaternion.slerpQuaternions(it.q0, t.q, e);
    d.g.scale.setScalar(1 + (row[i].s - 1) * e);
  });
  dirty = true;
}
function startLift() {
  lift = { phase: 'move', dir: 1, k: 0, t: 0, items: hand.map((d) => ({ p0: d.g.position.clone(), q0: d.g.quaternion.clone(), face: faceUp(d.g.quaternion, d.m.faces).index })) };
}
function dropLift() { if (lift && (lift.phase === 'held' || (lift.phase === 'move' && lift.dir > 0))) { lift.phase = 'move'; lift.dir = -1; } }
function cancelLift() { if (lift) { for (const d of hand) d.g.scale.setScalar(1); lift = null; } }
function updateLift(dt) {
  if (!lift) return;
  if (lift.phase === 'wait') { lift.t += dt; if (lift.t >= LIFT_WAIT) startLift(); return; }
  if (lift.phase !== 'move') return;
  lift.k += lift.dir * dt / (lift.dir > 0 ? LIFT_UP : LIFT_DOWN);
  if (lift.k >= 1) { lift.k = 1; lift.phase = 'held'; }
  if (lift.k <= 0) {
    hand.forEach((d, i) => { d.g.position.copy(lift.items[i].p0); d.g.quaternion.copy(lift.items[i].q0); d.g.scale.setScalar(1); });
    lift = null; dirty = true; return;
  }
  applyLift(lift.k);
}
btnLift.addEventListener('click', () => {
  liftOn = !liftOn; btnLift.textContent = 'Lift result: ' + (liftOn ? 'on' : 'off'); btnLift.setAttribute('aria-pressed', String(liftOn));
  if (!liftOn && lift) { if (lift.phase === 'wait') lift = null; else dropLift(); }
});

// ---------- hand box: press to scoop, shake, release (any number of dice, one included) ----------
// Pressing the canvas (while idle) puts the dice into an invisible closed box under the pointer, in a separate physics world
// (physics.js makeHand). The box follows the pointer by velocity (stepHand), so the dice rattle against each other and the
// walls. Releasing reads every die's pose and speed from that world, adds the box's recent speed as the flick, and starts a
// normal free throw from them. A click (no movement) just drops the dice from the box. Server roll / Land on: no hand throw.
const ray = new THREE.Raycaster(), plane = new THREE.Plane(UP, -HAND_Y), ndc = new THREE.Vector2(), tmpH = new THREE.Vector3();
const FLICK_MAX = 10, TRAIL = 0.1;             // flick speed cap (u/s) and the window the box's speed is measured over (s)
let hold = null;                               // { id, sim, tx, tz, acc, t, trail: [{ t, x, z }] } while state === 'holding'
const boxShadow = new THREE.Mesh(blobGeo, new THREE.MeshBasicMaterial({ map: blobTex, transparent: true, depthWrite: false, opacity: 0.22 }));
boxShadow.rotation.x = -Math.PI / 2; boxShadow.position.y = 0.012; boxShadow.visible = false; scene.add(boxShadow);

function toTable(e, out) {                     // e = anything with clientX/clientY; the pointer ray on the HAND_Y plane
  ndc.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  return !!ray.ray.intersectPlane(plane, out);
}
const clampTo = (v, m) => Math.max(-m, Math.min(m, v));
// Box target = the pointer's point, kept far enough inside the table that the whole box (and its dice) stays over the felt.
function aimHold(e) {
  if (!toTable(e, tmpH)) return;
  const m = hold.sim.s / 2 + 0.2;
  hold.tx = clampTo(tmpH.x, Math.max(HALF_X - m, 0)); hold.tz = clampTo(tmpH.z, Math.max(HALF_Z - m, 0));
}
// Scoop: the dice keep their drawn orientation (a lifted row: as floating, at normal size) and jump into the box at once.
function holdStart(e, id) {
  if (state !== 'idle' || !hand.length) return false;
  if (hand.length > 1 && serverOn) { note('Server roll uses the Throw button (a decided result cannot be turned in the hand)'); return false; }   // relabel would be visible in hand
  if (hand.length === 1 && targetIdx() >= 0) { note('Land on uses the Throw button (a decided result cannot be turned in the hand)'); return false; }
  if (!toTable(e, tmpH)) return false;
  cancelLift();
  const quats = hand.map((d) => { d.offQ.identity(); return d.g.quaternion.toArray(); });
  const defs = physDefs(), m = handBox(defs).s / 2 + 0.2, x = clampTo(tmpH.x, Math.max(HALF_X - m, 0)), z = clampTo(tmpH.z, Math.max(HALF_Z - m, 0));
  const sim = makeHand(defs, quats, [x, HAND_Y, z]);
  hold = { id, sim, tx: x, tz: z, acc: 0, t: 0, trail: [{ t: 0, x, z }] };
  state = 'holding'; syncUi();
  hand.forEach((d, i) => { const b = sim.dice[i].body; d.pp.copy(b.position); d.pq.set(b.quaternion.x, b.quaternion.y, b.quaternion.z, b.quaternion.w); });
  boxShadow.scale.setScalar((sim.s + 0.8) / 1.1); boxShadow.visible = true;
  elResult.className = 'busy'; elResult.textContent = 'Shake and release'; elParts.replaceChildren(); $('hint').style.display = 'none';
  return true;
}
// Release: poses and speeds from the hand world + the flick (box speed over the last TRAIL seconds, capped, a little upward),
// dice kept over the felt, then a normal free throw (no hidden run, no relabel). cancelled = no flick.
function holdEnd(cancelled) {
  if (state !== 'holding') return false;
  const { sim, trail, t } = hold, last = trail[trail.length - 1], first = trail.find((s) => t - s.t <= TRAIL), dt = last.t - first.t;
  hold = null; boxShadow.visible = false;
  let vx = 0, vz = 0;
  if (!cancelled && dt > 0.008) { vx = (last.x - first.x) / dt; vz = (last.z - first.z) / dt; }
  const speed = Math.hypot(vx, vz), k = speed > FLICK_MAX ? FLICK_MAX / speed : 1;
  // Lift only with a real flick: a still click or a cancel just drops the dice.
  const fl = [vx * k, speed > 0.05 ? 1 + Math.min(speed, FLICK_MAX) * 0.12 : 0, vz * k];
  const specs = hand.map((d, i) => {
    const m = Math.max(0.5, d.m.tip + 0.05), limX = HALF_X - m, limZ = HALF_Z - m;   // per die: the 1.1 ball (radius ~0.55) must not start inside a wall
    const b = sim.dice[i].body, v = [b.velocity.x + fl[0], b.velocity.y + fl[1], b.velocity.z + fl[2]], c = Math.min(1, BOX_SPEED / (Math.hypot(...v) || 1));
    return { pos: [clampTo(b.position.x, limX), Math.max(b.position.y, d.m.h + 0.05), clampTo(b.position.z, limZ)], quat: [b.quaternion.x, b.quaternion.y, b.quaternion.z, b.quaternion.w],
             vel: v.map((x) => x * c), ang: [b.angularVelocity.x, b.angularVelocity.y, b.angularVelocity.z] };
  });
  launchRoll(newSeed(), specs, hand.map(() => -1));
  return true;
}
// Pointer events and the test hooks (window.dice.hand2) share holdStart / aimHold / holdEnd; hook holds have id -1.
canvas.addEventListener('pointerdown', (e) => {
  if (state !== 'idle') return;
  if (holdStart(e, e.pointerId)) canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener('pointermove', (e) => { if (hold && e.pointerId === hold.id) aimHold(e); });
canvas.addEventListener('pointerup', (e) => { if (hold && e.pointerId === hold.id) holdEnd(false); });
for (const ev of ['pointercancel', 'lostpointercapture']) canvas.addEventListener(ev, (e) => { if (hold && e.pointerId === hold.id) holdEnd(true); });

// ---------- main loop ----------
let lastT = 0, ema = 16.7, jsEma = 0, wasIdle = true, hudT = 0, lastHud = '';
const tmpA = new THREE.Vector3(), tmpP = new THREE.Vector3(), tmpQ = new THREE.Quaternion();
// Remember each body's pose before a step, and draw the dice between that pose and the current one (a = 0..1).
function keepPrev(s) {
  s.dice.forEach(({ body: b }, i) => { hand[i].pp.copy(b.position); hand[i].pq.set(b.quaternion.x, b.quaternion.y, b.quaternion.z, b.quaternion.w); });
}
function drawBodies(s, a) {
  s.dice.forEach(({ body: b }, i) => {
    const d = hand[i];
    curQ.set(b.quaternion.x, b.quaternion.y, b.quaternion.z, b.quaternion.w);
    tmpA.set(b.position.x, b.position.y, b.position.z);
    placeDie(d, tmpP.copy(d.pp).lerp(tmpA, a), tmpQ.copy(d.pq).slerp(curQ, a));
  });
}
function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min((now - lastT) / 1000, 0.1); lastT = now;
  if (wantX !== HALF_X && state === 'idle') fitCamera();                  // a table width that had to wait for the end of a throw / hold
  const t0 = performance.now();

  if (state === 'rolling' && sim) {
    acc += dt;                                                            // fixed timestep: run whole steps, keep the remainder
    for (let n = 0; acc >= DT && !sim.done && n < 6; n++) { keepPrev(sim); stepOnce(sim); acc -= DT; }   // at most 6 steps a frame
    acc = Math.min(acc, DT);                                              // cap hit: drop the backlog (slower playback, same steps in the same order)
    if (sim.done) finishRoll(); else drawBodies(sim, acc / DT);           // draw between the last two steps
  } else if (state === 'holding') {
    const H = hold;
    H.acc += dt;                                                          // same fixed timestep for the hand world
    for (let n = 0; H.acc >= DT && n < 4; n++) {                          // at most 4 steps a frame
      keepPrev(H.sim); stepHand(H.sim, H.tx, H.tz); H.acc -= DT; H.t += DT;
      H.trail.push({ t: H.t, x: H.sim.box.position.x, z: H.sim.box.position.z });
      while (H.trail[0].t < H.t - 2 * TRAIL) H.trail.shift();
    }
    H.acc = Math.min(H.acc, DT);                                          // cap hit: drop the backlog so a slow frame never snowballs
    drawBodies(H.sim, H.acc / DT);
    boxShadow.position.x = H.sim.box.position.x; boxShadow.position.z = H.sim.box.position.z;
  } else if (state === 'settling') {
    tween.t = Math.min(1, tween.t + dt / tween.dur);
    const e = tween.kind === 'yaw' ? 1 - Math.pow(1 - tween.t, 3) : tween.t * tween.t * (3 - 2 * tween.t);   // yaw: ease-out
    for (const w of tween.list) setTween(w, e);
    if (tween.t >= 1) tween.next();
  }

  if (state === 'idle') updateLift(dt);
  const active = dirty || state === 'rolling' || state === 'holding' || state === 'settling';
  if (active) {
    for (const { g, blob, m } of hand) {                                  // fake shadow follows its die, fades with height
      if (!blob.visible) continue;
      blob.position.x = g.position.x; blob.position.z = g.position.z;
      blob.scale.setScalar((1 + g.position.y * 0.25) * m.scale); blob.material.opacity = 0.9 / (1 + g.position.y * 0.7);
    }
    if (window.dice.trace) window.dice.trace.push({ s: state, v: hand.some((d) => inView(d.g.position, 0.6 * d.m.scale)), o: hand.map((d) => d.offQ.toArray().map((n) => +n.toFixed(3)).join(',')).join('|') });
    renderer.render(scene, camera); dirty = false;
    if (wasIdle) wasIdle = false;                                         // first frame after idle has a long dt: skip it
    else { ema += (dt * 1000 - ema) * 0.1; jsEma += (performance.now() - t0 - jsEma) * 0.1; }
  } else wasIdle = true;

  if (now - hudT > 250) {
    hudT = now;
    const txt = `${(1000 / ema).toFixed(0)} fps | ${ema.toFixed(1)} ms/frame | js ${jsEma.toFixed(1)} ms` + (active ? '' : ' | idle');
    if (txt !== lastHud) { elHud.textContent = txt; lastHud = txt; }
  }
}

// ---------- test hooks (used by the verification script, harmless otherwise) ----------
// Single-die getters (h, tip, sphere, hull, pose) describe the first die of the handful.
const first = () => hand[0]?.m;
window.dice = {
  fast: false, breakReplay: false, last: null,
  get state() { return state; },
  get die() { return hand.length === 1 ? kinds[0] : handName(); },   // 'd8', 'ball', or '2d6 + d100' for a handful
  get hand() { return [...kinds]; },
  get h() { return first()?.h; },               // centre-to-face distance the physics uses (tests build their own sims)
  get tip() { return first()?.tip; },           // farthest model vertex (hull corners are trimmed to it)
  get sphere() { return first()?.sphere; },     // true for the d100 ball (sphere physics shape)
  get hull() { return first()?.hull; },         // scaled physics shape {verts, faces} (tests build their own sims)
  setDie,                                       // (kind) -> promise<boolean>; a handful of one; only works when idle
  setHand,                                      // ([...kinds]) -> promise<boolean>; e.g. ['d6', 'd6', 'd8', 'd100', 'ball']; only when idle
  get tex() { return tex; },                    // texture tier key: 'full' | 'high' | 'light'
  setTex,                                       // ('full'|'high'|'light') -> promise<boolean>; same path as the button; false when not idle / unknown
  get tally() { return structuredClone(tally); },   // copy of { kind: { shownValue: count } } (free throws only)
  resetTally,                                   // (all) -> clears the kind shown in the panel, or every kind when all is true; no confirm()
  throwTo(no, seed) {                           // one die: no = shown value to land on (d10 zero face = 10); 0/undefined = free
    if (hand.length !== 1) throw new Error('throwTo needs a handful of one die; use throwHand');
    const i = no ? hand[0].m.faces.findIndex((f) => val(f) === no) : -1;
    if (no && i < 0) throw new Error(`${kinds[0]} has no face ${no}`);
    const s = seed ?? newSeed();
    selTarget.value = i >= 0 ? String(i) : 'free'; launchRoll(s, handSpecs(s, i >= 0), [i]);
  },
  throwHand(seed, serverRoll = false) {         // whole handful; serverRoll = random target per die (see last.dice[].want, last.ok)
    if (!hand.length) throw new Error('empty handful');
    throwNow(seed ?? newSeed(), !!serverRoll);
  },
  pose: () => {
    const p = (d) => ({ q: d.g.quaternion.toArray(), p: d.g.position.toArray(), s: d.g.scale.x });
    return { ...p(hand[0]), faces: first().faces, dice: hand.map(p), cam: { p: camera.position.toArray(), up: new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion).toArray() } };
  },
  hand2: {                                      // hand box with screen coordinates (px), same code as the pointer events
    start: (x, y) => holdStart({ clientX: x, clientY: y }, -1),                 // -> true when the dice were scooped (idle, free)
    move: (x, y) => { if (hold && hold.id === -1) aimHold({ clientX: x, clientY: y }); },
    end: () => !!hold && hold.id === -1 && holdEnd(false),                       // release with the flick; the throw starts (state 'rolling')
    info: () => hold && { box: hold.sim.box.position.toArray(), s: hold.sim.s, hh: hold.sim.hh, resets: hold.sim.resets || 0, t: hold.t, dice: hold.sim.dice.map((d) => d.body.position.toArray()) },
  },
  get lift() { return lift ? lift.phase + ':' + lift.k : 'none'; },
  trace: null,                                  // set to [] to record {state, any die inView, offsets per die '|'-joined} per drawn frame
  selfTest(n = 200) {                          // determinism check for the current handful: same throw twice -> same bits
    const defs = physDefs(), hists = hand.map((d) => Array(d.m.faces.length).fill(0)), one = hand.length === 1;
    let bad = 0, steps = 0; const t0 = performance.now();
    for (let s = 1; s <= n; s++) {
      const a = runHeadless(handSpecs(s, false), defs), b = runHeadless(handSpecs(s, false), defs);
      if (a.steps !== b.steps || a.dice.some((x, i) => x.face !== b.dice[i].face || x.quat.some((v, k) => v !== b.dice[i].quat[k]))) bad++;
      a.dice.forEach((x, i) => hists[i][x.face]++); steps += a.steps;
    }
    const syms = hand.map((d) => (d.m.sphere ? 'any' : symsFor(d.m.faces).length));
    return { die: window.dice.die, syms: one ? syms[0] : syms, runs: n, mismatches: bad, hist: one ? hists[0] : hists,
             msPerRun: (performance.now() - t0) / (2 * n), avgSimSeconds: steps / n / 120 };
  },
  // Settle-time check for the current handful, n hidden throws (seeds 1..n): 'free' = the Throw button's launch, 'hand' =
  // scoop at a seeded spot, shake 1 s, flick in a seeded direction (as holdEnd builds it). Seconds are simulated time.
  bench(n = 100, mode = 'free') {
    const defs = physDefs(), secs = [];
    let throwsTilted = 0, tilted = 0, stops = 0;
    for (let s = 1; s <= n; s++) {
      let specs;
      if (mode === 'hand') {
        const r = mulberry32(s), at = [(r() - 0.5) * HALF_X, HAND_Y, (r() - 0.5) * HALF_Z];
        const sim = makeHand(defs, hand.map(() => randomQuat(r)), at);
        for (let k = 0; k < 120; k++) stepHand(sim, at[0] + (Math.floor(k / 6) % 2 ? 0.8 : -0.8), at[2]);
        const a = r() * 2 * Math.PI, fl = [Math.cos(a) * FLICK_MAX, 1 + FLICK_MAX * 0.12, Math.sin(a) * FLICK_MAX];
        specs = hand.map((d, i) => {
          const m = Math.max(0.5, d.m.tip + 0.05), b = sim.dice[i].body;
          const v = [b.velocity.x + fl[0], b.velocity.y + fl[1], b.velocity.z + fl[2]], c = Math.min(1, BOX_SPEED / (Math.hypot(...v) || 1));
          return { pos: [clampTo(b.position.x, HALF_X - m), Math.max(b.position.y, d.m.h + 0.05), clampTo(b.position.z, HALF_Z - m)],
                   quat: [b.quaternion.x, b.quaternion.y, b.quaternion.z, b.quaternion.w], vel: v.map((x) => x * c), ang: [b.angularVelocity.x, b.angularVelocity.y, b.angularVelocity.z] };
        });
      } else specs = handSpecs(s, false);
      const res = runHeadless(specs, defs);
      if (res.steps >= MAX_STEPS && window.dice.why && window.dice.why.length < 3) {   // why = [] collects up to 3 stuck throws
        const sim = makeSim(defs); launch(sim, specs);
        while (!sim.done) stepOnce(sim);
        const r2 = (v) => v.map((x) => +x.toFixed(2));
        window.dice.why.push({ seed: s, dice: sim.dice.map((d) => ({ p: r2(d.body.position.toArray()), v: +d.body.velocity.length().toFixed(2),
          w: +d.body.angularVelocity.length().toFixed(2), dot: d.sphere ? 1 : +faceUp(d.body.quaternion, d.faces).dot.toFixed(3), calm: d.calm, quiet: d.quiet })) });
      }
      const tl = res.dice.filter((x) => x.tilted).length;
      secs.push(res.steps / 120); tilted += tl; if (tl) throwsTilted++; if (res.steps >= MAX_STEPS) stops++;
    }
    secs.sort((a, b) => a - b);
    const f = (x) => +x.toFixed(2);
    return { die: window.dice.die, mode, runs: n, avgSec: f(secs.reduce((a, b) => a + b, 0) / n), p90Sec: f(secs[Math.floor(n * 0.9) - 1]),
             maxSec: f(secs[n - 1]), throwsWithTiltedPct: Math.round(100 * throwsTilted / n), tiltedPerThrow: f(tilted / n), stopsAtLimit: stops };
  },
};

// ---------- go ----------
setQuality(true);                             // shadows on by default; the button turns them off for weak phones
showTex();
requestAnimationFrame(frame);
renderTally();
loadHand(['d8']).then(() => resize()).catch((err) => { elResult.textContent = 'Could not load the die: ' + err.message; console.error(err); });
