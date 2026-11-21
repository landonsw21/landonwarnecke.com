// landonwarnecke.com contact form mailer (Cloudflare Worker).
// Runs at landonwarnecke.com/api/contact. Checks the Turnstile token, then emails the message
// through Cloudflare Email Routing. Settings (Worker → Settings → Variables and Secrets):
//   TURNSTILE_SECRET  secret  Turnstile widget secret key
//   CONTACT_TO        secret  where messages go (must be a verified Email Routing destination)
//   CONTACT_FROM      text    optional sender, default contact@landonwarnecke.com

const SITEVERIFY = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';
const HOSTS = ['landonwarnecke.com', 'www.landonwarnecke.com'];
const EMAIL_RE = /^[^\s@<>()",;:]+@[^\s@<>()",;:]+\.[^\s@<>()",;:]{2,}$/;

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
  });
const field = (v, max) => String(v ?? '').replace(/\r\n?/g, '\n').trim().slice(0, max);
const oneLine = (s) => s.replace(/[\u0000-\u001f\u007f]+/g, ' ').replace(/\s+/g, ' ').trim();

export default {
  async fetch(request, env) {
    if (request.method !== 'POST') return json({ ok: false, error: 'Method not allowed.' }, 405);

    const origin = request.headers.get('origin');
    if (origin && !HOSTS.some((h) => origin === 'https://' + h)) return json({ ok: false, error: 'Forbidden.' }, 403);
    if (Number(request.headers.get('content-length') || 0) > 32000) return json({ ok: false, error: 'Message is too long.' }, 413);

    let data;
    try {
      data = await request.json();
    } catch {
      return json({ ok: false, error: 'Bad request.' }, 400);
    }

    // Bots fill the hidden "company" field; pretend it worked.
    if (field(data.company, 200)) return json({ ok: true });

    const name = oneLine(field(data.name, 100));
    const email = oneLine(field(data.email, 200));
    const message = field(data.message, 5000);
    if (!name || !message || !EMAIL_RE.test(email)) {
      return json({ ok: false, error: 'Please add your name, a valid email and a message.' }, 400);
    }

    if (!env.TURNSTILE_SECRET || !env.CONTACT_TO || !env.EMAIL) {
      console.error('contact: missing TURNSTILE_SECRET, CONTACT_TO or EMAIL binding');
      return json({ ok: false, error: 'The form is not set up yet. Please use one of the links below.' }, 503);
    }

    const body = new FormData();
    body.append('secret', env.TURNSTILE_SECRET);
    body.append('response', field(data.token, 2048));
    const ip = request.headers.get('cf-connecting-ip');
    if (ip) body.append('remoteip', ip);
    const check = await fetch(SITEVERIFY, { method: 'POST', body })
      .then((r) => r.json())
      .catch(() => ({ success: false }));
    if (!check.success || (check.hostname && !HOSTS.includes(check.hostname))) {
      return json({ ok: false, error: 'Couldn’t verify you’re human. Please try again.' }, 403);
    }

    const sent = new Date().toUTCString();
    try {
      await env.EMAIL.send({
        from: { email: env.CONTACT_FROM || 'contact@landonwarnecke.com', name: 'landonwarnecke.com' },
        to: env.CONTACT_TO,
        replyTo: { email, name },
        subject: `Portfolio message from ${name}`,
        text: `${message}\n\n—\nFrom: ${name} <${email}>\nSent: ${sent} via the contact form on landonwarnecke.com\nReply to this email to answer ${name}.`,
      });
    } catch (err) {
      console.error('contact: send failed', err && err.code, err && err.message);
      return json({ ok: false, error: 'Couldn’t send right now. Please try again, or use one of the links below.' }, 502);
    }
    return json({ ok: true });
  },
};
