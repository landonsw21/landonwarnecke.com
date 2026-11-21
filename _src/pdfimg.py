"""Read the raster images embedded in a PDF at their own resolution (no page layout, no slide text).

Used by images.py for sources written "PDFIMG:PROJECT/deck.pdf:OBJ" (OBJ = the image's PDF object number).
`python3 _src/pdfimg.py deck.pdf OUTDIR [MINPX]` dumps every image of at least MINPX on its long side,
named ..._OBJ_WxH.png, so you can find the object number to use. Transparency (SMask) is kept as alpha.
"""
import io, os, re, sys, zlib
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def _index(data):
    objs = {}
    for m in re.finditer(rb"(\d+)\s+0\s+obj\s*<<(.*?)>>\s*stream\r?\n", data, re.S):
        if re.search(rb"/Subtype\s*/Image", m.group(2)):
            objs[int(m.group(1))] = (m.group(2), m.end())
    return objs


def _num(d, key):
    m = re.search(rb"/" + key + rb"\s+(\d+)", d)
    return int(m.group(1)) if m else None


def _unpredict(raw, w, bpp):   # PNG row filters
    stride, out, prev, i = w * bpp, bytearray(), bytearray(w * bpp), 0
    while i < len(raw):
        ft = raw[i]; row = bytearray(raw[i + 1:i + 1 + stride]); i += 1 + stride
        if ft == 2:
            row = bytearray((r + p) & 255 for r, p in zip(row, prev))
        elif ft:
            for x in range(len(row)):
                a = row[x - bpp] if x >= bpp else 0
                b = prev[x]; c = prev[x - bpp] if x >= bpp else 0
                if ft == 1: row[x] = (row[x] + a) & 255
                elif ft == 3: row[x] = (row[x] + ((a + b) >> 1)) & 255
                elif ft == 4:
                    p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    row[x] = (row[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out += row; prev = row
    return bytes(out)


def _decode(data, objs, n):
    d, start = objs[n]
    w, h = _num(d, b"Width"), _num(d, b"Height")
    raw = data[start:data.find(b"endstream", start)].rstrip(b"\r\n")
    if b"DCTDecode" in d:
        im = Image.open(io.BytesIO(raw)); im.load()
        return im.convert("RGB") if im.mode == "CMYK" else im
    if b"FlateDecode" not in d:
        raise ValueError(f"object {n}: unsupported image filter")
    dec = zlib.decompress(raw)
    pred = b"Predictor" in d
    bpp = round(((len(dec) / h - 1) if pred else len(dec) / h) / w)   # channels, from the data size
    if bpp not in (1, 3, 4):
        raise ValueError(f"object {n}: {bpp} channels")
    if pred:
        dec = _unpredict(dec, w, bpp)
    im = Image.frombytes({1: "L", 3: "RGB", 4: "CMYK"}[bpp], (w, h), dec[:w * h * bpp])
    return im.convert("RGB") if bpp == 4 else im


def _with_alpha(data, objs, n):
    im = _decode(data, objs, n)
    sm = re.search(rb"/SMask\s+(\d+)\s+0\s+R", objs[n][0])
    if sm and int(sm.group(1)) in objs:
        a = _decode(data, objs, int(sm.group(1))).convert("L")
        im = im.convert("RGB"); im.putalpha(a if a.size == im.size else a.resize(im.size))
    return im


def extract(pdf, obj):
    data = open(pdf, "rb").read()
    return _with_alpha(data, _index(data), int(obj))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    pdf, out = sys.argv[1], sys.argv[2]
    minpx = int(sys.argv[3]) if len(sys.argv) > 3 else 600
    os.makedirs(out, exist_ok=True)
    data = open(pdf, "rb").read(); objs = _index(data)
    masks = {int(x) for d, _ in objs.values() for x in re.findall(rb"/SMask\s+(\d+)\s+0\s+R", d)}
    base = os.path.splitext(os.path.basename(pdf))[0][:24].replace(" ", "_")
    for n, (d, _) in sorted(objs.items()):
        w, h = _num(d, b"Width"), _num(d, b"Height")
        if n in masks or not w or not h or max(w, h) < minpx:
            continue
        try:
            _with_alpha(data, objs, n).save(os.path.join(out, f"{base}_{n}_{w}x{h}.png"))
        except Exception as e:
            print("skip", n, e)
