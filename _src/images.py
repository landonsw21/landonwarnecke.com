"""Image tool for the portfolio: writes optimized JPEGs into portfolio-media/.

Needs Pillow (python3 -m pip install pillow). macOS only for PDF pages (uses tools/pdfpages.swift)
and HEIC photos (uses sips). Sources are looked up in the ID copy folder; override with LW_ID_COPY.

usage (from the repo root):
  python3 _src/images.py heroes [h_wedge h_axio ...]   re-crop the project card images (all if none named)
  python3 _src/images.py crop KEY X0 Y0 X1 Y1   trim portfolio-media/KEY.jpg in place (fractions 0-1, e.g. to cut slide titles)
  python3 _src/images.py sheet KEY COLS SOURCE... [--width 2400] [--rotate 90] [--gap 64] [--photos] [--aspect 3:4]   combine scanned pages into one sheet
        (cropped to the drawings, even rows); --photos makes a board of whole photos instead (moodboards);
        --aspect center-crops every photo to that shape first, so the board is an even grid; a single source can
        set its own shape as SOURCE@1:1 (e.g. a row of square photos above rows of 3:4 ones) and its own clockwise
        turn as SOURCE@r270 (sideways scans), or both as SOURCE@r90,1:1
  python3 _src/images.py cut KEY PROJECT/file.dxf   a laser-cut DXF as portfolio-media/KEY.svg (sheet outline + part)
  python3 _src/images.py label KEY   a render with part labels in the site's font (Manrope, ink, leader lines),
        from _src/labels/KEY.json: source, output width, text size, the x where label text starts (right side) or
        ends (left side), and per label its text, side, line height y and the point "at" on the part (optional "x" moves
        that label's text), all in output pixels
  python3 _src/images.py add KEY SOURCE [--width 1800] [--rotate 90] [--flip]
        SOURCE: a path, "PROJECT/file name.jpg" (searched inside that ID copy project folder),
                "PDF:PROJECT/deck.pdf:PAGE", "PDFIMG:PROJECT/deck.pdf:OBJ" (an image embedded in a PDF, at its
                own resolution; find OBJ with python3 _src/pdfimg.py deck.pdf OUTDIR), or a .HEIC file.
                --rotate turns it clockwise; --flip mirrors it left to right (e.g. to face the same way as its sketch).
                Transparent sources are flattened onto the site's panel colour.
  then: python3 _src/build.py

Card images are full frames showing one product (the whole photo unless a crop is given below).
A card has two sizes: resting (a band of the image, 384px tall on desktop) and clicked (the whole
image, at its own aspect ratio); hover only undims it. Which band shows while resting is set per project in
content.py (HERO_FOCUS, CSS object-position y); build.py reads each image's aspect ratio itself.
"""
import os, sys, subprocess, tempfile
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = None
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "portfolio-media")
ID_COPY = os.environ.get("LW_ID_COPY", os.path.expanduser("~/Downloads/Claude/ID copy"))
CACHE = os.path.join(tempfile.gettempdir(), "lw-images-cache")
HERO_W = 2400

# key: (source, crop). crop None = the whole photo; otherwise
# (center x, center y, crop width as a fraction of the source width (>1 pads with the backdrop color), aspect ratio w/h)
HEROES = {
    "h_wedge":  ("WEDGE/DSC07293-4.jpg", None),   # the uncropped close-up with napkins
    "h_axio":   ("AXIO/untitled.14.png", None),
    "h_anar":   ("ANAR KARI/Pomegranate.png", None),
    "h_andon":  ("ANDON/DSC07550.jpg", None),   # lit at dusk by the window
    "h_moai":   ("MOAI/untitled.82.png", (0.49, 0.43, 0.75, 1.5)),   # interface face (power, light slider, cooling); the crop starts just above the unit, so with focus 4% a thin band of background shows over it at every card size
    "h_fern":   ("Fern/DSC07676.png", (0.42, 0.56, 0.85, 1.5)),   # painting from the open kit (DSC07706 is soft)
    "h_bubble": ("PDFIMG:Bubble/Bubble.pdf:1063", (0.68, 0.25, 0.8, 1.5)),   # the nightstand render, in on the clock (whole dial fits the resting strip)
}


def find_in_project(project, name):
    base = os.path.join(ID_COPY, project)
    for root, _, files in os.walk(base):
        if name in files:
            return os.path.join(root, name)
    sys.exit(f"not found in {base}: {name}")


def pdf_page(rel, page, width=5200):
    tool = os.path.join(CACHE, "pdfpages")
    os.makedirs(CACHE, exist_ok=True)
    if not os.path.exists(tool):
        subprocess.run(["swiftc", "-O", os.path.join(HERE, "tools", "pdfpages.swift"), "-o", tool], check=True)
    prefix = os.path.join(CACHE, rel.replace("/", "_").replace(" ", "_"))
    out = f"{prefix}_{int(page):02d}.jpg"
    if not os.path.exists(out):
        subprocess.run([tool, os.path.join(ID_COPY, rel), prefix, str(int(page)), str(width)], check=True, capture_output=True)
    return out


def resolve(src):
    if src.startswith("PDF:"):
        _, rel, page = src.split(":")
        return pdf_page(rel, page)
    if src.startswith("PDFIMG:"):   # an image embedded in a PDF, at its own resolution (see pdfimg.py)
        _, rel, obj = src.split(":")
        os.makedirs(CACHE, exist_ok=True)
        out = os.path.join(CACHE, rel.replace("/", "_").replace(" ", "_") + f"_obj{obj}.png")
        if not os.path.exists(out):
            sys.path.insert(0, HERE)
            import pdfimg
            pdfimg.extract(os.path.join(ID_COPY, rel), obj).save(out)
        return out
    if os.path.isabs(src) or os.path.exists(src):
        path = src
    else:
        project, name = src.split("/", 1)
        path = find_in_project(project, name)
    if path.lower().endswith(".heic"):
        os.makedirs(CACHE, exist_ok=True)
        jpg = os.path.join(CACHE, os.path.basename(path)[:-5] + ".jpg")
        if not os.path.exists(jpg):
            subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "95", path, "--out", jpg], check=True, capture_output=True)
        path = jpg
    return path


def flat(im, bg=(236, 231, 224)):
    """RGB on the site's panel colour wherever the source is transparent (cut-out renders, UI screens)."""
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        base = Image.new("RGB", im.size, bg); base.paste(im, mask=im.split()[3])
        return base
    return im.convert("RGB")


QUALITY = {"h_andon": 90, "h_bubble": 90}   # JPEG quality per image (default 80): smoother gradients for these two cards


def save(im, key):
    path = os.path.join(OUT, key + ".jpg")
    im.save(path, quality=QUALITY.get(key, 80), optimize=True, progressive=True)
    print(f"{key}.jpg  {im.width}x{im.height}  {os.path.getsize(path) // 1024} KB")


def crop(im, cx, cy, wf, ar):
    cw = im.width * wf
    ch = cw / ar
    if wf > 1:
        bg = im.getpixel((4, 4))
        canvas = Image.new("RGB", (round(cw), round(max(ch, im.height))), bg)
        canvas.paste(im, (round(cw / 2 - cx * im.width), round((canvas.height - im.height) / 2)))
        y0 = (canvas.height - ch) / 2
        return canvas.crop((0, round(y0), round(cw), round(y0 + ch)))
    if ch > im.height:
        ch = im.height
        cw = ch * ar
    x0 = min(max(cx * im.width - cw / 2, 0), im.width - cw)
    y0 = min(max(cy * im.height - ch / 2, 0), im.height - ch)
    return im.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch)))


def heroes(keys):
    for key in keys or HEROES:
        src, box = HEROES[key]
        c = flat(Image.open(resolve(src)))
        if box:
            c = crop(c, *box)
        if c.width > HERO_W:
            c = c.resize((HERO_W, round(c.height * HERO_W / c.width)), Image.LANCZOS)
        save(c, key)


def add(key, src, width=1800, rotate=0, flip=False):
    im = flat(Image.open(resolve(src)))
    if flip:
        im = ImageOps.mirror(im)
    if rotate:
        im = im.rotate(-rotate, expand=True)
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    save(im, key)


def trim(key, x0, y0, x1, y1):
    path = os.path.join(OUT, key + ".jpg")
    im = Image.open(path).convert("RGB")
    save(im.crop((round(x0 * im.width), round(y0 * im.height), round(x1 * im.width), round(y1 * im.height))), key)


def drawn(im, side=0.02, top=0.01, footer=0.05, pad=0.02):
    """The part of a scanned page that holds drawings. The scanner's edge lines (`side`, `top`) and the
    name + date line along the bottom (`footer`) are painted out, and marks smaller than a few pen
    strokes (pencil specks) don't count toward the crop."""
    page = im.copy()
    sw, th, fh = round(im.width * side), round(im.height * top), round(im.height * footer)
    for box in ((0, 0, im.width, th), (0, im.height - fh, im.width, im.height), (0, 0, sw, im.height), (im.width - sw, 0, im.width, im.height)):
        page.paste((255, 255, 255), box)
    s = 16   # look at the page in 16 px cells; a row or column needs ink in 3+ cells to count
    ink = page.convert("L").point(lambda v: 255 if v < 200 else 0).resize((im.width // s, im.height // s), Image.BOX)
    px, w, h = ink.load(), im.width // s, im.height // s
    rows = [y for y in range(h) if sum(px[x, y] > 60 for x in range(w)) >= 3]
    cols = [x for x in range(w) if sum(px[x, y] > 60 for y in range(h)) >= 3]
    p = round(pad * max(im.width, im.height))
    return page.crop((max(0, cols[0] * s - p), max(0, rows[0] * s - p), min(im.width, (cols[-1] + 1) * s + p), min(im.height, (rows[-1] + 1) * s + p)))


def sheet(key, cols, sources, width=2400, rotate=0, gap=64, margin=40, photos=False, aspect=None):
    """Combine scanned drawing pages into one sheet: each page cropped to its drawings, then set in rows
    of `cols` that fill the width with even gaps (each row's height follows its pages' shapes).
    photos=True: a board of photos instead (kept whole, tight gaps in the site's panel colour)."""
    pages = []
    if photos:
        gap, margin = 16, 0
    for src in sources:
        shape, turn = aspect, rotate
        tail = src.rsplit("@", 1)[1] if "@" in src else ""
        if tail and all(t.startswith("r") or ":" in t for t in tail.split(",")):
            src = src.rsplit("@", 1)[0]
            for t in tail.split(","):
                if t.startswith("r"):
                    turn = int(t[1:])
                else:
                    w, h = t.split(":")
                    shape = float(w) / float(h)
        im = flat(Image.open(resolve(src)))
        if turn:
            im = im.rotate(-turn, expand=True)
        if shape:
            im = crop(im, 0.5, 0.5, 1, shape)
        pages.append(im if photos else drawn(im))
    rows = [pages[i:i + cols] for i in range(0, len(pages), cols)]
    inner = width - 2 * margin
    heights = [(inner - gap * (len(r) - 1)) / sum(p.width / p.height for p in r) for r in rows]
    out = Image.new("RGB", (width, round(2 * margin + sum(heights) + gap * (len(rows) - 1))), (236, 231, 224) if photos else "white")
    y = margin
    for r, h in zip(rows, heights):
        x = margin
        for p in r:
            w = round(h * p.width / p.height)
            out.paste(p.resize((w, round(h)), Image.LANCZOS), (round(x), round(y)))
            x += w + gap
        y += h + gap
    save(out, key)


FONT = os.path.join(HERE, "tools", "fonts", "Manrope[wght].ttf")
INK = (42, 31, 30)


def label(key):
    """A render with labelled parts: each label is text in Manrope Medium with a leader line that runs level from
    the text, then at 45 degrees to a dot on the part (drawn at 2x, then scaled down for smooth lines)."""
    import json
    from PIL import ImageDraw, ImageFont
    spec = json.load(open(os.path.join(HERE, "labels", key + ".json")))
    w, k = spec["width"], 2
    im = flat(Image.open(resolve(spec["source"])))
    im = im.resize((w * k, round(im.height * w * k / im.width)), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(FONT, spec["size"] * k)
    font.set_variation_by_axes([500])
    lw, r, gap = 3 * k, 8 * k, 22 * k
    for lab in spec["labels"]:
        ax, ay = lab["at"][0] * k, lab["at"][1] * k
        y = lab["y"] * k
        right = lab["side"] == "right"
        tx = lab.get("x", spec["text_x"]["right" if right else "left"]) * k
        # 45-degree run from the dot to the label's height, then level to the text
        ex = ax + abs(ay - y) if right else ax - abs(ay - y)
        end = tx - gap if right else tx + gap
        d.line([(ax, ay), (ex, y), (end, y)], fill=INK, width=lw, joint="curve")
        d.ellipse([ax - r, ay - r, ax + r, ay + r], fill=INK)
        d.text((tx, y), lab["text"], font=font, fill=INK, anchor="lm" if right else "rm")
    save(im.resize((w, round(im.height / k)), Image.LANCZOS), key)


def cut(key, dxf):
    """A laser-cut DXF (SPLINE + LINE entities, inches) as an SVG drawing in pomegranate: the sheet outline and the part."""
    path = dxf if os.path.isabs(dxf) or os.path.exists(dxf) else find_in_project(*dxf.split("/", 1))
    lines = open(path, encoding="latin-1").read().splitlines()
    pairs = [(c.strip(), v.strip()) for c, v in zip(lines[0::2], lines[1::2])]
    sec, ents = None, []
    for i, (c, v) in enumerate(pairs):
        if c == "0" and v == "SECTION":
            sec = pairs[i + 1][1]
        elif sec == "ENTITIES":
            if c == "0":
                ents.append((v, {}))
            elif ents:
                ents[-1][1].setdefault(c, []).append(v)

    def point(t, knots, ctrl, p):   # de Boor
        k = p
        while k < len(ctrl) - 1 and not (knots[k] <= t < knots[k + 1]):
            k += 1
        d = [ctrl[j + k - p] for j in range(p + 1)]
        for r in range(1, p + 1):
            for j in range(p, r - 1, -1):
                den = knots[j + 1 + k - r] - knots[j + k - p]
                a = 0 if den == 0 else (t - knots[j + k - p]) / den
                d[j] = ((1 - a) * d[j - 1][0] + a * d[j][0], (1 - a) * d[j - 1][1] + a * d[j][1])
        return d[p]

    segs = []
    for kind, g in ents:
        if kind == "SPLINE":
            knots, p = [float(x) for x in g["40"]], int(g["71"][0])
            ctrl = list(zip(map(float, g["10"]), map(float, g["20"])))
            lo, hi = knots[p], knots[len(ctrl)]
            segs.append([point(lo + (hi - lo) * s / 80, knots, ctrl, p) for s in range(81)])
        elif kind == "LINE":
            segs.append([(float(g["10"][0]), float(g["20"][0])), (float(g["11"][0]), float(g["21"][0]))])
    xs, ys = [x for s in segs for x, _ in s], [y for s in segs for _, y in s]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    edge = lambda s: any(min(abs(x - x0), abs(x - x1), abs(y - y0), abs(y - y1)) < 1e-3 for x, y in s)
    m, u = 0.6, 100   # margin in inches, svg units per inch
    w, h = (x1 - x0 + 2 * m) * u, (y1 - y0 + 2 * m) * u
    d = lambda group: " ".join("M" + " L".join(f"{(x - x0 + m) * u:.1f},{(y1 - y + m) * u:.1f}" for x, y in s) for s in group)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" height="{h:.0f}">'
           f'<rect width="100%" height="100%" fill="#ECE7E0"/><g fill="none" stroke-linecap="round" stroke-linejoin="round">'
           f'<path stroke="#8E2F3A" stroke-width="3" d="{d([s for s in segs if edge(s)])}"/>'
           f'<path stroke="#8E2F3A" stroke-width="4" d="{d([s for s in segs if not edge(s)])}"/></g></svg>')
    open(os.path.join(OUT, key + ".svg"), "w").write(svg)
    print(f"{key}.svg  sheet {x1 - x0:.2f} x {y1 - y0:.2f} in  {len(svg) // 1024} KB")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in ("heroes", "add", "crop", "sheet", "cut", "label"):
        sys.exit(__doc__)
    if args[0] == "heroes":
        heroes(args[1:])
    elif args[0] == "crop":
        if len(args) != 6:
            sys.exit(__doc__)
        trim(args[1], *map(float, args[2:]))
    elif args[0] == "label":
        if len(args) != 2:
            sys.exit(__doc__)
        label(args[1])
    elif args[0] == "cut":
        if len(args) != 3:
            sys.exit(__doc__)
        cut(args[1], args[2])
    elif args[0] == "sheet":
        opts, pos, it = {"--width": 2400, "--rotate": 0, "--gap": 64}, [], iter(args[1:])
        photos, aspect = "--photos" in args, None
        for a in it:
            if a in opts:
                opts[a] = int(next(it))
            elif a == "--aspect":
                w, h = next(it).split(":")
                aspect = float(w) / float(h)
            elif a != "--photos":
                pos.append(a)
        if len(pos) < 3:
            sys.exit(__doc__)
        sheet(pos[0], int(pos[1]), pos[2:], opts["--width"], opts["--rotate"], gap=opts["--gap"], margin=min(40, opts["--gap"]), photos=photos, aspect=aspect)
    else:
        opts = {"--width": 1800, "--rotate": 0}
        pos = []
        it = iter(args[1:])
        for a in it:
            if a in opts:
                opts[a] = int(next(it))
            elif a != "--flip":
                pos.append(a)
        if len(pos) != 2:
            sys.exit(__doc__)
        add(pos[0], pos[1], opts["--width"], opts["--rotate"], flip="--flip" in args)
