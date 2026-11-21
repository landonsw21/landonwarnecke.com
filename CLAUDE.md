# landonwarnecke.com — how this site is built and published

Static portfolio for Landon Schmidt-Warnecke (industrial design, WWU). No build step: plain HTML/CSS/JS.

## Files
- `index.html` — the whole site, pre-rendered (projects, extras, gallery, resume). Generated; edit content at the source (below) and regenerate rather than hand-editing when possible.
- `site.css`, `site.js` — styles and interactions (tabs, one-at-a-time project drawers with sticky chapter bar, gallery rows, lightbox with Esc/arrow keys, deep links like `#gallery` or `#axio`).
- `portfolio-media/` — optimized images (KeyShot renders and original photos from the ID folder). Also used by the Framer copy of the site.
- `fisheye.html`, `editor.html` — Fisheye Studio (linked from Extras). Still in the old dark/lime style; restyle to Greige + Pomegranate is pending.
- `legacy.html` — the previous homepage, kept for reference.
- `_headers` — Cloudflare Pages headers.

## Design system
Greige + Pomegranate: base #E4DED5, surface #D4CBBE, panel #ECE7E0, ink #2A1F1E, muted #6A5F58, accent #8E2F3A, line #D2CABF. Manrope + IBM Plex Mono. Never use Fisheye lime (#D4F28A) or green-black (#101210).

## Publishing workflow
1. Change content/design (ask Landon before new design or interaction decisions).
2. Commit to `main`.
3. Push (GitHub Desktop → Push origin, or CLI once credentials are set up).
4. Cloudflare Pages deploys `main` automatically to https://landonwarnecke.com (build command: none, output directory: `/`).
   GitHub Pages also serves the repo at https://landonsw21.github.io/landonwarnecke.com/ (useful for previews).

## Placeholders still to fill
Search for `[TO WRITE]`, `[TO CONFIRM]`, `[TO ADD` and `[PDF LINK TO ADD]` in index.html.
