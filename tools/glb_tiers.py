# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Haxinpro
"""Makes lighter copies of the .glb dice models by shrinking their textures. Standard library + Pillow.

  python3 tools/glb_tiers.py dice/models --size 1024 --out dice/models/high
  python3 tools/glb_tiers.py dice/models --size 512  --out dice/models/light

Every `*.glb` directly in the source folder (not its sub-folders) is copied to the output folder. Each embedded texture that is
wider or taller than --size is scaled down to fit (LANCZOS, aspect kept) and saved again in its own format (JPEG at --quality,
same chroma subsampling as the source; PNG optimized). Textures already that small are copied byte for byte. The matching
`<die>.faces.json` is copied unchanged.

What it changes: only the bytes of the texture images and, because their length changes, the offsets and lengths of the buffer
views and the buffer length in the JSON.
What it never changes: the meshes (accessors and their data), materials, nodes, `asset` (copyright, extras), and faces.json.
After writing, every file is read back and compared with its source; a difference stops the run with an error.

A GLB file is: a 12-byte header ("glTF", version 2, total length), a JSON chunk and one BIN chunk. Each chunk is
<length><type><data>, padded to 4 bytes (JSON with spaces, BIN with zeros). The textures live inside the BIN chunk, as buffer
views that the JSON `images` list points to. Run it again after every model re-export."""
import argparse
import copy
import io
import json
import os
import shutil
import struct
import sys
import tempfile
from pathlib import Path

from PIL import Image, JpegImagePlugin

JSON_TYPE, BIN_TYPE = 0x4E4F534A, 0x004E4942        # "JSON" and "BIN\0" as little-endian numbers
MAGIC = b"glTF"


def read_glb(path):
    """(gltf dict, BIN chunk bytes) of a .glb file. ValueError if it is not a one-buffer GLB 2.0 with embedded data."""
    data = Path(path).read_bytes()
    if len(data) < 12 or data[:4] != MAGIC:
        raise ValueError("not a GLB file (bad magic)")
    version, total = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise ValueError(f"GLB version {version}, only 2 is supported")
    if total != len(data):
        raise ValueError(f"header length {total} differs from file size {len(data)}")
    pos, gltf, binary = 12, None, None
    while pos + 8 <= total:
        size, kind = struct.unpack_from("<II", data, pos)
        chunk = data[pos + 8:pos + 8 + size]
        if len(chunk) != size:
            raise ValueError("truncated chunk")
        if size % 4:
            raise ValueError("chunk length is not a multiple of 4")
        if kind == JSON_TYPE and gltf is None:
            gltf = json.loads(chunk.decode("utf-8"))
        elif kind == BIN_TYPE and binary is None:
            binary = chunk
        else:                                       # writing would drop it, so refuse instead
            raise ValueError(f"unsupported extra chunk (type 0x{kind:08X})")
        pos += 8 + size
    if pos != total:
        raise ValueError("trailing bytes after the last chunk")
    if gltf is None:
        raise ValueError("no JSON chunk")
    if binary is None:
        raise ValueError("no BIN chunk")
    buffers = gltf.get("buffers", [])
    if len(buffers) != 1 or "uri" in buffers[0]:
        raise ValueError("expected exactly one buffer without a uri (the BIN chunk)")
    return gltf, binary


def view_bytes(gltf, binary, i):
    """The bytes of bufferView number i."""
    v = gltf["bufferViews"][i]
    start = v.get("byteOffset", 0)
    end = start + v["byteLength"]
    if end > len(binary):
        raise ValueError(f"bufferView {i} runs past the BIN chunk")
    return binary[start:end]


def image_view(gltf, name):
    """Index of the bufferView that holds the image called name. ValueError if there is none."""
    for img in gltf.get("images", []):
        if img.get("name") == name:
            if "bufferView" not in img:
                raise ValueError(f"image {name!r} is not embedded in the buffer")
            return img["bufferView"]
    raise ValueError(f"no image named {name!r}")


def image_bytes(gltf, binary, name):
    """The (JPEG or PNG) file bytes of the image called name."""
    return view_bytes(gltf, binary, image_view(gltf, name))


def replace_images(gltf, binary, new):
    """(new gltf dict, new BIN bytes) with images swapped. `new` maps image name -> new file bytes.

    Every bufferView keeps its data and its index; only the byteOffset values change (each view starts on a 4-byte boundary,
    zero padded) and replaced images get their new length. The input dict is not changed (a deep copy is returned)."""
    out = copy.deepcopy(gltf)
    swap = {}
    for name, data in new.items():
        i = image_view(out, name)
        if i in swap and swap[i] != data:
            raise ValueError(f"two different replacements for bufferView {i}")
        swap[i] = data
    buf = bytearray()
    for i, view in enumerate(out.get("bufferViews", [])):
        data = swap[i] if i in swap else view_bytes(gltf, binary, i)
        buf += b"\0" * (-len(buf) % 4)              # align the start of this view
        view["byteOffset"] = len(buf)
        view["byteLength"] = len(data)
        buf += data
    out["buffers"][0]["byteLength"] = len(buf)
    return out, bytes(buf)


def write_glb(path, gltf, binary):
    """Writes a GLB 2.0 file: compact JSON chunk (space padded), BIN chunk (zero padded). Goes to a unique temp file first."""
    text = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    blob = (MAGIC + struct.pack("<II", 2, total)
            + struct.pack("<II", len(text), JSON_TYPE) + text
            + struct.pack("<II", len(binary), BIN_TYPE) + binary)
    fd, part = tempfile.mkstemp(prefix=Path(path).name + ".", suffix=".part", dir=Path(path).parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        os.replace(part, path)
    except BaseException:
        os.unlink(part)                             # only our own unique temp file
        raise


def img_size(data):
    """(width, height) of image file bytes."""
    with Image.open(io.BytesIO(data)) as im:
        return im.size


def resize_image(data, mime, size, quality=90):
    """Image file bytes scaled to fit size x size, saved again as mime. Returned unchanged if already small enough."""
    with Image.open(io.BytesIO(data)) as im:
        w, h = im.size
        if max(w, h) <= size:
            return data
        scale = size / max(w, h)
        small = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)
        opts = {}
        if im.info.get("icc_profile"):
            opts["icc_profile"] = im.info["icc_profile"]
        if mime == "image/jpeg":
            sampling = JpegImagePlugin.get_sampling(im)         # 0 = 4:4:4, 1 = 4:2:2, 2 = 4:2:0, -1 = unknown
            if sampling >= 0:
                opts["subsampling"] = sampling
            fmt, opts = "JPEG", {**opts, "quality": quality, "optimize": True}
        elif mime == "image/png":
            fmt, opts = "PNG", {**opts, "optimize": True}
        else:
            raise ValueError(f"unsupported image type {mime!r}")
    out = io.BytesIO()
    small.save(out, fmt, **opts)
    return out.getvalue()


def check(src, dst, names):
    """Reads dst back and compares it with src (both as (gltf, binary)). ValueError on any difference."""
    (g0, b0), (g1, b1) = src, dst
    if g0.get("asset") != g1.get("asset"):
        raise ValueError("asset differs")
    rest = [{k: v for k, v in g.items() if k not in ("bufferViews", "buffers")} for g in (g0, g1)]
    if rest[0] != rest[1]:
        raise ValueError("JSON differs outside bufferViews and buffers")
    if len(g0["bufferViews"]) != len(g1["bufferViews"]):
        raise ValueError("bufferView count differs")
    skip = {image_view(g0, n) for n in names}
    for i in range(len(g0["bufferViews"])):
        if i not in skip and view_bytes(g0, b0, i) != view_bytes(g1, b1, i):
            raise ValueError(f"bufferView {i} (not an image) differs")
        for key in ("byteStride", "target", "buffer"):  # layout fields besides offset and length stay as they were
            if g0["bufferViews"][i].get(key) != g1["bufferViews"][i].get(key):
                raise ValueError(f"bufferView {i} field {key} differs")
    if g1["buffers"][0]["byteLength"] > len(b1):
        raise ValueError("buffer byteLength is larger than the BIN chunk")


def tier(src, dst, size, quality):
    """Converts one .glb. Returns (old bytes, new bytes, [(image name, old size, new size)])."""
    gltf, binary = read_glb(src)
    new, info = {}, []
    for img in gltf.get("images", []):
        name = img.get("name")
        if not name:
            raise ValueError("image without a name")
        old = image_bytes(gltf, binary, name)
        data = resize_image(old, img.get("mimeType", ""), size, quality)
        if data is not old:
            new[name] = data
        info.append((name, img_size(old), img_size(data)))
    out, out_bin = replace_images(gltf, binary, new)
    write_glb(dst, out, out_bin)
    check((gltf, binary), read_glb(dst), new)
    return Path(src).stat().st_size, Path(dst).stat().st_size, info


def main(argv):
    """CLI. Returns the exit code."""
    ap = argparse.ArgumentParser(description="Make lighter .glb copies with smaller textures.")
    ap.add_argument("src", help="folder with the .glb models")
    ap.add_argument("--size", type=int, required=True, help="largest texture side in pixels, e.g. 1024")
    ap.add_argument("--out", required=True, help="output folder (created if missing)")
    ap.add_argument("--quality", type=int, default=90, help="JPEG quality (default 90)")
    a = ap.parse_args(argv)
    src, out = Path(a.src).resolve(), Path(a.out).resolve()
    if not src.is_dir():
        print(f"error: {a.src} is not a folder", file=sys.stderr)
        return 1
    if src == out:
        print("error: --out must differ from the source folder", file=sys.stderr)
        return 1
    if a.size < 1:
        print("error: --size must be at least 1", file=sys.stderr)
        return 1
    files = sorted(src.glob("*.glb"))
    if not files:
        print(f"error: no .glb files in {a.src}", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    for f in files:
        try:
            old, new, info = tier(f, out / f.name, a.size, a.quality)
        except (OSError, ValueError) as err:
            print(f"error: {f.name}: {err}", file=sys.stderr)
            return 1
        faces = f.with_suffix(".faces.json")
        if faces.exists():
            shutil.copyfile(faces, out / faces.name)
        pics = ", ".join(f"{n} {o[0]}x{o[1]} -> {m[0]}x{m[1]}" for n, o, m in info)
        print(f"{f.stem:5} {old / 1000:8.0f} kB -> {new / 1000:8.0f} kB   {pics}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
