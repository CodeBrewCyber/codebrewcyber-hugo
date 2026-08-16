#!/usr/bin/env python3
"""Black out regions of a PNG, and crop/zoom to verify the result.

Pure stdlib on purpose: this Mac has no ImageMagick and no Pillow, and the one
thing you never want mid-publish is to discover your redaction tool is missing.

Redact (in place, one or more boxes as x0,y0,x1,y1):
    redact.py shot.png 1538,244,1730,274

Verify (never skip this, see --inspect note below):
    redact.py shot.png --inspect 1300,220,1800,310 --zoom 4 --out /tmp/crop.png

First-pass coordinates are usually short and leave the tail of a GUID or an
email domain visible, which is exactly the failure that matters. Always
--inspect at 3x to 5x afterward and actually look at the crop.
"""

import sys
import zlib
import struct


def read_png(path):
    data = open(path, 'rb').read()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        sys.exit(f"{path}: not a PNG")
    pos, idat, hdr = 8, b'', None
    while pos < len(data):
        length = struct.unpack('>I', data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if kind == b'IHDR':
            hdr = struct.unpack('>IIBBBBB', chunk)
        elif kind == b'IDAT':
            idat += chunk
        pos += 12 + length
    if hdr is None:
        sys.exit(f"{path}: no IHDR")
    return hdr, zlib.decompress(idat)


def unfilter(raw, width, height, bpp):
    """Undo the per-scanline PNG filters. See RFC 2083 section 6."""
    stride = width * bpp
    out = bytearray()
    prev = bytearray(stride)
    i = 0
    for _ in range(height):
        ftype = raw[i]
        i += 1
        line = bytearray(raw[i:i + stride])
        i += stride
        if ftype == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 255
        elif ftype == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif ftype == 3:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
        elif ftype == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 255
        elif ftype != 0:
            sys.exit(f"unsupported PNG filter type {ftype}")
        out += line
        prev = line
    return out, stride


def write_png(path, width, height, bpp, px, stride):
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (None); we re-encode unfiltered
        raw += px[y * stride:(y + 1) * stride]

    def chunk(kind, payload):
        body = struct.pack('>I', len(payload)) + kind + payload
        return body + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)

    color_type = 6 if bpp == 4 else 2
    ihdr = struct.pack('>IIBBBBB', width, height, 8, color_type, 0, 0, 0)
    blob = b'\x89PNG\r\n\x1a\n'
    blob += chunk(b'IHDR', ihdr)
    blob += chunk(b'IDAT', zlib.compress(bytes(raw), 9))
    blob += chunk(b'IEND', b'')
    open(path, 'wb').write(blob)


def load(path):
    hdr, raw = read_png(path)
    width, height, depth, color_type = hdr[0], hdr[1], hdr[2], hdr[3]
    if depth != 8:
        sys.exit(f"{path}: only 8-bit PNGs supported (got {depth}-bit)")
    if color_type not in (2, 6):
        sys.exit(f"{path}: only RGB/RGBA supported (got color type {color_type})")
    bpp = 4 if color_type == 6 else 3
    px, stride = unfilter(raw, width, height, bpp)
    return width, height, bpp, px, stride


def parse_box(text):
    try:
        x0, y0, x1, y1 = (int(v) for v in text.split(','))
    except ValueError:
        sys.exit(f"bad box '{text}', expected x0,y0,x1,y1")
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    path = args.pop(0)

    inspect = out = None
    zoom = 4
    boxes = []
    while args:
        arg = args.pop(0)
        if arg == '--inspect':
            inspect = parse_box(args.pop(0))
        elif arg == '--zoom':
            zoom = int(args.pop(0))
        elif arg == '--out':
            out = args.pop(0)
        else:
            boxes.append(parse_box(arg))

    width, height, bpp, px, stride = load(path)

    if boxes:
        for (x0, y0, x1, y1) in boxes:
            for y in range(max(0, y0), min(height, y1)):
                base = y * stride
                for x in range(max(0, x0), min(width, x1)):
                    off = base + x * bpp
                    px[off] = px[off + 1] = px[off + 2] = 0
        write_png(path, width, height, bpp, px, stride)
        print(f"redacted {path} ({width}x{height}) boxes={boxes}")

    if inspect:
        if not out:
            sys.exit("--inspect needs --out <path>")
        x0, y0, x1, y1 = inspect
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(width, x1), min(height, y1)
        cw, ch = (x1 - x0) * zoom, (y1 - y0) * zoom
        if cw <= 0 or ch <= 0:
            sys.exit("--inspect region is empty")
        crop = bytearray(cw * ch * bpp)
        cstride = cw * bpp
        for y in range(ch):
            sy = y0 + y // zoom
            for x in range(cw):
                sx = x0 + x // zoom
                src = sy * stride + sx * bpp
                dst = y * cstride + x * bpp
                crop[dst:dst + bpp] = px[src:src + bpp]
        write_png(out, cw, ch, bpp, crop, cstride)
        print(f"wrote {out} ({cw}x{ch}, {zoom}x zoom of {inspect}) - now LOOK at it")


if __name__ == '__main__':
    main()
