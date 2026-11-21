# landonwarnecke.com — how this site is built and published

Static portfolio for Landon Warnecke (industrial design, Western Washington University; the site shows the name "Landon Warnecke"). No build step: plain HTML/CSS/JS.

## Files
- `index.html` — the whole site, pre-rendered (projects, extras, gallery, resume). Generated; edit content at the source (below) and regenerate rather than hand-editing when possible.
- `site.css`, `site.js` — styles and interactions (tabs, one-at-a-time project drawers with sticky chapter bar, gallery rows, lightbox with Esc/arrow keys, deep links like `#gallery` or `#axio`).
- `portfolio-media/` — optimized images (KeyShot renders and original photos from the ID folder). Also used by the Framer copy of the site.
- `theme.css` — THE palette. Shared by the portfolio, Fisheye Studio and Perspective Studio. Change colors here only.
- `fisheye.html` (+ `styles.css`, `fisheye-demo.js`), `editor.html` — Fisheye Studio, linked from Extras. Colors come from theme.css (including the WebGL demo scenes via `--lw-scene-*`).
- `perspective-studio/` — Perspective Studio (moved from landonsw21.github.io/perspective-studio). Its UI colors map to theme.css; its drawing colors (VP rays, guides) are functional and intentionally not themed.
- `legacy.html` — the previous homepage, kept for reference.
- `_headers` — Cloudflare Pages headers.
- `contact-worker/` — the Contact form mailer, a separate Cloudflare Worker (`landonwarnecke-contact`) deployed by Workers Builds from this folder and routed at `landonwarnecke.com/api/contact` (Pages Functions can't send email). It checks Cloudflare Turnstile, then emails the message through Email Routing from contact@landonwarnecke.com with Reply-To set to the visitor. Secrets live only in the Worker's dashboard settings: `TURNSTILE_SECRET`, `CONTACT_TO`. The public Turnstile site key is in the form's `data-sitekey` (index.html). The form never says where messages are delivered.

## Design system
Greige + Pomegranate, defined once in `theme.css` as `--lw-*` custom properties (light set + dark set).
- The portfolio forces the light set (`<html data-theme="light">`); the tools follow the visitor's system light/dark setting.
- To change the palette: edit the values in `theme.css` (both the light block and the two identical dark blocks), commit, push. Keep text contrast at 4.5:1 or better.
- site.css, styles.css, editor.html and perspective-studio/index.html must use `var(--lw-…)`, never raw hex (exceptions: functional drawing colors and JS fallbacks).
- Never use Fisheye lime (#D4F28A / #d5f596) or green-black (#101210).

## Publishing workflow
1. Change content/design (ask Landon before new design or interaction decisions).
2. Commit to `main`.
3. Push (GitHub Desktop → Push origin, or CLI once credentials are set up).
4. Cloudflare Pages deploys `main` automatically to https://landonwarnecke.com (build command: none, output directory: `/`).
   GitHub Pages also serves the repo at https://landonsw21.github.io/landonwarnecke.com/ (useful for previews).

## Placeholders still to fill
Search for `[TO WRITE]`, `[TO CONFIRM]`, `[TO ADD` and `[PDF LINK TO ADD]` in index.html.
