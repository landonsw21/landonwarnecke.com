"""Builds the site's Fisheye Studio (editor.html) from Landon's studio source folder.

The studio is developed in ~/Documents/GBD/cube export (override with LW_FISHEYE_SRC): studio-shell.html
plus the scripts its own build_editors.py embeds. This embeds them the same way, then
  - colors the interface, viewport handles and demo scene from theme.css (Greige + Pomegranate,
    following the visitor's light/dark setting); pins and the orange twist diamond keep their own colors,
  - trims filler text (section numbers, kicker labels, paragraphs that repeat the controls),
  - points "Download KeyShot script" at downloads/cube-export.py, copied from the source folder.

usage (from the repo root): python3 _src/fisheye.py
Every replacement is checked: if the studio source changes shape, this stops and names what it could not find.
"""
import os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SRC = os.environ.get("LW_FISHEYE_SRC", os.path.expanduser("~/Documents/GBD/cube export"))


def read(name):
    return open(os.path.join(SRC, name), encoding="utf-8").read()


def sub(text, old, new, where, count=1):
    n = text.count(old)
    if (n != count) if count else not n:
        sys.exit(f"fisheye.py: expected {count or 'some'} x {old[:80]!r} in {where}, found {n}")
    return text.replace(old, new)


# ---- shell: same script order as the studio's own build_editors.py
order = re.search(r"for f in \(([^)]*)\)", read("build_editors.py"))
if not order:
    sys.exit("fisheye.py: could not read the script list from build_editors.py")
scripts = re.findall(r"'([^']+\.js)'", order.group(1))
shell = read("studio-shell.html")
head, body = shell.split("</head>", 1)
css_start, css_end = head.index("<style>") + 7, head.index("</style>")
css = head[css_start:css_end]

# ---- interface colors -> theme.css tokens
root = re.search(r":root\s*\{[^}]*\}", css)
if not root or "#d5f596" not in root.group(0):
    sys.exit("fisheye.py: the shell's :root color block changed")
css = css.replace(root.group(0), ":root { --bg: var(--lw-bg); --panel: var(--lw-panel); --panel-elevated: var(--lw-surface); "
                  "--line: var(--lw-line); --muted: var(--lw-muted); --text: var(--lw-ink); --accent: var(--lw-accent); "
                  "--accent-glow: color-mix(in srgb, var(--lw-accent) 15%, transparent); --orange: var(--lw-scene-tint-b); }", 1)
css = sub(css, "radial-gradient(ellipse at center, #242c26, #0e1210 75%)", "var(--lw-stage)", "stage background")
css = sub(css, '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif', "var(--lw-font-sans)", "body font")
css = re.sub(r"font-family:\s*monospace", "font-family: var(--lw-font-mono)", css)
css = css.replace("font:10px monospace", "font:10px var(--lw-font-mono)")
mix = "color-mix(in srgb, var(--lw-accent) {}%, transparent)".format
COLORS = {
    "rgba(17, 20, 18, 0.85)": "color-mix(in srgb, var(--lw-bg) 85%, transparent)",   # sticky header
    "rgba(213, 245, 150, 0.4)": mix(40), "rgba(213, 245, 150, 0.08)": mix(8),
    "#d5f59633": mix(20),                                  # timeline trim handles
    "#ffffff08": "color-mix(in srgb, var(--lw-ink) 6%, transparent)",   # timeline grid
    "#252d27": "var(--lw-panel)", "#3c483f": "var(--lw-line-strong)",    # buttons, inputs
    "#323d35": "var(--lw-surface)", "#526356": "var(--lw-muted)",        # button hover
    "#152210": "var(--lw-on-accent)", "#2c3822": "var(--lw-accent-soft)",
    "#4a5c41": mix(45),                                    # badge
    "#92a28d": "var(--lw-muted)", "#7f907a": "var(--lw-muted)", "#b5c7ad": "var(--lw-muted)", "#cad6c5": "var(--lw-muted)",
    "#c9d4c5": "var(--lw-ink)", "#ff9e87": "var(--lw-danger)",
    "#0f1310": "var(--lw-bg)", "#131814": "var(--lw-bg)", "#384537": "var(--lw-line-strong)",   # number inputs, pin box
    "#252e20": "var(--lw-accent-soft)", "#4a5c37": mix(40),               # notice
    "#34412c": "var(--lw-accent-soft)", "#718958": mix(55),                # timeline effect blocks
    "#495b37": "color-mix(in srgb, var(--lw-accent) 28%, var(--lw-accent-soft))",
    "#d5f596": "var(--lw-accent)",
}
for old, new in COLORS.items():   # longest first: #d5f59633 before #d5f596
    css = css.replace(old, new)
left = re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)", css)
if left:
    sys.exit(f"fisheye.py: new colors in studio-shell.html need a theme token: {sorted(set(left))}")
css += "\n    section > .row.spread:first-child { margin-bottom: 12px; }\n"

head = head[:css_start] + css + head[css_end:]
head = re.sub(r"<title>.*?</title>", "<title>Fisheye Studio · Landon Warnecke</title>", head, count=1)
head = sub(head, "<style>", '<link rel="stylesheet" href="theme.css">\n  <style>', "head")

# ---- text: keep what helps, drop filler
PLAY, PAUSE = "▶︎ Play", "❚❚ Pause"   # ︎ keeps ▶ a text symbol, not an emoji, on phones
B = [
    ('<div class="eyebrow">Standalone Continuous Ray Optical Engine</div>', '<div class="eyebrow">Capture once. Shape the view.</div>'),
    ('href="cube%20export.py"', 'href="downloads/cube-export.py"'),
    ('<h2 id="projectName">Interactive 3D Demo Scene</h2>', '<h2 id="projectName">Material study</h2>'),
    ("Procedural 13-sphere Thomson layout · Load a KeyShot capture to edit your own render", "Interactive sample · load a cube export to use your own render"),
    (">WebGL 2 Live<", ">Demo scene<"),
    ("◎ Concentric Rings", "◎ Rings"), ("⌖ Local Pins", "⌖ Pins"),
    ('title="Press & hold to bypass displacement"', 'title="Press and hold to see the unedited projection"'),
    ('<div class="stage-label">CONTINUOUS RAY ENGINE · LIVE GPU</div>', ""),
    ('\n        <span id="renderInfo">Single-pass continuous ray unprojection</span>', ""),
    (re.search(r'\s*<p class="secondary" style="margin-top:10px">Add an adjustment as an effect\..*?</p>', body, re.S), ""),
    (re.search(r'<p class="secondary" style="margin-top:10px">⌘/Ctrl\+Z undoes.*?</p>', body, re.S),
     '<p class="secondary" style="margin-top:10px">The preview plays here; PNG export uses the still view. Save edits keeps the timeline.</p>'),
    ("<label>From<input", '<label title="Rotation is continuous: 0 → 360 is one turn, 0 → 720 is two">From<input'),
    ("<label>To<input", '<label title="Rotation is continuous: 0 → 360 is one turn, 0 → 720 is two">To<input'),
    ("<h3>01 / Optical Projection</h3>", "<h3>Projection</h3>"),
    ('<h3 style="margin:0">02 / Continuous Displacement</h3>', '<h3 style="margin:0">Displacement</h3>'),
    ('<h3 style="margin:0">03 / Optics & Aberrations</h3>', '<h3 style="margin:0">Optics</h3>'),
    ("<h3>04 / Master Studio Export</h3>", "<h3>Export</h3>"),
    (re.search(r'<p class="secondary" style="margin:6px 0 10px;">\s*Set each ring.*?</p>', body, re.S),
     '<p class="secondary" style="margin:0 0 10px;">Each ring moves a radius in the original image (base / source) to a new one '
     "(destination) and can twist it. Remove a neighboring ring for more travel.</p>"),
    (re.search(r'\s*<p class="secondary" style="margin:6px 0 10px;">\s*Physical full-frame.*?</p>', body, re.S), ""),
    (re.search(r'<p class="secondary">Fixed to the glass while the scene moves\..*?</p>', body, re.S),
     '<p class="secondary">Fixed to the glass while the scene moves.</p>'),
    ("Export Master PNG ↗", "Export PNG"),
    ('class="primary">Play preview</button>', f'class="primary">{PLAY}</button>'),   # timeline transport: symbols
    ('<button id="animationStop">Stop</button>', '<button id="animationStop">■ Stop</button>'),
    ('<button id="animationBase">Reset preview</button>', '<button id="animationBase" title="Reset the preview to the current settings">↺ Reset</button>'),
    (re.search(r'\s*<details style="margin-top:14px;">.*?</details>', body, re.S), ""),   # offline exporter isn't offered here
]
for old, new in B:
    if old is None:
        sys.exit(f"fisheye.py: a paragraph to trim is gone from studio-shell.html (replacement {new[:60]!r})")
    body = sub(body, old if isinstance(old, str) else old.group(0), new, "studio-shell.html body")

# ---- scripts
js = {name: read(name) for name in scripts}
s = js["studio.js"]
W = "studio.js"
s = sub(s, "uniform vec3 rings;uniform float ringSpread;",
        "uniform vec3 rings;uniform float ringSpread;\nuniform vec3 demoSkyA,demoSkyB,demoGroundA,demoGroundB,demoTintA,demoTintB;", W)
s = sub(s, "mix(vec3(.075,.10,.08),vec3(.36,.43,.32),", "mix(demoSkyA,demoSkyB,", W)
s = sub(s, "mix(vec3(.18,.23,.17),vec3(.27,.33,.23),", "mix(demoGroundA,demoGroundB,", W)
s = sub(s, "mix(vec3(.46,.66,.24),vec3(.86,.47,.23),", "mix(demoTintA,demoTintB,", W)
s = sub(s, "vec3(.95,.99,.83)*spec", "vec3(1.,.97,.95)*spec", W)
s = sub(s, "\nfunction uniforms(", """
// ---- shared palette (theme.css), added by the site's _src/fisheye.py
const LW_THEME={demoSkyA:'--lw-scene-sky-a',demoSkyB:'--lw-scene-sky-b',demoGroundA:'--lw-scene-ground-a',demoGroundB:'--lw-scene-ground-b',demoTintA:'--lw-scene-tint-a',demoTintB:'--lw-scene-tint-b'};
function lwTok(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim()}
function lwVec(hex){const m=/^#?([0-9a-f]{6})$/i.exec(hex||'');if(!m)return[.5,.5,.5];const n=parseInt(m[1],16);return[(n>>16&255)/255,(n>>8&255)/255,(n&255)/255]}
const lwVals={};function lwRead(){for(const k in LW_THEME)lwVals[k]=lwVec(lwTok(LW_THEME[k]));lwVals.accent=lwTok('--lw-accent')||'#8E2F3A';lwVals.accentHover=lwTok('--lw-accent-hover')||'#6E2029'}
function lwApplyTheme(){for(const k in LW_THEME)gl.uniform3fv(loc(k),lwVals[k])}
lwRead();
if(window.matchMedia)matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{lwRead();schedule()});
function uniforms(""", W)
s = sub(s, " gl.uniform3fv(loc('rings'),state.rings);", " lwApplyTheme();gl.uniform3fv(loc('rings'),state.rings);", W)
s = sub(s, "j===selectedRing?'#e8ffad':'#d5f59688'", "j===selectedRing?lwVals.accentHover:lwVals.accent+'88'", W)
s = sub(s, "ctx.fillStyle='#d5f596';", "ctx.fillStyle=lwVals.accent;", W)
s = sub(s, "ctx.fillStyle='#121812';", "ctx.fillStyle='#1D1817';", W)   # pin numbers on the orange/blue pins
s = sub(s, " Larger outputs can use the offline exporter.", "", W)
s = sub(s, '<p class="secondary">Warp from this radius in the original image to the destination radius below.</p>', "", W)   # said once above the rings instead
if re.search(r"#d5f596|#e8ffad", s, re.I):
    sys.exit("fisheye.py: lime is still used in studio.js")
js["studio.js"] = s
a = js["animation.js"]
a = sub(a, "$('animationPlay').textContent='Play preview'", f"$('animationPlay').textContent='{PLAY}'", "animation.js")
a = sub(a, "$('animationPlay').textContent='Pause preview'", f"$('animationPlay').textContent='{PAUSE}'", "animation.js")
js["animation.js"] = a

scripts_html = "\n".join("<script>\n" + js[name] + "\n</script>" for name in scripts)
body = sub(body, "{{SCRIPTS}}", scripts_html, "studio-shell.html body")
doc = head + "</head>" + body
if re.search(r"#d5f596|#d4f28a|#101210", doc, re.I):
    sys.exit("fisheye.py: Fisheye lime or green-black is still in the page")

open(os.path.join(REPO, "editor.html"), "w", encoding="utf-8").write(doc)
os.makedirs(os.path.join(REPO, "downloads"), exist_ok=True)
shutil.copyfile(os.path.join(SRC, "cube export.py"), os.path.join(REPO, "downloads", "cube-export.py"))
print(f"editor.html  {len(doc) // 1024} KB  (scripts: {', '.join(scripts)})")
print(f"downloads/cube-export.py  {os.path.getsize(os.path.join(REPO, 'downloads', 'cube-export.py')) // 1024} KB")
