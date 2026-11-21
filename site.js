(function () {
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
    closeProject(false);
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
  function setCard(id, open) {
    var art = document.getElementById('p-' + id); if (!art) return;
    var btn = $('.lw-card', art); var d = document.getElementById('d-' + id);
    d.hidden = !open; btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }
  function closeProject(scroll) {
    if (!openId) return; var id = openId; setCard(id, false); openId = null;
    if (scroll) scrollToEl(document.getElementById('p-' + id));
  }
  function openProject(id, scroll) {
    if (openId && openId !== id) setCard(openId, false);
    setCard(id, true); openId = id; updateChapters();
    if (scroll !== false) scrollToEl(document.getElementById('p-' + id));
    history.replaceState(null, '', '#' + id);
  }
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
