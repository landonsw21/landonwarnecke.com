"""Builds the portfolio: writes index.html, site.css and site.js in the repo root.
usage (from the repo root):  python3 _src/build.py
Content lives in _src/content.py, base styles in _src/base.css. Plain Python 3, no packages needed.
"""
import json, os, sys, html as H
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
    if _fn.endswith(".jpg"):
        _path = os.path.join(REPO, MEDIA, _fn)
        _w, _h = jpeg_size(_path)
        # ?v=<content hash> on every image link, so replacing a file in place still reaches visitors at once
        META[_fn[:-4]] = {"w": _w, "h": _h, "v": __import__("hashlib").sha1(open(_path, "rb").read()).hexdigest()[:8]}
FISHEYE = "editor.html"


def e(s):
    return H.escape(s, quote=True)


def img(k, alt, cls="", lazy=True, extra=""):
    m = META.get(k, {})
    wh = f' width="{m["w"]}" height="{m["h"]}"' if m else ""
    load = ' loading="lazy" decoding="async"' if lazy else ' fetchpriority="high"'
    c = f' class="{cls}"' if cls else ""
    v = f'?v={m["v"]}' if m else ""
    return f'<img src="{MEDIA}{k}.jpg{v}" alt="{e(alt)}"{wh}{load}{c}{extra}>'


def pad(n):
    return f"{n:02d}"


def head_block(label, title, sub, right=""):
    return (f'<header class="lw-head"><div style="display:flex;flex-direction:column;gap:10px;max-width:640px">'
            f'<span class="lw-mono lw-label">{label}</span><h1 class="lw-h1">{title}</h1>{f'<p class="lw-sub">{sub}</p>' if sub else ''}</div>{right}</header>')


# ---------- projects ----------
cards = []
for i, p in enumerate(PROJECTS):
    pid = p["id"]
    nxt = PROJECTS[(i + 1) % len(PROJECTS)]
    focus = HERO_FOCUS.get(pid, "50%")
    media = img(p["hero"], p["alt"], "lw-card-img" + (" is-blur" if p.get("soon") else ""), lazy=i > 2)
    hm = META.get(p["hero"], {"w": 2, "h": 1})
    ar = 2.0 if p.get("soon") else hm["w"] / hm["h"]   # clicked card = the whole image at its own shape
    chaps = "".join(f'<a class="lw-chap" href="#{pid}-{s[0]}" data-chap="{pid}-{s[0]}">{e(s[1])}</a>' for s in p["sections"])
    meta = "".join(f'<div><dt class="lw-mono">{e(k.upper())}</dt><dd>{e(v)}</dd></div>' for k, v in p["meta"])
    secs = ""
    for j, (slug, title, paras, imgs, cols) in enumerate(p["sections"]):
        cid = f"{pid}-{slug}"
        body = "".join(f"<p>{t}</p>" for t in paras)
        if imgs:
            cls = "lw-imgs c2" if cols == 2 and len(imgs) > 1 else "lw-imgs"
            body += f'<div class="{cls}">' + "".join(img(k, a, extra=f' data-lb="{pid}"') for k, a in imgs) + "</div>"
        secs += (f'<section id="{cid}" class="lw-sec" data-chapter="{cid}"><div style="display:flex;flex-direction:column;gap:6px">'
                 f'<span class="lw-mono lw-label">{pad(j + 1)}</span><h3>{e(title)}</h3></div><div class="lw-sec-body">{body}</div></section>')
    cards.append(
        f'<article id="p-{pid}" class="lw-proj" data-project="{pid}"><div class="lw-unit">'
        f'<button class="lw-card" type="button" aria-expanded="false" aria-controls="d-{pid}" data-toggle="{pid}" style="--fy:{focus};--ar:{ar:.4f}">{media}'
        f'<span class="lw-card-body">'
        f'<span class="lw-card-name">{e(p["name"])}</span><span class="lw-card-line">{e(p["line"])}</span>'
        f'</span></button>'
        f'<div id="d-{pid}" class="lw-drawer" hidden><div class="lw-drawer-in">'
        f'<nav class="lw-chapbar" aria-label="{e(p["name"])} sections"><div class="lw-chaps">{chaps}</div>'
        f'<button class="lw-close" type="button" data-toggle="{pid}" aria-label="Close {e(p["name"])}">Close ×</button></nav>'
        f'<div class="lw-dbody"><dl class="lw-meta">{meta}</dl>{secs}'
        f'<div class="lw-dfoot"><button class="lw-ghost" type="button" data-toggle="{pid}">Close project ↑</button>'
        f'<button class="lw-pill" type="button" data-next="{nxt["id"]}">Next: {e(nxt["name"])} →</button></div></div></div></div></div></article>')
projects_html = (head_block("SELECTED WORK · 2024–2026", "Selected work",
                            "Seven case studies and one project in progress. Open any project for the full story, from research to final.")
                 + f'<div class="lw-list">{"".join(cards)}</div>')

# ---------- extras ----------
ex = ""
for k, tag, name, desc, url, alt in EXTRAS:
    href = FISHEYE if name == "Fisheye Studio" else url
    ex += (f'<article class="lw-extra">{img(k, alt)}<div class="lw-extra-body"><span class="lw-mono" style="font-size:12px">{e(tag)}</span>'
           f'<h2>{e(name)}</h2><p>{e(desc)}</p><a class="lw-pill" style="margin-top:auto;align-self:flex-start;color:var(--lw-on-accent)" href="{e(href)}" target="_blank" rel="noopener">Open tool ↗</a></div></article>')
extras_html = head_block("EXTRAS", "Tools I’ve built", "Small tools I made for my own process, free to try in your browser.") + f'<div class="lw-two">{ex}</div>'

# ---------- gallery ----------
gs = ""
for gi, (gid, title, items) in enumerate(GALLERY):
    cards_g = "".join(
        f'<button class="lw-gcard" type="button" aria-label="View {e(cap)}" data-lbopen="{gid}" data-i="{i}">'
        f'{img(k, cap, extra=f" data-lb=\"{gid}\"")}<span class="lw-gcap"><span class="lw-mono lw-label" style="padding-top:2px">{pad(i + 1)}</span><span>{e(cap)}</span></span></button>'
        for i, (k, cap) in enumerate(items))
    gs += (f'<section class="lw-gsec" aria-labelledby="g-{gid}"><div class="lw-ghead"><div style="display:flex;flex-direction:column;gap:6px">'
           f'<span class="lw-mono lw-label">{pad(gi + 1)} · {len(items)} PIECES</span><h2 id="g-{gid}">{e(title)}</h2></div>'
           f'<div style="display:flex;gap:8px"><button class="lw-icon" type="button" data-row="{gid}" data-dir="-1" aria-label="Scroll {e(title)} left">←</button>'
           f'<button class="lw-icon" type="button" data-row="{gid}" data-dir="1" aria-label="Scroll {e(title)} right">→</button></div></div>'
           f'<div class="lw-row" id="row-{gid}">{cards_g}</div><div class="lw-track"><div id="prog-{gid}" style="width:6%"></div></div></section>')
gallery_html = (head_block("GALLERY", "Gallery", "Drawings, making and smaller projects. Drag, swipe or use the arrows; tap any piece to view it large.")
                + f'<div style="display:flex;flex-direction:column;gap:48px">{gs}</div>')

# ---------- resume ----------
def rrow(r):
    return (f'<div class="lw-rrow"><span class="lw-mono lw-label" style="padding-top:3px">{e(r[0])}</span>'
            f'<div style="display:flex;flex-direction:column;gap:3px"><b>{e(r[1])}</b><small>{e(r[2])}</small></div></div>')


skills = "".join(f'<div class="lw-rrow" style="grid-template-columns:170px minmax(0,1fr)"><b style="font-size:14px">{e(a)}</b>'
                 f'<span style="font-size:15px;line-height:1.5">{e(b)}</span></div>' for a, b in RESUME["skills"])
dl = ('<div style="display:flex;flex-direction:column;align-items:flex-end;gap:6px"><a class="lw-pill" style="color:var(--lw-on-accent)" href="#resume">Download PDF ↓</a>'
      '<span class="lw-mono lw-label" style="font-size:11px">[PDF LINK TO ADD]</span></div>')
resume_html = (head_block("RESUME", "Resume", "Industrial design student at Western Washington University. [TO CONFIRM: graduation year]", dl)
               + '<div class="lw-two" style="gap:40px"><div style="display:flex;flex-direction:column;gap:36px">'
               + f'<section class="lw-rblock"><h2>Education</h2>{"".join(rrow(r) for r in RESUME["education"])}</section>'
               + f'<section class="lw-rblock"><h2>Experience</h2>{"".join(rrow(r) for r in RESUME["experience"])}</section>'
               + f'<section class="lw-rblock"><h2>Activities</h2>{"".join(rrow(r) for r in RESUME["activities"])}</section></div>'
               + '<div style="display:flex;flex-direction:column;gap:36px">'
               + f'<section class="lw-rblock"><h2>Skills</h2>{skills}</section>'
               + f'<section class="lw-rblock"><h2>Languages</h2><p class="lw-rrow" style="display:block;margin:0;font-size:15px">{e(RESUME["languages"])}</p></section>'
               + f'<section class="lw-rblock"><h2>Interests</h2><p class="lw-rrow" style="display:block;margin:0;font-size:15px;line-height:1.55">{e(RESUME["interests"])}</p></section></div></div>')

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
contact_html = (head_block("CONTACT", "Contact me", "")
                + f'<div class="lw-contact-wrap">{cform}<div class="lw-contact">{crows}</div></div>')
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
<div class="lw-id"><button class="lw-me" type="button" data-collapse disabled aria-label="Collapse the open project">{img("portrait2", "Portrait of Landon Warnecke", "lw-portrait", lazy=False)}<span class="lw-me-badge" aria-hidden="true">−</span></button>
<div style="display:flex;flex-direction:column;gap:4px;min-width:0"><span class="lw-nm">Landon Warnecke</span><span class="lw-role">Industrial Design · Western Washington University</span></div>
<button class="lw-about-toggle" type="button" aria-expanded="false" data-about>About me</button></div>
<div class="lw-bio"><span class="lw-mono lw-label">ABOUT ME</span><p>{e(BIO)}</p></div>
<nav class="lw-tabs" aria-label="Sections">{tab_btns}</nav>
<div class="lw-side-foot"><span style="font-size:13px;color:var(--lw-muted)">© 2026 Landon Warnecke</span></div>
</aside>
<main class="lw-main" id="main">{main}</main>
</div>
<section class="lw-lb" id="lb" aria-label="Image viewer" hidden>
<button class="lw-lb-bg" type="button" data-lbclose aria-label="Close image viewer"></button>
<figure><img id="lb-img" src="" alt=""><figcaption><span class="lw-mono" id="lb-count" style="font-size:12px;color:rgba(255,255,255,.75)"></span><span id="lb-cap"></span></figcaption></figure>
<button class="lw-lbicon" type="button" style="left:18px;top:50%;margin-top:-24px" data-lbstep="-1" aria-label="Previous image">←</button>
<button class="lw-lbicon" type="button" style="right:18px;top:50%;margin-top:-24px" data-lbstep="1" aria-label="Next image">→</button>
<button class="lw-lbicon" type="button" style="right:18px;top:18px" data-lbclose aria-label="Close">×</button>
</section>
</div>
<button class="lw-fab" type="button" data-collapse hidden aria-label="Collapse the open project"><span aria-hidden="true">−</span></button>
<script src="site.js" defer></script>
</body>
</html>
'''

css = tokenize(BUILD5_CSS) + r"""
body{margin:0; background:#E4DED5; font-family:Manrope, system-ui, sans-serif}
.lw-skip{position:absolute; left:-9999px; top:8px; z-index:2000; padding:10px 14px; border-radius:8px; background:#2A1F1E; color:#FFFFFF !important}
.lw-skip:focus{left:8px}
.lw-imgs img{cursor:zoom-in}
.lw-gcard img, .lw-extra img{height:auto}
.lw-about-toggle{white-space:nowrap; flex:none}
.lw-portrait{filter:none; object-position:50% 30%}
/* --- project cards: darkened image with the name on top. Three sizes: resting band, hover (2x, shade lifted), clicked (the whole image) --- */
.lw-list{gap:0}
.lw-proj{padding-bottom:22px; scroll-margin-top:16px}
.lw-proj:last-child{padding-bottom:0}
.lw-unit{container-type:inline-size; border-radius:18px; outline:2px solid transparent; outline-offset:0; transition:outline-color .2s}
.lw-card{--h:clamp(170px, calc((100svh - 140px) / 3), 280px); position:relative; display:block; width:100%; height:var(--h); padding:0; border:0; border-radius:18px; overflow:hidden; background:#2A1F1E; color:#FFFFFF; text-align:left; cursor:pointer; transform:none; box-shadow:none; transition:height .5s cubic-bezier(.2,.7,.2,1), border-radius .3s}
.lw-card:hover{transform:none; box-shadow:none}
.lw-card-img{position:absolute; inset:0; width:100%; height:100%; aspect-ratio:auto; object-fit:cover; object-position:50% var(--fy, 50%); background:#2A1F1E}
.lw-card-img.is-blur{filter:blur(14px) saturate(.9); transform:scale(1.12)}
.lw-card::before{content:""; position:absolute; inset:0; z-index:1; background:color-mix(in srgb, #2A1F1E 42%, transparent); transition:opacity .5s}
.lw-card::after{content:""; position:absolute; inset:0; z-index:1; background:linear-gradient(to top, color-mix(in srgb, #2A1F1E 88%, transparent) 0, color-mix(in srgb, #2A1F1E 62%, transparent) 34%, transparent 72%)}
.lw-card-body{position:absolute; left:0; right:0; bottom:0; z-index:2; display:flex; flex-direction:column; align-items:flex-start; justify-content:flex-end; flex-wrap:nowrap; gap:4px; padding:18px 22px 18px; text-shadow:0 1px 14px color-mix(in srgb, #2A1F1E 45%, transparent)}
.lw-card-name{font-size:30px; line-height:1.05; font-weight:700; letter-spacing:-0.03em; color:#FFFFFF}
.lw-card-line{font-size:15px; line-height:1.45; max-width:640px; color:#FFFFFF; opacity:.92; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; overflow:hidden}
.lw-card:focus-visible{outline:3px solid #8E2F3A; outline-offset:3px}
@media (hover: hover){
 .lw-proj:hover .lw-unit{outline-color:#8E2F3A}
 .lw-proj:hover .lw-card{height:calc(var(--h) * 2)}
 .lw-proj:hover .lw-card::before{opacity:0}
}
.lw-proj.is-open .lw-unit{outline-color:#8E2F3A}
.lw-proj.is-open .lw-card, .lw-proj.is-open:hover .lw-card{height:min(calc(100cqw / var(--ar, 2)), 86svh); border-radius:18px 18px 0 0; transition:height .6s cubic-bezier(.2,.7,.2,1), border-radius .3s}
.lw-proj.is-open .lw-card::before{opacity:0}
/* --- drawer hangs straight off its card and slides open --- */
.lw-drawer{margin-top:0; border-top:0; border-radius:0 0 18px 18px; display:grid; grid-template-columns:minmax(0, 1fr); grid-template-rows:0fr; transition:grid-template-rows .55s cubic-bezier(.2,.7,.2,1)}
.lw-drawer.is-open{grid-template-rows:1fr}
.lw-drawer-in{min-height:0; min-width:0; overflow:clip}
.lw-drawer.is-settled .lw-drawer-in{overflow:visible}
.lw-chapbar{border-radius:0}
/* --- portrait collapses the open project; floating button when the portrait is off screen --- */
.lw-me{position:relative; flex:none; padding:0; border:0; background:none; border-radius:12px; cursor:default; line-height:0}
.lw-me:not([disabled]){cursor:pointer}
.lw-me-badge{position:absolute; right:-6px; bottom:-6px; width:26px; height:26px; border-radius:50%; background:#8E2F3A; color:#FFFFFF; font-size:20px; font-weight:700; line-height:24px; text-align:center; box-shadow:0 0 0 3px #E4DED5; opacity:0; transform:scale(.6); transition:opacity .2s, transform .2s}
.lw-me:not([disabled]) .lw-me-badge{opacity:1; transform:none}
.lw-me:not([disabled]):hover .lw-me-badge{background:#6E2029; transform:scale(1.1)}
.lw-fab{position:fixed; right:22px; bottom:22px; z-index:50; width:56px; height:56px; border-radius:50%; border:0; background:#8E2F3A; color:#FFFFFF; font:inherit; font-size:30px; font-weight:700; line-height:1; cursor:pointer; box-shadow:0 10px 28px color-mix(in srgb, #2A1F1E 28%, transparent); transition:background .15s, transform .15s}
.lw-fab:hover{background:#6E2029; transform:scale(1.06)}
.lw-fab:focus-visible{outline:3px solid #2A1F1E; outline-offset:3px}
@media (max-width: 860px){
 .lw-proj{padding-bottom:14px; scroll-margin-top:124px}
 .lw-card{--h:clamp(118px, 18svh, 150px)}
 .lw-card-body{padding:12px 14px; gap:2px}
 .lw-card-name{font-size:22px}
 .lw-card-line{font-size:14px; -webkit-line-clamp:1}
 .lw-me, .lw-me .lw-portrait{border-radius:50%}
 .lw-me-badge, .lw-fab{display:none !important}
}
@media (prefers-reduced-motion: reduce){
 .lw-card, .lw-card::before, .lw-drawer, .lw-me-badge, .lw-proj.is-open .lw-card, .lw-proj.is-open:hover .lw-card{transition:none}
}
.lw-contact{display:flex; flex-direction:column; max-width:760px}
.lw-crow{display:grid; grid-template-columns:130px minmax(0,1fr) auto; align-items:center; gap:16px; padding:18px 4px; border-top:1px solid #D2CABF; color:#2A1F1E !important; text-decoration:none; font-size:20px; font-weight:600; letter-spacing:-0.01em; overflow-wrap:anywhere}
.lw-crow:last-child{border-bottom:1px solid #D2CABF}
a.lw-crow:hover{color:#8E2F3A !important}
.lw-crow .lw-mono{font-size:12px; font-weight:400; color:#6A5F58; letter-spacing:.08em}
@media (max-width: 860px){
 .lw-crow{grid-template-columns:minmax(0,1fr) auto; font-size:17px; row-gap:4px}
 .lw-crow .lw-mono{grid-column:1 / -1}
}
.lw-contact-wrap{display:flex; flex-direction:column; gap:56px; max-width:760px}
.lw-form{display:flex; flex-direction:column; gap:18px}
.lw-frow{display:grid; grid-template-columns:1fr 1fr; gap:18px}
.lw-field{display:flex; flex-direction:column; gap:8px; min-width:0}
.lw-field .lw-mono{font-size:12px; color:#6A5F58; letter-spacing:.08em}
.lw-field input, .lw-field textarea{font:inherit; font-size:17px; color:#2A1F1E; background:#ECE7E0; border:1px solid #B9AEA1; border-radius:10px; padding:13px 14px; width:100%; box-sizing:border-box; transition:border-color .15s, box-shadow .15s}
.lw-field textarea{resize:vertical; min-height:150px; line-height:1.5}
.lw-field input:hover, .lw-field textarea:hover{border-color:#6A5F58}
.lw-field input:focus, .lw-field textarea:focus{outline:none; border-color:#8E2F3A; box-shadow:0 0 0 3px color-mix(in srgb, #8E2F3A 22%, transparent)}
.lw-hp{position:absolute; left:-9999px; width:1px; height:1px; overflow:hidden}
.lw-ts:empty{display:none}
.lw-factions{display:flex; align-items:center; gap:18px; flex-wrap:wrap}
.lw-send{font:inherit; font-size:16px; font-weight:700; color:#FFFFFF; background:#8E2F3A; border:0; border-radius:999px; padding:14px 26px; cursor:pointer; transition:background .15s, transform .15s}
.lw-send:hover{background:#6E2029}
.lw-send:active{transform:scale(.98)}
.lw-send:focus-visible{outline:2px solid #2A1F1E; outline-offset:3px}
.lw-send[disabled]{opacity:.6; cursor:progress}
.lw-fstatus{margin:0; font-size:15px; color:#6A5F58}
.lw-fstatus.is-ok{color:#2A1F1E; font-weight:600}
.lw-fstatus.is-err{color:#B43C2F; font-weight:600}
@media (max-width: 860px){ .lw-frow{grid-template-columns:1fr} .lw-tabs::after{content:""; flex:0 0 10px} }
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
    $('.lw-side').classList.remove('is-about');
    if (name === 'contact' && typeof loadTurnstile === 'function') loadTurnstile();
    if (push) history.replaceState(null, '', name === 'projects' ? location.pathname : '#' + name);
    window.scrollTo({ top: 0, behavior: smooth });
  }
  $$('.lw-tab').forEach(function (b) { b.addEventListener('click', function () { showTab(b.getAttribute('data-tab'), true); }); });

  // ---------- about toggle (phones) ----------
  var about = $('[data-about]');
  if (about) about.addEventListener('click', function () {
    var side = $('.lw-side'); var on = !side.classList.contains('is-about');
    side.classList.toggle('is-about', on); about.setAttribute('aria-expanded', on ? 'true' : 'false');
    about.textContent = on ? 'Hide about' : 'About me';
  });

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
    if (!openId) return; var id = openId; setCard(id, false, instant); openId = null; syncCollapse();
    if (scroll) scrollToEl(document.getElementById('p-' + id));
  }
  function openProject(id, scroll) {
    var art = document.getElementById('p-' + id);
    if (openId && openId !== id) {
      // close the other project instantly, keeping the clicked card where it is on screen
      var before = art.getBoundingClientRect().top;
      setCard(openId, false, true);
      window.scrollBy({ top: art.getBoundingClientRect().top - before, behavior: 'instant' });
    }
    setCard(id, true); openId = id; updateChapters(); syncCollapse();
    if (scroll !== false) scrollToEl(art);
    history.replaceState(null, '', '#' + id);
  }

  // ---------- collapse from the portrait, or the floating "−" when the portrait is off screen ----------
  var me = $('.lw-me'), fab = $('.lw-fab'), portraitVisible = true;
  function syncCollapse() {
    if (me) me.disabled = !openId;
    if (fab) fab.hidden = !(openId && !portraitVisible);
  }
  if (window.IntersectionObserver && me) {
    new IntersectionObserver(function (entries) {
      portraitVisible = entries[entries.length - 1].isIntersecting; syncCollapse();
    }).observe(me);
  }
  $$('[data-collapse]').forEach(function (b) {
    b.addEventListener('click', function () {
      if (!openId) return; closeProject(true); history.replaceState(null, '', location.pathname);
    });
  });
  $$('[data-toggle]').forEach(function (b) {
    b.addEventListener('click', function () {
      var id = b.getAttribute('data-toggle');
      if (openId === id) { closeProject(true); history.replaceState(null, '', location.pathname); } else openProject(id);
    });
  });
  $$('[data-next]').forEach(function (b) { b.addEventListener('click', function () { openProject(b.getAttribute('data-next')); }); });

  // ---------- chapter bar: highlight the section under the bar ----------
  function updateChapters() {
    if (!openId) return;
    var d = document.getElementById('d-' + openId); if (!d || d.hidden) return;
    var bar = $('.lw-chapbar', d); var line = bar.getBoundingClientRect().bottom + 24;
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

  // ---------- gallery rows ----------
  $$('[data-row]').forEach(function (b) {
    b.addEventListener('click', function () {
      var row = document.getElementById('row-' + b.getAttribute('data-row'));
      row.scrollBy({ left: Number(b.getAttribute('data-dir')) * Math.max(320, row.clientWidth * 0.8), behavior: smooth });
    });
  });
  $$('.lw-row').forEach(function (row) {
    var bar = document.getElementById('prog-' + row.id.replace('row-', ''));
    row.addEventListener('scroll', function () {
      var max = row.scrollWidth - row.clientWidth; var p = max > 0 ? row.scrollLeft / max * 100 : 100;
      bar.style.width = Math.max(6, p) + '%';
    }, { passive: true });
  });

  // ---------- lightbox ----------
  var lb = $('#lb'), lbImg = $('#lb-img'), lbCap = $('#lb-cap'), lbCount = $('#lb-count');
  var list = [], idx = 0, lastFocus = null;
  function render() {
    var im = list[idx]; lbImg.src = im.src; lbImg.alt = im.alt; lbCap.textContent = im.alt; lbCount.textContent = (idx + 1) + ' / ' + list.length;
  }
  function openLb(group, i, from) {
    list = $$('img[data-lb="' + group + '"]').map(function (im) { return { src: im.currentSrc || im.src, alt: im.alt }; });
    if (!list.length) return; idx = i; lastFocus = from || document.activeElement; render(); lb.hidden = false;
    $('[data-lbclose]', lb).focus({ preventScroll: true });
  }
  function closeLb() { lb.hidden = true; if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true }); }
  function step(dlt) { idx = (idx + dlt + list.length) % list.length; render(); }
  $$('[data-lbopen]').forEach(function (b) {
    b.addEventListener('click', function () { openLb(b.getAttribute('data-lbopen'), Number(b.getAttribute('data-i')), b); });
  });
  $$('.lw-imgs img[data-lb]').forEach(function (im) {
    im.addEventListener('click', function () {
      var g = im.getAttribute('data-lb'); var all = $$('img[data-lb="' + g + '"]'); openLb(g, all.indexOf(im), im);
    });
  });
  $$('[data-lbclose]').forEach(function (b) { b.addEventListener('click', closeLb); });
  $$('[data-lbstep]').forEach(function (b) { b.addEventListener('click', function () { step(Number(b.getAttribute('data-lbstep'))); }); });
  document.addEventListener('keydown', function (ev) {
    if (lb.hidden) return;
    if (ev.key === 'Escape') closeLb(); else if (ev.key === 'ArrowRight') step(1); else if (ev.key === 'ArrowLeft') step(-1);
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

  // ---------- deep links: #gallery, #resume, #extras, #axio ----------
  function route() {
    var h = location.hash.replace('#', '');
    if (!h) return;
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
