# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Haxinpro
"""Adds XMP rights metadata (creator, rights, licence URL) to WebP files. Standard library only.

  python3 tools/stamp_xmp.py dice/results/d20/*.webp dice/icons/*.webp

A WebP is a RIFF file: "RIFF" <size> "WEBP" followed by chunks (4-letter name, 4-byte little-endian size, payload, one zero byte
if the size is odd). Metadata needs the extended layout, whose first chunk "VP8X" holds the flags and the canvas size. A simple
file (a lone "VP8 " lossy or "VP8L" lossless chunk) is converted to that layout first. Running it again replaces the old XMP."""
import os
import struct
import sys
from pathlib import Path
from xml.sax.saxutils import escape

CREATOR = "Haxinpro"
RIGHTS = "© Haxinpro, CC BY 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by/4.0/"        # LICENSE-ASSETS.md
ALPHA_FLAG, XMP_FLAG = 0x10, 0x04                                   # bits of the first VP8X byte


def xmp_packet():
    """The XMP document (UTF-8): dc:creator, dc:rights and xmpRights:WebStatement (the licence URL), in an xpacket wrapper."""
    return f"""<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:xmpRights="http://ns.adobe.com/xap/1.0/rights/">
   <dc:creator><rdf:Seq><rdf:li>{escape(CREATOR)}</rdf:li></rdf:Seq></dc:creator>
   <dc:rights><rdf:Alt><rdf:li xml:lang="x-default">{escape(RIGHTS)}</rdf:li></rdf:Alt></dc:rights>
   <xmpRights:Marked>True</xmpRights:Marked>
   <xmpRights:WebStatement>{escape(LICENCE_URL)}</xmpRights:WebStatement>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>""".encode("utf-8")


def read_chunks(data):
    """[(name, payload)] of a WebP file, checking the RIFF header and that no chunk runs past the end."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("not a WebP file")
    end = 8 + struct.unpack_from("<I", data, 4)[0]
    if end > len(data):
        raise ValueError("truncated file")
    pos, out = 12, []
    while pos + 8 <= end:
        name, size = struct.unpack_from("<4sI", data, pos)
        if pos + 8 + size > end:
            raise ValueError("truncated chunk")
        out.append((name, data[pos + 8:pos + 8 + size]))
        pos += 8 + size + (size & 1)                # payloads are padded to an even length
    return out


def pack_chunk(name, payload):
    """One chunk as bytes, with the pad byte for an odd payload."""
    return name + struct.pack("<I", len(payload)) + payload + b"\0" * (len(payload) & 1)


def simple_size(name, payload):
    """(width, height, has_alpha) of a simple "VP8 " (lossy, never alpha) or "VP8L" (lossless) image chunk."""
    if name == b"VP8 " and len(payload) >= 10 and payload[3:6] == b"\x9d\x01\x2a":      # keyframe start code
        w, h = struct.unpack_from("<HH", payload, 6)
        return w & 0x3FFF, h & 0x3FFF, False                                            # 14 bits each (the top 2 are scaling)
    if name == b"VP8L" and len(payload) >= 5 and payload[0] == 0x2F:                    # signature byte
        bits = struct.unpack_from("<I", payload, 1)[0]
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1, bool(bits >> 28 & 1)   # width-1, height-1, alpha, version
    raise ValueError("unknown image data")


def stamp(data):
    """The WebP bytes with a VP8X header carrying the XMP flag and a fresh "XMP " chunk at the end."""
    chunks = read_chunks(data)
    if not chunks:
        raise ValueError("no chunks")
    if chunks[0][0] == b"VP8X":                     # already extended: keep its flags and sizes, add the XMP bit
        head = bytearray(chunks[0][1])
        if len(head) != 10:
            raise ValueError("bad VP8X chunk")
        head[0] |= XMP_FLAG
        rest = chunks[1:]
    else:                                           # simple file: build the VP8X from the image's own header
        w, h, alpha = simple_size(*chunks[0])
        head = bytearray([XMP_FLAG | (ALPHA_FLAG if alpha else 0), 0, 0, 0])            # flags, 3 reserved bytes
        head += (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")           # canvas size minus one
        rest = chunks
    rest = [c for c in rest if c[0] != b"XMP "] + [(b"XMP ", xmp_packet())]
    body = b"WEBP" + b"".join(pack_chunk(n, p) for n, p in [(b"VP8X", bytes(head))] + rest)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def main(paths):
    """Stamps every file in place (written next to it first, then moved over it). Returns the number of failures."""
    if not paths:
        print(__doc__)
        return 1
    failed = 0
    for path in map(Path, paths):
        try:
            new = stamp(path.read_bytes())
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(new)
            os.replace(tmp, path)
            print(f"stamped {path}")
        except (OSError, ValueError) as err:
            failed += 1
            print(f"skipped {path}: {err}", file=sys.stderr)
    return failed


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1:]) else 0)
