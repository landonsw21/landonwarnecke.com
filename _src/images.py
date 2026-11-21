"""Image tool for the portfolio: writes optimized JPEGs into portfolio-media/.

Needs Pillow (python3 -m pip install pillow). macOS only for PDF pages (uses tools/pdfpages.swift)
and HEIC photos (uses sips). Sources are looked up in the ID copy folder; override with LW_ID_COPY.

usage (from the repo root):
  python3 _src/images.py heroes [h_wedge h_axio ...]   re-crop the project card images (all if none named)
  python3 _src/images.py add KEY SOURCE [--width 1800] [--rotate 90]
        SOURCE: a path, "PROJECT/file name.jpg" (searched inside that ID copy project folder),
                "PDF:PROJECT/deck.pdf:PAGE", or a .HEIC file. --rotate turns it clockwise.
  then: python3 _src/build.py

Card images are 2:1 crops centered on one product. In the collapsed card only a band of the crop
shows; which band is set per project in content.py (HERO_FOCUS, CSS object-position y).
"""
import os, sys, subprocess, tempfile
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = None
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "portfolio-media")
ID_COPY = os.environ.get("LW_ID_COPY", os.path.expanduser("~/Downloads/Claude/ID copy"))
CACHE = os.path.join(tempfile.gettempdir(), "lw-images-cache")
AR, HERO_W = 2.0, 2400

# key: (source, center x, center y, crop width as a fraction of the source width; >1 pads with the backdrop color)
HEROES = {
    "h_wedge":  ("WEDGE/DSC07271-2.jpg", 0.47, 0.50, 1.00),
    "h_axio":   ("AXIO/untitled.14.png", 0.50, 0.45, 1.00),
    "h_anar":   ("ANAR KARI/Pomegranate.png", 0.51, 0.60, 0.95),
    "h_andon":  ("ANDON/DSC07529.jpg", 0.52, 0.56, 1.00),
    "h_moai":   ("MOAI/untitled.82.png", 0.55, 0.50, 1.35),
    "h_fern":   ("Fern/DSC07706.png", 0.52, 0.52, 1.00),
    "h_bubble": ("PDF:Bubble/Bubble.pdf:12", 0.653, 0.48, 0.58),
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


def crop(im, cx, cy, wf):
    cw = im.width * wf
    ch = cw / AR
    if wf > 1:
        bg = im.getpixel((4, 4))
        canvas = Image.new("RGB", (round(cw), round(max(ch, im.height))), bg)
        canvas.paste(im, (round(cw / 2 - cx * im.width), round((canvas.height - im.height) / 2)))
        y0 = (canvas.height - ch) / 2
        return canvas.crop((0, round(y0), round(cw), round(y0 + ch)))
    if ch > im.height:
        ch = im.height
        cw = ch * AR
    x0 = min(max(cx * im.width - cw / 2, 0), im.width - cw)
    y0 = min(max(cy * im.height - ch / 2, 0), im.height - ch)
    return im.crop((round(x0), round(y0), round(x0 + cw), round(y0 + ch)))


def heroes(keys):
    for key in keys or HEROES:
        src, cx, cy, wf = HEROES[key]
        im = ImageOps.exif_transpose(Image.open(resolve(src))).convert("RGB")
        c = crop(im, cx, cy, wf)
        if c.width > HERO_W:
            c = c.resize((HERO_W, round(HERO_W / AR)), Image.LANCZOS)
        save(c, key)


def add(key, src, width=1800, rotate=0):
    im = ImageOps.exif_transpose(Image.open(resolve(src))).convert("RGB")
    if rotate:
        im = im.rotate(-rotate, expand=True)
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    save(im, key)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in ("heroes", "add"):
        sys.exit(__doc__)
    if args[0] == "heroes":
        heroes(args[1:])
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
