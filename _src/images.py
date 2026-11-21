"""Image tool for the portfolio: writes optimized JPEGs into portfolio-media/.

Needs Pillow (python3 -m pip install pillow). macOS only for PDF pages (uses tools/pdfpages.swift)
and HEIC photos (uses sips). Sources are looked up in the ID copy folder; override with LW_ID_COPY.

usage (from the repo root):
  python3 _src/images.py heroes [h_wedge h_axio ...]   re-crop the project card images (all if none named)
  python3 _src/images.py crop KEY X0 Y0 X1 Y1   trim portfolio-media/KEY.jpg in place (fractions 0-1, e.g. to cut slide titles)
  python3 _src/images.py sheet KEY COLS SOURCE... [--width 2400] [--rotate 90]   tile drawing pages into one image
  python3 _src/images.py cut KEY PROJECT/file.dxf   a laser-cut DXF as portfolio-media/KEY.svg (sheet outline + part)
  python3 _src/images.py add KEY SOURCE [--width 1800] [--rotate 90]
        SOURCE: a path, "PROJECT/file name.jpg" (searched inside that ID copy project folder),
                "PDF:PROJECT/deck.pdf:PAGE", or a .HEIC file. --rotate turns it clockwise.
  then: python3 _src/build.py

Card images are full frames showing one product (the whole photo unless a crop is given below).
A card has three sizes: resting (a thin band of the image), hover (2x the band) and clicked (the whole
image, at its own aspect ratio). Which band shows while resting/hovering is set per project in
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
    "h_andon":  ("ANDON/DSC07529.jpg", None),
    "h_moai":   ("MOAI/untitled.82.png", None),
    "h_fern":   ("Fern/DSC07706.png", None),
    "h_bubble": ("PDF:Bubble/Bubble.pdf:12", (0.653, 0.50, 0.62, 1.5)),   # the clock, not the whole bedroom page
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


def save(im, key):
    path = os.path.join(OUT, key + ".jpg")
    im.save(path, quality=80, optimize=True, progressive=True)
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
        c = ImageOps.exif_transpose(Image.open(resolve(src))).convert("RGB")
        if box:
            c = crop(c, *box)
        if c.width > HERO_W:
            c = c.resize((HERO_W, round(c.height * HERO_W / c.width)), Image.LANCZOS)
        save(c, key)


def add(key, src, width=1800, rotate=0):
    im = ImageOps.exif_transpose(Image.open(resolve(src))).convert("RGB")
    if rotate:
        im = im.rotate(-rotate, expand=True)
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    save(im, key)


def trim(key, x0, y0, x1, y1):
    path = os.path.join(OUT, key + ".jpg")
    im = Image.open(path).convert("RGB")
    save(im.crop((round(x0 * im.width), round(y0 * im.height), round(x1 * im.width), round(y1 * im.height))), key)


def sheet(key, cols, sources, width=2400, rotate=0, edge=0.0):
    """Tile several drawing pages into one image, edge to edge on white (`edge` trims that fraction of each page's border)."""
    pages = []
    for src in sources:
        im = ImageOps.exif_transpose(Image.open(resolve(src))).convert("RGB")
        if rotate:
            im = im.rotate(-rotate, expand=True)
        dx, dy = round(im.width * edge), round(im.height * edge)
        pages.append(im.crop((dx, dy, im.width - dx, im.height - dy)))
    cw = width // cols
    ch = round(cw * pages[0].height / pages[0].width)
    rows = (len(pages) + cols - 1) // cols
    out = Image.new("RGB", (cw * cols, ch * rows), "white")
    for i, im in enumerate(pages):
        im.thumbnail((cw, ch), Image.LANCZOS)
        out.paste(im, ((i % cols) * cw + (cw - im.width) // 2, (i // cols) * ch + (ch - im.height) // 2))
    save(out, key)


def cut(key, dxf):
    """A laser-cut DXF (SPLINE + LINE entities, inches) as an SVG drawing: sheet outline in grey, the part in pomegranate."""
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
           f'<path stroke="#B9AEA1" stroke-width="3" d="{d([s for s in segs if edge(s)])}"/>'
           f'<path stroke="#8E2F3A" stroke-width="4" d="{d([s for s in segs if not edge(s)])}"/></g></svg>')
    open(os.path.join(OUT, key + ".svg"), "w").write(svg)
    print(f"{key}.svg  sheet {x1 - x0:.2f} x {y1 - y0:.2f} in  {len(svg) // 1024} KB")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in ("heroes", "add", "crop", "sheet", "cut"):
        sys.exit(__doc__)
    if args[0] == "heroes":
        heroes(args[1:])
    elif args[0] == "crop":
        if len(args) != 6:
            sys.exit(__doc__)
        trim(args[1], *map(float, args[2:]))
    elif args[0] == "cut":
        if len(args) != 3:
            sys.exit(__doc__)
        cut(args[1], args[2])
    elif args[0] == "sheet":
        opts, pos, it = {"--width": 2400, "--rotate": 0}, [], iter(args[1:])
        for a in it:
            if a in opts:
                opts[a] = int(next(it))
            else:
                pos.append(a)
        if len(pos) < 3:
            sys.exit(__doc__)
        sheet(pos[0], int(pos[1]), pos[2:], opts["--width"], opts["--rotate"])
    else:
        opts = {"--width": 1800, "--rotate": 0}
        pos = []
        it = iter(args[1:])
        for a in it:
            if a in opts:
                opts[a] = int(next(it))
            else:
                pos.append(a)
        if len(pos) != 2:
            sys.exit(__doc__)
        add(pos[0], pos[1], opts["--width"], opts["--rotate"])
