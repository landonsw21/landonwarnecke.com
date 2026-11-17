# landonwarnecke.com — Portfolio & Computational Tools

Personal portfolio and systems showcase for **Landon Warnecke** — Industrial Designer & Creative Technologist.

## Structure

- `index.html`: Main portfolio homepage (Selected Work, Industrial Design, About, and Navigation with the **Extras** dropdown).
- `fisheye.html`: Dedicated Fisheye Studio optical engine page (live interactive WebGL 2 demo, master renders, mathematical formulation, and offline exporter documentation).
- `editor.html`: Fullscreen interactive Fisheye Studio WebGL 2 application.
- `fisheye-demo.js`: Interactive WebGL 2 shader demo running on the website.
- `styles.css`: Complete responsive design stylesheet with dark aesthetic.
- `assets/`: Static master renders and media.
- `_headers`: Cloudflare Pages security and CDN caching headers.

## Deploying to Cloudflare Pages (Custom Domain `landonwarnecke.com`)

Since `landonwarnecke.com` is registered in your Cloudflare account:

1. **Push this repository to GitHub**:
   ```bash
   cd "/Users/landon/Documents/GitHub/landonwarnecke.com"
   git remote add origin https://github.com/landonsw21/landonwarnecke.com.git
   git branch -M main
   git push -u origin main
   ```
2. **Connect to Cloudflare Pages**:
   - In your Cloudflare Dashboard ([dash.cloudflare.com](https://dash.cloudflare.com)), click **Workers & Pages** → **Create application** → **Pages** → **Connect to Git**.
   - Select the `landonwarnecke.com` repository.
   - Build settings:
     - Framework preset: `None`
     - Build command: *(leave empty)*
     - Build output directory: *(leave empty / root)*
   - Click **Save and Deploy**.
3. **Attach Custom Domain**:
   - In your Pages project settings, click **Custom domains** → **Set up a custom domain**.
   - Enter `landonwarnecke.com` (and `www.landonwarnecke.com`).
   - Because your domain is registered through Cloudflare Registrar, DNS records are configured automatically with instant SSL!
