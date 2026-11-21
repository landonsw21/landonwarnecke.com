"""Image tool for the portfolio: writes optimized JPEGs into portfolio-media/.

Needs Pillow (python3 -m pip install pillow). macOS only for PDF pages (uses tools/pdfpages.swift)
and HEIC photos (uses sips). Sources are looked up in the ID copy folder; override with LW_ID_COPY.

usage (from the repo root):
  python3 _src/images.py heroes [h_wedge h_axio ...]   re-crop the project card images (all if none named)
  python3 _src/images.py crop KEY X0 Y0 X1 Y1   trim portfolio-media/KEY.jpg in place (fractions 0-1, e.g. to cut slide titles)
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
    "h_wedge":  ("WEDGE/DSC07271-2.jpg", None),
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


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in ("heroes", "add", "crop"):
        sys.exit(__doc__)
    if args[0] == "heroes":
        heroes(args[1:])
    elif args[0] == "crop":
        if len(args) != 6:
            sys.exit(__doc__)
        trim(args[1], *map(float, args[2:]))
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
