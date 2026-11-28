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
