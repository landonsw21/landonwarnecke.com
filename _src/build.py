"""Builds the portfolio: writes index.html, site.css and site.js in the repo root.
usage (from the repo root):  python3 _src/build.py
Content lives in _src/content.py, base styles in _src/base.css. Plain Python 3, no packages needed.
"""
import json, os, re, sys, html as H
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content import BIO, PROJECTS, GALLERY, EXTRAS, RESUME, CONTACT, TURNSTILE_SITEKEY, HERO_FOCUS
HERE = os.path.dirname(os.path.abspath(__file__))
BUILD5_CSS = open(os.path.join(HERE, "base.css")).read()

REPO = os.path.dirname(HERE)
MEDIA = "portfolio-media/"


def jpeg_size(path):
    """(width, height) from a JPEG's frame header, so img tags get width/height without any image library."""
    with open(path, "rb") as f:
        data = f.read()
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = int.from_bytes(data[i + 2:i + 4], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + seg
    raise ValueError("no JPEG size in " + path)


META = {}
for _fn in os.listdir(os.path.join(REPO, MEDIA)):
    _key, _ext = os.path.splitext(_fn)
    if _ext not in (".jpg", ".svg"):
        continue
    _path = os.path.join(REPO, MEDIA, _fn)
    if _ext == ".jpg":
        _w, _h = jpeg_size(_path)
    else:   # drawings made by images.py cut: size from the svg's own width/height
        _w, _h = (int(x) for x in __import__("re").search(r'width="(\d+)" height="(\d+)"', open(_path).read()).groups())
    # ?v=<content hash> on every image link, so replacing a file in place still reaches visitors at once
    META[_key] = {"w": _w, "h": _h, "ext": _ext, "v": __import__("hashlib").sha1(open(_path, "rb").read()).hexdigest()[:8]}
FISHEYE = "editor.html"


def e(s):
    return H.escape(s, quote=True)


def img(k, alt, cls="", lazy=True, extra=""):
    m = META.get(k, {})
    wh = f' width="{m["w"]}" height="{m["h"]}"' if m else ""
    load = ' loading="lazy" decoding="async"' if lazy else ' fetchpriority="high"'
    c = f' class="{cls}"' if cls else ""
    v = f'?v={m["v"]}' if m else ""
    return f'<img src="{MEDIA}{k}{m.get("ext", ".jpg")}{v}" alt="{e(alt)}"{wh}{load}{c}{extra}>'


def pad(n):
    return f"{n:02d}"


_PLACEHOLDER = __import__("re").compile(r"\s*\[(?:TO WRITE|TO CONFIRM|TO ADD|PDF LINK TO ADD)[^\]]*\]")


def clean(text):
    """Drop unfinished '[TO WRITE: ...]'-style notes from content.py so they never show on the site."""
    return _PLACEHOLDER.sub("", text).strip()


# ---------- projects ----------
cards = []
for i, p in enumerate(PROJECTS):
    pid = p["id"]
    focus = HERO_FOCUS.get(pid, "50%")
    media = img(p["hero"], p["alt"], "lw-card-img" + (" is-blur" if p.get("soon") else ""), lazy=i > 2)
    hm = META.get(p["hero"], {"w": 2, "h": 1})
    ar = 2.0 if p.get("soon") else hm["w"] / hm["h"]   # clicked card = the whole image at its own shape
    chaps = "".join(f'<a class="lw-chap" href="#{pid}-{s[0]}" data-chap="{pid}-{s[0]}">{e(s[1])}</a>' for s in p["sections"])
    meta = "".join(f'<div><dt class="lw-mono">{e(k.upper())}</dt><dd>{e(clean(v))}</dd></div>' for k, v in p["meta"] if clean(v))
    secs = ""
    for j, (slug, title, paras, imgs, cols) in enumerate(p["sections"]):
        cid = f"{pid}-{slug}"
        body = "".join(f"<p>{clean(t)}</p>" for t in paras if clean(t))
        if imgs:
            cls = f"lw-imgs c{cols}" if cols in (2, 3) and len(imgs) > 1 else "lw-imgs"
            # an image given as (key, alt, "wide") spans both columns
            body += f'<div class="{cls}">' + "".join(img(k, a, "is-wide" if w else "", extra=f' data-lb="{pid}"') for k, a, *w in imgs) + "</div>"
        secs += (f'<section id="{cid}" class="lw-sec" data-chapter="{cid}"><h3>{e(title)}</h3>'
                 f'<div class="lw-sec-body">{body}</div></section>')
    cards.append(
        f'<article id="p-{pid}" class="lw-proj" data-project="{pid}"><div class="lw-unit">'
        f'<button class="lw-card" type="button" aria-expanded="false" aria-controls="d-{pid}" data-toggle="{pid}" style="--fy:{focus};--ar:{ar:.4f}">{media}'
        f'<span class="lw-card-body">'
        f'<span class="lw-card-name">{e(p["name"])}</span><span class="lw-card-line">{e(p["line"])}</span>'
        f'</span></button>'
        f'<div id="d-{pid}" class="lw-drawer" hidden><div class="lw-drawer-in">'
        f'<nav class="lw-chapbar" aria-label="{e(p["name"])} sections"><span class="lw-chapslot" aria-hidden="true"></span><button class="lw-chapname" type="button" data-top="{pid}" tabindex="-1">{e(p["name"])}</button><div class="lw-chaps">{chaps}</div>'
        f'</nav>'
        f'<div class="lw-dbody"><dl class="lw-meta">{meta}</dl>{secs}'
        f'</div></div></div></div></article>')
projects_html = f'<div class="lw-list">{"".join(cards)}</div>'

# ---------- extras ----------
ex = ""
for k, tag, name, desc, url, alt in EXTRAS:
    href = FISHEYE if name == "Fisheye Studio" else url
    ex += (f'<article class="lw-extra"><span class="lw-shade">{img(k, alt)}</span><div class="lw-extra-body">'
           f'<h2>{e(name)}</h2><p>{e(desc)}</p><a class="lw-pill" style="margin-top:auto;align-self:flex-start;color:var(--lw-on-accent)" href="{e(href)}" target="_blank" rel="noopener">Open tool ↗</a></div></article>')
extras_html = f'<div class="lw-two">{ex}</div>'

# ---------- gallery: a grid of tiles; each tile opens its piece as a page in place of the grid ----------
# A page: sticky "← Gallery" bar, the name and one line, then the images in justified rows (each row one height and
# the full column width, so photos of any shape line up uncropped), hero first, then the process in order.
def gslug(label):
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def jrows(keys, target=2.9):
    """Rows of images (in order) whose width/height ratios add up close to `target`. The first row is the hero: a
    landscape image alone, or a portrait or square one together with the next image."""
    ar = [META[k]["w"] / META[k]["h"] for k in keys]
    first = 1 if ar[0] >= 1.2 or len(ar) == 1 else 2
    rest = list(range(first, len(ar)))
    n = len(rest)
    best, back = [0.0] + [float("inf")] * n, [0] * (n + 1)
    for j in range(1, n + 1):
        for i in range(max(0, j - 4), j):
            sm = sum(ar[rest[t]] for t in range(i, j))
            cost = (target - sm) ** 2 * 0.25 if (j == n and sm < target) else (sm - target) ** 2
            if best[i] + cost < best[j]:
                best[j], back[j] = best[i] + cost, i
    cuts, j = [], n
    while j > 0:
        cuts.append((back[j], j))
        j = back[j]
    rows = [list(range(first))] + [rest[i:j] for i, j in reversed(cuts)]
    return [[(keys[t], ar[t]) for t in r] for r in rows], target


def gpage(label, line, items):
    slug, alts = gslug(label), dict(items)
    rows, target = jrows([k for k, _ in items])
    body = ""
    for n, row in enumerate(rows):
        sm = sum(a for _, a in row)
        cap = "" if n == 0 or sm >= 0.75 * target else f' style="max-width:{sm / target * 100:.1f}%"'   # a short last row keeps the row height
        body += f'<div class="lw-jrow"{cap}>' + "".join(img(k, alts[k], extra=f' style="flex:{a:.4f} 1 0" data-lb="g-{slug}"') for k, a in row) + "</div>"
    return (f'<article class="lw-gpage" id="g-{slug}" aria-labelledby="gt-{slug}" hidden>'
            f'<nav class="lw-gbar" aria-label="{e(label)}"><button class="lw-back" type="button" data-gback>← Gallery</button>'
            f'<span class="lw-gbar-name" aria-hidden="true">{e(label)}</span></nav>'
            f'<header class="lw-ghead"><h2 id="gt-{slug}">{e(label)}</h2><p>{e(line)}</p></header>'
            f'<div class="lw-jrows">{body}</div></article>')


def tile(i, label, line, items):
    return (f'<button class="lw-tile" type="button" aria-label="Open {e(label)}" data-gpage="{gslug(label)}">'
            f'{img(items[0][0], items[0][1], "lw-tile-img", lazy=i > 5)}<span class="lw-tile-name">{e(label)}</span></button>')


gallery_html = (f'<div class="lw-tiles">{"".join(tile(i, *g) for i, g in enumerate(GALLERY))}</div>'
                + "".join(gpage(*g) for g in GALLERY))

# ---------- resume ----------
def rrow(r):
    return (f'<div class="lw-rrow"><span class="lw-mono lw-label">{e(r[0])}</span>'
            f'<div style="display:flex;flex-direction:column;gap:4px"><b>{e(clean(r[1]))}</b><small>{e(clean(r[2]))}</small></div></div>')


skills = "".join(f'<div class="lw-rrow" style="grid-template-columns:176px minmax(0,1fr)"><b style="font-size:14px">{e(a)}</b>'
                 f'<span style="font-size:14px;line-height:1.5">{e(b)}</span></div>' for a, b in RESUME["skills"])
pdf = RESUME.get("pdf")
resume_html = ((f'<div class="lw-rtop"><a class="lw-pill" style="color:var(--lw-on-accent)" href="{e(pdf)}" download>Download PDF ↓</a></div>' if pdf else "")
               + '<div class="lw-two" style="gap:48px"><div style="display:flex;flex-direction:column;gap:32px">'
               + f'<section class="lw-rblock"><h2>Education</h2>{"".join(rrow(r) for r in RESUME["education"])}</section>'
               + f'<section class="lw-rblock"><h2>Experience</h2>{"".join(rrow(r) for r in RESUME["experience"])}</section>'
               + f'<section class="lw-rblock"><h2>Activities</h2>{"".join(rrow(r) for r in RESUME["activities"])}</section></div>'
               + '<div style="display:flex;flex-direction:column;gap:32px">'
               + f'<section class="lw-rblock"><h2>Skills</h2>{skills}</section>'
               + f'<section class="lw-rblock"><h2>Languages</h2><p class="lw-rrow" style="display:block;margin:0;font-size:14px;line-height:1.6">{e(RESUME["languages"])}</p></section>'
               + f'<section class="lw-rblock"><h2>Interests</h2><p class="lw-rrow" style="display:block;margin:0;font-size:14px;line-height:1.6">{e(RESUME["interests"])}</p></section></div></div>')

tabs = [("projects", "Projects"), ("extras", "Extras"), ("gallery", "Gallery"), ("resume", "Resume"), ("contact", "Contact")]
tab_btns = "".join(
    f'<button class="lw-tab{" is-active" if k == "projects" else ""}" type="button" data-tab="{k}"{" aria-current=\"page\"" if k == "projects" else ""}>'
    f'<span>{lbl}</span></button>' for i, (k, lbl) in enumerate(tabs))
crows = "".join(
    (f'<a class="lw-crow" href="{e(href)}"{" target=\"_blank\" rel=\"noopener\"" if href.startswith("http") else ""}>'
     f'<span class="lw-mono">{lab}</span><span>{e(val)}</span><span aria-hidden="true">{"↗" if href.startswith("http") else "→"}</span></a>')
    if href else
    (f'<div class="lw-crow"><span class="lw-mono">{lab}</span><span style="color:var(--lw-muted)">{e(val)}</span><span></span></div>')
    for lab, val, href in CONTACT)
cform = (f'<form class="lw-form" id="cform" data-sitekey="{e(TURNSTILE_SITEKEY)}">'
         '<div class="lw-frow">'
         '<label class="lw-field"><span class="lw-mono">NAME</span><input name="name" autocomplete="name" required maxlength="100"></label>'
         '<label class="lw-field"><span class="lw-mono">EMAIL</span><input name="email" type="email" autocomplete="email" required maxlength="200"></label>'
         '</div>'
         '<label class="lw-field"><span class="lw-mono">MESSAGE</span><textarea name="message" rows="6" required maxlength="5000"></textarea></label>'
         '<div class="lw-hp" aria-hidden="true"><label>Leave this empty <input name="company" tabindex="-1" autocomplete="off"></label></div>'
         '<div class="lw-ts" id="cform-ts"></div>'
         '<div class="lw-factions"><button class="lw-send" type="submit">Send message</button>'
         '<p class="lw-fstatus" id="cform-status" role="status" aria-live="polite"></p></div>'
         '<noscript><p class="lw-fstatus">The form needs JavaScript. You can also use the links below.</p></noscript>'
         '</form>')
contact_html = (f'<div class="lw-contact-wrap">{cform}<div class="lw-contact">{crows}</div></div>')
panes = {"projects": projects_html, "contact": contact_html, "extras": extras_html, "gallery": gallery_html, "resume": resume_html}
main = "".join(f'<div class="lw-pane" id="tab-{k}" data-pane="{k}"{"" if k == "projects" else " hidden"}>{panes[k]}</div>' for k, _ in tabs)

def tokenize(c):
    for a, b in [("rgba(236,231,224,.95)", "color-mix(in srgb, var(--lw-panel) 95%, transparent)"),
                 ("rgba(42,31,30,.16)", "color-mix(in srgb, var(--lw-ink) 16%, transparent)"),
                 ("#E4DED5", "var(--lw-bg)"), ("#D4CBBE", "var(--lw-surface)"), ("#ECE7E0", "var(--lw-panel)"),
                 ("#2A1F1E", "var(--lw-ink)"), ("#6A5F58", "var(--lw-muted)"), ("#8E2F3A", "var(--lw-accent)"),
                 ("#D2CABF", "var(--lw-line)"), ("#6E2029", "var(--lw-accent-hover)"), ("#CFC6B8", "var(--lw-surface)"),
                 ("#3A2F2C", "var(--lw-ink)"), ("color:#FFFFFF", "color:var(--lw-on-accent)"),
                 ("#B9AEA1", "var(--lw-line-strong)"), ("#B43C2F", "var(--lw-danger)")]:
        c = c.replace(a, b)
    return c


DESC = "Industrial design portfolio of Landon Warnecke, Western Washington University: product design, CMF and process from research to final."
doc = f'''<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Landon Warnecke · Industrial Design</title>
<meta name="description" content="{e(DESC)}">
<link rel="canonical" href="https://landonwarnecke.com/">
<meta property="og:type" content="website">
<meta property="og:title" content="Landon Warnecke · Industrial Design">
<meta property="og:description" content="{e(DESC)}">
<meta property="og:url" content="https://landonwarnecke.com/">
<meta property="og:image" content="https://landonwarnecke.com/{MEDIA}c_axio.jpg?v={META["c_axio"]["v"]}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#E4DED5">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='22' fill='%238E2F3A'/><text x='50' y='66' font-family='Arial' font-weight='700' font-size='46' fill='%23E4DED5' text-anchor='middle'>LW</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="theme.css">
<link rel="stylesheet" href="site.css">
</head>
<body>
<div class="lw-root">
<a class="lw-skip" href="#main">Skip to content</a>
<div class="lw-shell">
<aside class="lw-side" aria-label="About and navigation">
<div class="lw-id"><button class="lw-me" type="button" data-home aria-label="Back to projects">{img("portrait2", "Portrait of Landon Warnecke", "lw-portrait", lazy=False)}</button>
<div style="display:flex;flex-direction:column;gap:4px;min-width:0"><span class="lw-nm">Landon Warnecke</span></div>
<button class="lw-menu-btn" type="button" aria-expanded="false" aria-controls="lw-menu" aria-label="Open menu" data-menu><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button></div>
<div class="lw-menu" id="lw-menu">
<div class="lw-bio"><p>{e(BIO)}</p></div>
<nav class="lw-tabs" aria-label="Sections">{tab_btns}</nav>
<div class="lw-side-foot"><span style="color:var(--lw-muted)">© 2026 Landon Warnecke</span></div>
</div>
</aside>
<main class="lw-main" id="main">{main}</main>
</div>
<section class="lw-lb" id="lb" aria-label="Image viewer" hidden>
<button class="lw-lb-bg" type="button" data-lbclose aria-label="Close image viewer"></button>
<figure><img id="lb-img" src="" alt=""><figcaption><span class="lw-mono" id="lb-count" style="font-size:12px;color:rgba(255,255,255,.75)"></span><span id="lb-cap"></span></figcaption></figure>
<button class="lw-lbicon" type="button" style="left:24px;top:50%;margin-top:-24px" data-lbstep="-1" aria-label="Previous image">←</button>
<button class="lw-lbicon" type="button" style="right:24px;top:50%;margin-top:-24px" data-lbstep="1" aria-label="Next image">→</button>
<button class="lw-lbicon" type="button" style="right:24px;top:24px" data-lbclose aria-label="Close">×</button>
</section>
</div>
<script src="site.js" defer></script>
</body>
</html>
'''

css = tokenize(BUILD5_CSS) + r"""
body{margin:0; background:#E4DED5; font-family:Manrope, system-ui, sans-serif}
.lw-skip{position:absolute; left:-9999px; top:8px; z-index:2000; padding:12px 16px; border-radius:var(--r-s); background:#2A1F1E; color:#FFFFFF !important}
.lw-skip:focus{left:8px}
.lw-imgs.c2 .is-wide, .lw-imgs.c3 .is-wide{grid-column:1 / -1}
.lw-palette{display:flex; flex-wrap:wrap; gap:16px 32px; padding-top:4px}
.lw-sw{display:grid; grid-template-columns:48px auto; column-gap:12px; align-items:center}
.lw-sw i{grid-row:1 / span 2; width:48px; height:48px; border-radius:var(--r-s); border:1px solid #D2CABF}
.lw-sw b{align-self:end; font-size:16px; line-height:1.25}
.lw-sw small{align-self:start; font-size:12px; line-height:1.35; color:#6A5F58}
.lw-extra img{height:auto}
/* portrait: shown as is; a pomegranate border on hover. Clicking it goes back to Projects (collapsing an open project) */
@media (hover: hover){ .lw-me:hover::after{box-shadow:inset 0 0 0 2px #8E2F3A} }
/* --- project cards: darkened image with the name on top. Two sizes: resting band (384px desktop) and clicked (the whole image);
   hover only lifts the shade and draws the pomegranate outline (no growth) --- */
.lw-proj{padding-bottom:24px; scroll-margin-top:16px}
.lw-proj:last-child{padding-bottom:0}
.lw-unit{container-type:inline-size; border-radius:var(--r-l); outline:2px solid transparent; outline-offset:0; transition:outline-color .2s}
.lw-card{--h:384px; position:relative; display:block; width:100%; height:var(--h); padding:0; border:0; border-radius:var(--r-l); overflow:hidden; background:#2A1F1E; color:#FFFFFF; text-align:left; cursor:pointer; transition:height .5s cubic-bezier(.2,.7,.2,1), border-radius .3s}
.lw-card-img{position:absolute; inset:0; width:100%; height:100%; object-fit:cover; object-position:50% var(--fy, 50%); background:#2A1F1E}
.lw-card-img.is-blur{filter:blur(14px) saturate(.9); transform:scale(1.12)}
.lw-card::before{content:""; position:absolute; inset:0; z-index:1; background:color-mix(in srgb, #2A1F1E 42%, transparent); transition:opacity .5s}
.lw-card::after{content:""; position:absolute; inset:0; z-index:1; background:linear-gradient(to top, color-mix(in srgb, #2A1F1E 88%, transparent) 0, color-mix(in srgb, #2A1F1E 62%, transparent) 34%, transparent 72%)}
.lw-card-body{position:absolute; left:0; right:0; bottom:0; z-index:2; display:flex; flex-direction:row; align-items:baseline; justify-content:flex-start; flex-wrap:nowrap; gap:12px; padding:24px; text-shadow:0 1px 14px color-mix(in srgb, #2A1F1E 45%, transparent)}
.lw-card-name{flex:none; white-space:nowrap; font-size:30px; line-height:1.05; font-weight:700; letter-spacing:-0.03em; color:#FFFFFF}
.lw-card-line{min-width:0; font-size:16px; line-height:1.45; color:#FFFFFF; opacity:.92; white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.lw-card:focus-visible{outline:3px solid #8E2F3A; outline-offset:3px}
@media (hover: hover){
 .lw-proj.is-hover .lw-unit{outline-color:#8E2F3A}
 .lw-proj.is-hover .lw-card::before{opacity:0}
}
.lw-proj.is-open .lw-unit{outline-color:#8E2F3A}
.lw-proj.is-open .lw-card, .lw-proj.is-open:hover .lw-card{height:min(calc(100cqw / var(--ar, 2)), 86svh); border-radius:var(--r-l) var(--r-l) 0 0; transition:height .6s cubic-bezier(.2,.7,.2,1), border-radius .3s}
.lw-proj.is-open .lw-card::before{opacity:0}
/* --- drawer hangs straight off its card and slides open --- */
.lw-drawer{display:grid; grid-template-columns:minmax(0, 1fr); grid-template-rows:0fr; transition:grid-template-rows .55s cubic-bezier(.2,.7,.2,1)}
.lw-drawer.is-open{grid-template-rows:1fr}
.lw-drawer-in{min-height:0; min-width:0; overflow:clip}
.lw-drawer.is-settled .lw-drawer-in{overflow:visible}
/* --- the open project's title never leaves the screen: as you scroll it shrinks, turns dark and lands at the section bar's left end
   (site.js drives it from the scroll position: --p is 0 with the title on the photo, 1 once it is docked in the bar) --- */
.lw-chapbar{--p:0}
.lw-chapslot{position:relative; flex:none; align-self:stretch; width:calc(var(--p) * var(--slot, 0px)); margin-right:calc((var(--p) - 1) * 12px)}
.lw-chapslot::after{content:""; position:absolute; right:0; top:8px; bottom:8px; width:1px; background:#D2CABF; opacity:var(--p)}
.lw-chapname{position:absolute; left:0; top:0; z-index:1; padding:0; border:0; background:none; color:#2A1F1E; font:inherit; font-size:16px; line-height:1.05; font-weight:700; letter-spacing:-0.03em; white-space:nowrap; cursor:pointer; opacity:0; pointer-events:none; transform-origin:0 0}
.lw-chapname::before{content:""; position:absolute; inset:-10px -8px}
.lw-chapbar.is-docked .lw-chapname{pointer-events:auto}
.lw-chapbar.is-docked .lw-chapname:hover{color:#8E2F3A}
@media (max-width: 860px){ .lw-chapname{font-size:14px} }
/* --- portrait: back to Projects / collapses the open project --- */
.lw-me{position:relative; flex:none; padding:0; border:0; background:none; border-radius:var(--r-s); cursor:pointer; line-height:0}
.lw-me::after{content:""; position:absolute; inset:0; border-radius:inherit; box-shadow:inset 0 0 0 2px transparent; transition:box-shadow .2s; pointer-events:none}   /* hover ring drawn inside the photo, so the photo lines up with the tabs */
@media (max-width: 860px){
 .lw-proj{padding-bottom:16px; scroll-margin-top:70px}
 .lw-card{--h:clamp(118px, 18svh, 150px)}
 .lw-card-body{padding:16px; gap:8px}
 .lw-card-name{font-size:24px}
 .lw-card-line{font-size:14px; white-space:normal; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2}
 .lw-me, .lw-me .lw-portrait{border-radius:50%}
}
@media (prefers-reduced-motion: reduce){
 .lw-card, .lw-card::before, .lw-drawer, .lw-proj.is-open .lw-card, .lw-proj.is-open:hover .lw-card{transition:none}
}
/* --- extras share the project-card hover: shade lifts, pomegranate outline, slight grow.
   Touch screens never hover, so they show the images unshaded. --- */
.lw-shade{position:relative; display:block}
.lw-extra{position:relative; outline:2px solid transparent; outline-offset:0; transition:outline-color .2s, transform .3s cubic-bezier(.2,.7,.2,1)}
.lw-extra .lw-pill::after{content:""; position:absolute; inset:0; border-radius:var(--r-l)}
@media (hover: hover){
 .lw-shade::after{content:""; position:absolute; inset:0; background:color-mix(in srgb, #2A1F1E 42%, transparent); transition:opacity .5s; pointer-events:none}
 .lw-extra.is-hover .lw-shade::after{opacity:0}
 .lw-extra.is-hover{outline-color:#8E2F3A; transform:scale(1.02)}
}
/* --- gallery: one even grid of tiles, a short label over a darkened image, same hover as the project cards --- */
.lw-tiles{display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:24px}
.lw-tile{position:relative; display:block; aspect-ratio:4/5; padding:0; border:0; border-radius:var(--r-l); overflow:hidden; background:#2A1F1E; color:#FFFFFF; font:inherit; text-align:left; cursor:pointer; outline:2px solid transparent; outline-offset:0; transition:outline-color .2s, transform .3s cubic-bezier(.2,.7,.2,1)}
/* --- gallery pages --- */
.lw-gpage{display:flex; flex-direction:column}
.lw-gpage[hidden], .lw-tiles[hidden]{display:none}
.lw-gbar{position:sticky; top:0; z-index:4; display:flex; align-items:center; gap:16px; padding:12px 0; background:color-mix(in srgb, #E4DED5 94%, transparent); backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px)}
.lw-back{flex:none; display:inline-flex; align-items:center; min-height:44px; padding:0 16px; border:1px solid #D2CABF; border-radius:var(--r-s); background:transparent; color:#2A1F1E; font:inherit; font-size:14px; font-weight:600; cursor:pointer; transition:border-color .2s, color .2s}
.lw-back:hover{border-color:#8E2F3A; color:#8E2F3A}
.lw-back:focus-visible{outline:3px solid #2A1F1E; outline-offset:2px}
.lw-gbar-name{font-size:16px; font-weight:700; letter-spacing:-0.02em; opacity:0; transform:translateY(4px); transition:opacity .2s, transform .2s}
.lw-gpage.is-docked .lw-gbar-name{opacity:1; transform:none}
.lw-ghead{padding:24px 0 32px}
.lw-ghead h2{margin:0; font-size:30px; line-height:1.1; font-weight:700; letter-spacing:-0.03em}
.lw-ghead p{margin:12px 0 0; max-width:700px; font-size:16px; line-height:1.6; color:#6A5F58}
.lw-jrows{display:flex; flex-direction:column; gap:12px}
.lw-jrow{display:flex; gap:12px}
.lw-jrow img{display:block; width:0; min-width:0; height:auto; border-radius:var(--r-s); background:#D4CBBE; cursor:zoom-in}
@media (max-width: 860px){
 .lw-gbar{top:68px}
 .lw-ghead{padding:16px 0 24px}
 .lw-ghead h2{font-size:24px}
 .lw-jrow{flex-direction:column; max-width:none !important}
 .lw-jrow img{width:100%; flex:none !important}
}
@media (prefers-reduced-motion: reduce){ .lw-gbar-name{transition:none} }
.lw-tile .lw-tile-img{position:absolute; inset:0; width:100%; height:100%; object-fit:cover}
.lw-tile::before{content:""; position:absolute; inset:0; z-index:1; background:color-mix(in srgb, #2A1F1E 42%, transparent); transition:opacity .5s}
.lw-tile::after{content:""; position:absolute; inset:0; z-index:1; background:linear-gradient(to top, color-mix(in srgb, #2A1F1E 80%, transparent) 0, transparent 45%)}
.lw-tile-name{position:absolute; left:24px; right:24px; bottom:24px; z-index:2; font-size:24px; line-height:1.1; font-weight:700; letter-spacing:-0.02em; text-shadow:0 1px 14px color-mix(in srgb, #2A1F1E 60%, transparent)}
@media (hover: hover){
 .lw-tile.is-hover{outline-color:#8E2F3A; transform:scale(1.02)}
 .lw-tile.is-hover::before{opacity:0}
}
@media (max-width: 860px){
 .lw-tiles{grid-template-columns:repeat(2, minmax(0, 1fr)); gap:16px}
 .lw-tile-name{left:16px; right:16px; bottom:16px; font-size:16px}
}
@media (prefers-reduced-motion: reduce){
 .lw-extra, .lw-shade::after, .lw-tile, .lw-tile::before{transition:none}
 .lw-extra.is-hover, .lw-tile.is-hover{transform:none}
}
.lw-contact{display:flex; flex-direction:column; max-width:760px}
.lw-crow{display:grid; grid-template-columns:128px minmax(0,1fr) auto; align-items:center; gap:16px; padding:16px 0; border-top:1px solid #D2CABF; color:#2A1F1E !important; text-decoration:none; font-size:20px; font-weight:600; letter-spacing:-0.01em; overflow-wrap:anywhere}
.lw-crow:last-child{border-bottom:1px solid #D2CABF}
a.lw-crow:hover{color:#8E2F3A !important}
.lw-crow .lw-mono{font-size:12px; font-weight:400; color:#6A5F58; letter-spacing:.08em}
@media (max-width: 860px){
 .lw-crow{grid-template-columns:minmax(0,1fr) auto; font-size:16px; row-gap:4px}
 .lw-crow .lw-mono{grid-column:1 / -1}
}
.lw-contact-wrap{display:flex; flex-direction:column; gap:48px; max-width:760px}
.lw-form{display:flex; flex-direction:column; gap:24px}
.lw-frow{display:grid; grid-template-columns:1fr 1fr; gap:24px}
.lw-field{display:flex; flex-direction:column; gap:8px; min-width:0}
.lw-field .lw-mono{font-size:12px; color:#6A5F58; letter-spacing:.08em}
.lw-field input, .lw-field textarea{font:inherit; font-size:16px; color:#2A1F1E; background:#ECE7E0; border:1px solid #B9AEA1; border-radius:var(--r-s); padding:12px 16px; width:100%; box-sizing:border-box; transition:border-color .15s, box-shadow .15s}
.lw-field textarea{resize:vertical; min-height:150px; line-height:1.5}
.lw-field input:hover, .lw-field textarea:hover{border-color:#6A5F58}
.lw-field input:focus, .lw-field textarea:focus{outline:none; border-color:#8E2F3A; box-shadow:0 0 0 3px color-mix(in srgb, #8E2F3A 22%, transparent)}
.lw-hp{position:absolute; left:-9999px; width:1px; height:1px; overflow:hidden}
.lw-ts:empty{display:none}
.lw-factions{display:flex; align-items:center; gap:16px; flex-wrap:wrap}
.lw-send{font:inherit; font-size:16px; font-weight:700; color:#FFFFFF; background:#8E2F3A; border:0; border-radius:var(--r-s); min-height:48px; padding:0 24px; cursor:pointer; transition:background .15s, transform .15s}
.lw-send:hover{background:#6E2029}
.lw-send:active{transform:scale(.98)}
.lw-send:focus-visible{outline:2px solid #2A1F1E; outline-offset:3px}
.lw-send[disabled]{opacity:.6; cursor:progress}
.lw-fstatus{margin:0; font-size:14px; color:#6A5F58}
.lw-fstatus.is-ok{color:#2A1F1E; font-weight:600}
.lw-fstatus.is-err{color:#B43C2F; font-weight:600}
@media (max-width: 860px){ .lw-frow{grid-template-columns:1fr} }
.lw-rtop{display:flex; justify-content:flex-end; margin-bottom:24px}
[hidden]{display:none !important}
"""

css = tokenize(css).replace("font-family:Manrope, system-ui, sans-serif}", "font-family:var(--lw-font-sans)}")

js = r"""(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var smooth = reduce ? 'auto' : 'smooth';
  var openId = null;

  function scrollToEl(el) { if (el) el.scrollIntoView({ behavior: smooth, block: 'start' }); }

  // ---------- tabs ----------
  function showTab(name, push) {
    $$('.lw-tab').forEach(function (b) {
      var on = b.getAttribute('data-tab') === name;
      b.classList.toggle('is-active', on);
      if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
      var row = b.parentNode;
      if (on && row.scrollWidth > row.clientWidth) row.scrollLeft = b.offsetLeft - row.offsetLeft - 16;
    });
    $$('.lw-pane').forEach(function (p) { p.hidden = p.getAttribute('data-pane') !== name; });
    closeProject(false, true);
    closeG(false);
    setMenu(false);
    if (name === 'contact' && typeof loadTurnstile === 'function') loadTurnstile();
    if (push) history.replaceState(null, '', name === 'projects' ? location.pathname : '#' + name);
    window.scrollTo({ top: 0, behavior: smooth });
  }
  $$('.lw-tab').forEach(function (b) {
    b.addEventListener('click', function () {
      setMenu(false);
      if (!b.classList.contains('is-active')) { showTab(b.getAttribute('data-tab'), true); return; }
      if (openId) { closeProject(true); history.replaceState(null, '', location.pathname); }
      if (gOpen) backToGallery();
    });
  });

  // ---------- phones: tapping the name row (photo, name or arrow) drops the menu (about + tabs) over the page ----------
  var side = $('.lw-side'), menuBtn = $('[data-menu]'), me = $('.lw-me');
  var phone = window.matchMedia('(max-width: 860px)');
  function labelArrow() {
    if (!menuBtn) return;
    var open = side.classList.contains('is-menu');
    menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    menuBtn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  }
  function setMenu(on) { side.classList.toggle('is-menu', on); labelArrow(); }
  function syncPhone() {
    if (!phone.matches) setMenu(false);
    if (me) me.setAttribute('aria-label', phone.matches ? 'Menu' : 'Back to projects');
    labelArrow();
  }
  $('.lw-id').addEventListener('click', function (e) {
    if (!phone.matches) return;   // desktop: the photo goes back to Projects (below)
    e.stopPropagation();
    setMenu(!side.classList.contains('is-menu'));
  });
  document.addEventListener('click', function (e) {   // a tap outside only closes the menu (it doesn't also open what's underneath)
    if (side.classList.contains('is-menu') && !side.contains(e.target)) { e.preventDefault(); e.stopPropagation(); setMenu(false); }
  }, true);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && side.classList.contains('is-menu')) { e.preventDefault(); setMenu(false); if (menuBtn) menuBtn.focus(); }
  });
  if (phone.addEventListener) phone.addEventListener('change', syncPhone);
  syncPhone();

  // ---------- project drawers (one open at a time) ----------
  // The drawer slides open from under its card (grid rows 0fr -> 1fr) and is display:none once closed.
  function setCard(id, open, instant) {
    var art = document.getElementById('p-' + id); if (!art) return;
    var btn = $('.lw-card', art); var d = document.getElementById('d-' + id);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    art.classList.toggle('is-open', open);
    clearTimeout(d._t); d.classList.remove('is-settled');
    if (open) {
      d.hidden = false;
      if (instant || reduce) { d.classList.add('is-open', 'is-settled'); return; }
      void d.offsetHeight;
      d.classList.add('is-open');
      d._t = setTimeout(function () { d.classList.add('is-settled'); }, 600);
    } else {
      d.classList.remove('is-open');
      if (instant || reduce) { d.hidden = true; return; }
      d._t = setTimeout(function () { if (!d.classList.contains('is-open')) d.hidden = true; }, 600);
    }
  }
  function closeProject(scroll, instant) {
    if (!openId) return; var id = openId; setCard(id, false, instant); resetTitle(id); openId = null;
    if (scroll) scrollToEl(document.getElementById('p-' + id));
  }
  function openProject(id, scroll) {
    var art = document.getElementById('p-' + id);
    if (openId && openId !== id) {
      // close the other project instantly, keeping the clicked card where it is on screen
      var before = art.getBoundingClientRect().top;
      setCard(openId, false, true); resetTitle(openId);
      window.scrollBy({ top: art.getBoundingClientRect().top - before, behavior: 'instant' });
    }
    setCard(id, true); openId = id; updateChapters();
    if (scroll !== false) scrollToEl(art);
    history.replaceState(null, '', '#' + id);
  }

  // ---------- desktop: clicking an open project's text or background closes it (images, links, the section bar and
  // other controls keep their own actions; selecting text doesn't close it) ----------
  document.addEventListener('click', function (e) {
    if (!openId || phone.matches || e.defaultPrevented) return;
    var d = document.getElementById('d-' + openId);
    if (!d || !d.contains(e.target)) return;
    if (e.target.closest('a, button, img, input, textarea, select, label, .lw-chapbar')) return;
    if (window.getSelection && String(window.getSelection()).length) return;
    closeProject(true); history.replaceState(null, '', location.pathname);
  });
  // ---------- profile photo: back to Projects (from another tab), else collapse the open project, else to the top ----------
  $$('[data-home]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (phone.matches) return;   // phones: the photo opens the menu instead
      if (!$('.lw-tab[data-tab="projects"]').classList.contains('is-active')) { showTab('projects', true); return; }
      if (openId) { closeProject(true); history.replaceState(null, '', location.pathname); }
      else window.scrollTo({ top: 0, behavior: smooth });
    });
  });
  $$('[data-toggle]').forEach(function (b) {
    b.addEventListener('click', function () {
      var id = b.getAttribute('data-toggle');
      if (openId === id) { closeProject(true); history.replaceState(null, '', location.pathname); } else openProject(id);
    });
  });

  // ---------- chapter bar: highlight the section under the bar ----------
  // ---------- the open project's title shrinks into the section bar as you scroll (it never leaves the screen) ----------
  function lerp(a, b, t) { return a + (b - a) * t; }
  function resetTitle(id) {
    var art = document.getElementById('p-' + id); if (!art) return;
    ['.lw-card-name', '.lw-card-line'].forEach(function (sel) { var el = $(sel, art); if (el) el.style.opacity = ''; });
    var bar = $('.lw-chapbar', art); if (!bar) return;
    bar.style.setProperty('--p', 0); bar.classList.remove('is-docked');
    var name = $('.lw-chapname', bar); name.style.opacity = ''; name.tabIndex = -1;
  }
  function dockTitle(bar) {
    var art = document.getElementById('p-' + openId), card = $('.lw-card', art);
    var title = $('.lw-card-name', art), line = $('.lw-card-line', art), name = $('.lw-chapname', bar);
    var stuck = parseFloat(getComputedStyle(bar).top) || 0;   // where the bar sticks (under the phone header on phones)
    var cr = card.getBoundingClientRect(), br = bar.getBoundingClientRect(), tr = title.getBoundingClientRect();
    var span = Math.min(300, cr.height * 0.5);   // scroll distance over which the title travels into the bar
    var p = Math.max(0, Math.min(1, 1 - (cr.bottom - stuck) / span)), k = p * p * (3 - 2 * p);
    var h = name.offsetHeight;
    bar.style.setProperty('--slot', (name.offsetWidth + 12) + 'px'); bar.style.setProperty('--p', k);
    var x = lerp(tr.left - br.left, parseFloat(getComputedStyle(bar).paddingLeft) || 0, k), y = lerp(tr.top - br.top, (br.height - h) / 2, k), sc = lerp(tr.height / h, 1, k);
    name.style.transform = 'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px) scale(' + sc.toFixed(3) + ')';
    var hs = h * sc, c = Math.max(0, Math.min(1, 0.5 + (y + hs / 2) / hs));   // white while over the photo, dark once inside the bar
    name.style.color = c >= 1 ? '' : 'rgb(' + [Math.round(lerp(255, 42, c)), Math.round(lerp(255, 31, c)), Math.round(lerp(255, 30, c))].join(',') + ')';
    name.style.textShadow = c >= 1 ? '' : '0 1px 14px rgba(42,31,30,' + (0.6 * (1 - c)).toFixed(2) + ')';
    var moving = p > 0;
    name.style.opacity = moving ? 1 : 0; title.style.opacity = moving ? 0 : '';
    if (line) line.style.opacity = moving ? Math.max(0, 0.92 * (1 - p * 2.5)).toFixed(2) : '';
    bar.classList.toggle('is-docked', p >= 1); name.tabIndex = p >= 1 ? 0 : -1;
  }
  window.addEventListener('resize', function () { updateChapters(); });
  function updateChapters() {
    if (!openId) return;
    var d = document.getElementById('d-' + openId); if (!d || d.hidden) return;
    var bar = $('.lw-chapbar', d); var line = bar.getBoundingClientRect().bottom + 24;
    dockTitle(bar);
    var secs = $$('[data-chapter]', d); var cur = secs[0];
    secs.forEach(function (s) { if (s.getBoundingClientRect().top <= line) cur = s; });
    var id = cur && cur.getAttribute('data-chapter');
    $$('.lw-chap', d).forEach(function (a) {
      var on = a.getAttribute('data-chap') === id; a.classList.toggle('is-active', on);
      if (on && a.scrollIntoView && a.parentNode.scrollWidth > a.parentNode.clientWidth) {
        var p = a.parentNode; var l = a.offsetLeft - p.clientWidth / 2 + a.clientWidth / 2; p.scrollTo({ left: l, behavior: smooth });
      }
    });
  }
  var ticking = false;
  window.addEventListener('scroll', function () {
    if (ticking) return; ticking = true;
    requestAnimationFrame(function () { ticking = false; updateChapters(); });
  }, { passive: true });
  $$('.lw-chap').forEach(function (a) {
    a.addEventListener('click', function (ev) { ev.preventDefault(); scrollToEl(document.getElementById(a.getAttribute('data-chap'))); });
  });
  $$('.lw-chapname').forEach(function (b) {
    b.addEventListener('click', function () { scrollToEl(document.getElementById('p-' + b.getAttribute('data-top'))); });
  });

  // ---------- lightbox ----------
  var lb = $('#lb'), lbImg = $('#lb-img'), lbCap = $('#lb-cap'), lbCount = $('#lb-count');
  var list = [], idx = 0, lastFocus = null;
  function render() {
    var im = list[idx]; lbImg.src = im.src; lbImg.alt = im.alt; lbCap.textContent = im.alt; lbCount.textContent = (idx + 1) + ' / ' + list.length;
    var single = list.length < 2; lbCount.hidden = single; $$('[data-lbstep]', lb).forEach(function (b) { b.hidden = single; });
  }
  function openList(items, i, from) {
    list = items; if (!list.length) return; idx = i; lastFocus = from || document.activeElement; render(); lb.hidden = false;
    $('[data-lbclose]', lb).focus({ preventScroll: true });
  }
  function openLb(group, i, from) {
    openList($$('img[data-lb="' + group + '"]').map(function (im) { return { src: im.currentSrc || im.src, alt: im.alt }; }), i, from);
  }
  function closeLb() { lb.hidden = true; if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true }); }
  function step(dlt) { idx = (idx + dlt + list.length) % list.length; render(); }
  $$('.lw-imgs img[data-lb], .lw-jrow img[data-lb]').forEach(function (im) {
    im.addEventListener('click', function () {
      var g = im.getAttribute('data-lb'); var all = $$('img[data-lb="' + g + '"]'); openLb(g, all.indexOf(im), im);
    });
  });
  $$('[data-lbclose]').forEach(function (b) { b.addEventListener('click', closeLb); });
  $$('[data-lbstep]').forEach(function (b) { b.addEventListener('click', function () { step(Number(b.getAttribute('data-lbstep'))); }); });
  document.addEventListener('keydown', function (ev) {
    if (lb.hidden) return;
    if (ev.key === 'Escape') { ev.preventDefault(); closeLb(); } else if (ev.key === 'ArrowRight') step(1); else if (ev.key === 'ArrowLeft') step(-1);
  });

  // ---------- contact form (Cloudflare Worker at /api/contact + Turnstile) ----------
  var form = $('#cform'), tsId = null, tsLoading = false;
  var sitekey = form ? form.getAttribute('data-sitekey') : '';
  var tsReady = /^[0-9]x[A-Za-z0-9_-]{10,}$/.test(sitekey);
  function loadTurnstile() {
    if (!form || !tsReady || tsLoading) return; tsLoading = true;
    window.lwTurnstile = function () {
      tsId = window.turnstile.render('#cform-ts', { sitekey: sitekey, action: 'contact', theme: 'light', appearance: 'interaction-only', size: 'flexible' });
    };
    var s = document.createElement('script');
    s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit&onload=lwTurnstile';
    s.async = true; s.defer = true; document.head.appendChild(s);
  }
  function tsToken() {
    return new Promise(function (resolve) {
      var t0 = Date.now();
      (function poll() {
        var t = (window.turnstile && tsId !== null) ? window.turnstile.getResponse(tsId) : '';
        if (t || Date.now() - t0 > 8000) resolve(t || ''); else setTimeout(poll, 250);
      })();
    });
  }
  if (form) {
    var status = $('#cform-status'), send = $('.lw-send', form);
    var say = function (msg, kind) { status.textContent = msg; status.className = 'lw-fstatus' + (kind ? ' is-' + kind : ''); };
    form.addEventListener('focusin', loadTurnstile);
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      if (!tsReady) { say('The form isn’t switched on yet. Please use one of the links below.', 'err'); return; }
      send.disabled = true; say('Sending…');
      loadTurnstile();
      tsToken().then(function (token) {
        if (!token) throw new Error('Couldn’t verify you’re human. Please try again.');
        var f = form.elements;
        return fetch('/api/contact', {
          method: 'POST', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ name: f.name.value, email: f.email.value, message: f.message.value, company: f.company.value, token: token })
        }).then(function (r) {
          return r.json().catch(function () { return {}; }).then(function (d) {
            if (!r.ok || !d.ok) throw new Error(d.error || 'Something went wrong. Please try again, or use one of the links below.');
          });
        });
      }).then(function () {
        form.reset(); say('Thanks! Your message was sent.', 'ok');
      }).catch(function (err) {
        say(err && err.message && err.message !== 'Failed to fetch' ? err.message : 'Couldn’t send right now. Please try again, or use one of the links below.', 'err');
      }).then(function () {
        send.disabled = false;
        if (window.turnstile && tsId !== null) window.turnstile.reset(tsId);
      });
    });
  }

  // ---------- hover that keeps up with scrolling: browsers only re-check :hover once a scroll (e.g. a trackpad swipe)
  // ends, so the card under a still cursor lit up late. The script keeps .is-hover on the project card, gallery tile or
  // extra under the mouse, checking again on every scroll frame. ----------
  var HOVERABLE = '.lw-proj, .lw-tile, .lw-extra', px = -1, py = -1, hovered = null, hoverQueued = false;
  function setHover(el) {
    if (el === hovered) return;
    if (hovered) hovered.classList.remove('is-hover');
    hovered = el; if (el) el.classList.add('is-hover');
  }
  function hoverAt() {
    hoverQueued = false;
    if (px < 0) return setHover(null);
    var t = document.elementFromPoint(px, py);
    setHover(t && t.closest ? t.closest(HOVERABLE) : null);
  }
  document.addEventListener('pointermove', function (e) {
    if (e.pointerType !== 'mouse') return;
    px = e.clientX; py = e.clientY; hoverAt();
  }, { passive: true });
  window.addEventListener('scroll', function () {
    if (px >= 0 && !hoverQueued) { hoverQueued = true; requestAnimationFrame(hoverAt); }
  }, { passive: true });
  document.documentElement.addEventListener('mouseleave', function () { px = -1; setHover(null); });

  // ---------- gallery pages: a tile opens its piece in place of the grid; "← Gallery", Esc, the browser's back
  // button or the Gallery tab return to the grid, scrolled to where it was ----------
  var gTiles = $('.lw-tiles'), gOpen = null, gY = 0, gPushed = false;
  function openG(slug, push) {
    var pg = document.getElementById('g-' + slug); if (!pg || !gTiles) return;
    if (gOpen && gOpen !== slug) document.getElementById('g-' + gOpen).hidden = true;
    if (!gOpen) gY = window.scrollY;
    gTiles.hidden = true; pg.hidden = false; pg.classList.remove('is-docked'); gOpen = slug;
    if (push) { history.pushState({ g: slug }, '', '#gallery/' + slug); gPushed = true; }
    window.scrollTo(0, 0);
    $('[data-gback]', pg).focus({ preventScroll: true });
  }
  function closeG(restore) {
    if (!gOpen) return;
    var slug = gOpen; document.getElementById('g-' + slug).hidden = true; gTiles.hidden = false; gOpen = null; gPushed = false;
    if (restore) { window.scrollTo(0, gY); var t = $('[data-gpage="' + slug + '"]'); if (t) t.focus({ preventScroll: true }); }
  }
  function backToGallery() {
    if (!gOpen) return;
    if (gPushed) { history.back(); return; }          // the popstate below closes the page
    history.replaceState(null, '', '#gallery'); closeG(true);
  }
  $$('[data-gpage]').forEach(function (b) { b.addEventListener('click', function () { openG(b.getAttribute('data-gpage'), true); }); });
  $$('[data-gback]').forEach(function (b) { b.addEventListener('click', backToGallery); });
  window.addEventListener('popstate', function () {
    var m = location.hash.match(/^#gallery\/(.+)$/);
    if (m) { if (!$('[data-pane="gallery"]').hidden) openG(m[1], false); else { showTab('gallery', false); openG(m[1], false); } }
    else if (gOpen) closeG(true);
  });
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && gOpen && !ev.defaultPrevented) backToGallery();
  });
  if ('IntersectionObserver' in window) {                 // the name docks into the bar once the heading has scrolled under it
    $$('.lw-gpage').forEach(function (pg) {
      new IntersectionObserver(function (es) { pg.classList.toggle('is-docked', !es[0].isIntersecting); },
        { rootMargin: (phone.matches ? '-136px' : '-68px') + ' 0px 0px 0px' }).observe($('.lw-ghead h2', pg));
    });
  }

  // ---------- deep links: #gallery, #gallery/<piece>, #resume, #extras, #axio ----------
  function route() {
    var h = location.hash.replace('#', '');
    if (!h) return;
    var gm = h.match(/^gallery\/(.+)$/);
    if (gm) { showTab('gallery', false); openG(gm[1], false); return; }
    if (['extras', 'gallery', 'resume', 'contact', 'projects'].indexOf(h) >= 0) { showTab(h, false); return; }
    if (document.getElementById('p-' + h)) { openProject(h); }
  }
  route();
})();
"""

# Version each stylesheet/script link by its content so a new deploy is never masked by a cached old file.
import hashlib
def _ver(text):
    return hashlib.sha1(text.encode()).hexdigest()[:10]
for _old, _new in [('href="theme.css"', 'href="theme.css?v=' + _ver(open(os.path.join(REPO, "theme.css")).read()) + '"'),
                   ('href="site.css"', 'href="site.css?v=' + _ver(css) + '"'),
                   ('src="site.js"', 'src="site.js?v=' + _ver(js) + '"')]:
    assert doc.count(_old) == 1, _old
    doc = doc.replace(_old, _new)
open(os.path.join(REPO, "index.html"), "w").write(doc)
open(os.path.join(REPO, "site.css"), "w").write(css)
open(os.path.join(REPO, "site.js"), "w").write(js)
print("index.html", len(doc), "site.css", len(css), "site.js", len(js))
