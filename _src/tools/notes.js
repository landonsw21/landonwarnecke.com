/* Feedback layer for the local preview. Served only by _src/notes.py (never part of the deployed site).
   Note (N): click anything and type what to change.  Draw (D): mark up the page, then type a note.
   Drag a pin to move its note (its drawing moves with it).  Click a pin to read or delete it.
   Notes (L): list, show, delete.  Hide (H): hide pins and drawings.  Esc: stop.
   Each note saves to _notes/notes.json with the element it points at (selector, text, size, styles),
   where it is (tab, project, section), the window size and scroll, and any drawing.
   /?note=ID reopens the page the way it was when that note was left, with its drawing. */
(function () {
  'use strict';
  if (window.__lwNotes) return;
  window.__lwNotes = true;

  var API = '/__notes', SVG = 'http://www.w3.org/2000/svg';
  var POM = '#8E2F3A', INK = '#2A1F1E', LINE = '#D2CABF', MUTED = '#6A5F58', PAPER = '#F7F3EE';
  var notes = [], lastJson = '', mode = 'off', hideAll = false, listOpen = false;
  var draft = null;      // note being written: {el, x, y (document coords), strokes: [[[x, y], ...]]}
  var stroke = null;     // stroke being drawn
  var cardFor = null;    // saved note whose card is open
  var hoverEl = null, hlFor = null;
  var drag = null;       // pin being moved: {n, x0, y0, dx, dy, moved, target}
  var focusId = (/[?&]note=(\d+)/.exec(location.search) || [])[1];
  focusId = focusId ? +focusId : null;

  // ---------- helpers ----------
  function h(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    return el;
  }
  function s(tag, attrs) {
    var el = document.createElementNS(SVG, tag);
    for (var k in attrs) el.setAttribute(k, attrs[k]);
    return el;
  }
  function file(src) { return (src || '').split('?')[0].split('/').pop(); }
  function clean(t, n) { t = (t || '').replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, n - 1) + '…' : t; }
  function mine(el) { return root.contains(el); }
  function pick(x, y) {
    x = Math.max(1, Math.min(innerWidth - 2, x)); y = Math.max(1, Math.min(innerHeight - 2, y));
    var all = document.elementsFromPoint(x, y);
    for (var i = 0; i < all.length; i++) if (!mine(all[i]) && all[i] !== document.documentElement) return all[i];
    return document.body;
  }
  function shown(el) {
    if (!el || !el.isConnected || el.closest('[hidden]')) return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0;
  }
  function sel(el) {
    var parts = [];
    while (el && el.nodeType === 1 && el !== document.body && el !== document.documentElement) {
      if (el.id && document.querySelectorAll('#' + CSS.escape(el.id)).length === 1) { parts.unshift('#' + CSS.escape(el.id)); return parts.join(' > '); }
      var p = el.parentElement, part = el.tagName.toLowerCase();
      var cls = Array.prototype.filter.call(el.classList, function (c) { return /^lw-/.test(c); })[0];
      if (cls) part += '.' + CSS.escape(cls);
      if (p) {
        var same = Array.prototype.filter.call(p.children, function (c) { return c.tagName === el.tagName; });
        if (same.length > 1) part += ':nth-of-type(' + (same.indexOf(el) + 1) + ')';
      }
      parts.unshift(part); el = p;
    }
    parts.unshift('body');
    return parts.join(' > ');
  }
  function find(n) {
    if (!n._el || !n._el.isConnected) { try { n._el = document.querySelector(n.anchor); } catch (e) { n._el = null; } }
    return n._el;
  }
  function label(el) {
    var t = el.tagName.toLowerCase(), c = Array.prototype.filter.call(el.classList, function (x) { return /^lw-/.test(x); })[0];
    var bit = el.tagName === 'IMG' ? file(el.currentSrc || el.src) : clean(el.innerText || el.textContent, 40);
    return t + (c ? '.' + c : '') + (bit ? '  ' + bit : '');
  }
  function lite(el) {
    var d = { sel: sel(el), tag: el.tagName.toLowerCase() };
    if (el.tagName === 'IMG') { d.img = file(el.currentSrc || el.src); d.alt = el.alt; }
    var t = clean(el.innerText || el.textContent, 80); if (t) d.text = t;
    return d;
  }
  function describe(el) {
    var d = lite(el), r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (el.className && typeof el.className === 'string') d.cls = el.className.trim();
    d.text = clean(el.innerText || el.textContent, 160) || undefined;
    d.box = [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)];
    d.style = {
      font: cs.fontSize + '/' + cs.lineHeight + ' ' + cs.fontWeight, color: cs.color, background: cs.backgroundColor,
      margin: cs.margin, padding: cs.padding, radius: cs.borderRadius, display: cs.display
    };
    if (cs.display.indexOf('flex') >= 0 || cs.display.indexOf('grid') >= 0) d.style.gap = cs.gap;
    return d;
  }
  function where(el) {
    if (el.closest('#lb')) { var im = document.querySelector('#lb img'); return 'Image viewer' + (im ? ' › ' + file(im.currentSrc || im.src) : ''); }
    if (el.closest('.lw-side')) return 'Left column';
    var w = [], tab = document.querySelector('.lw-tab.is-active');
    w.push(tab ? clean(tab.textContent, 30) : 'Page');
    var proj = el.closest('.lw-proj');
    if (proj) {
      var nm = proj.querySelector('.lw-card-name'); w.push(nm ? clean(nm.textContent, 30) : proj.id);
      if (el.closest('.lw-card')) w.push('Card');
      else if (el.closest('.lw-chapbar')) w.push('Section bar');
    }
    var sec = el.closest('.lw-sec, .lw-rblock'); if (sec) { var hd = sec.querySelector('h2, h3'); if (hd) w.push(clean(hd.textContent, 30)); }
    var tile = el.closest('.lw-tile'); if (tile) { var tn = tile.querySelector('.lw-tile-name'); if (tn) w.push(clean(tn.textContent, 30)); }
    var ex = el.closest('.lw-extra'); if (ex) { var eh = ex.querySelector('h2, h3, h4'); if (eh) w.push(clean(eh.textContent, 30)); }
    return w.join(' › ');
  }
  function view() {
    var tab = document.querySelector('.lw-tab.is-active'), proj = document.querySelector('.lw-proj.is-open');
    var lb = document.getElementById('lb'), lbi = lb && !lb.hidden ? lb.querySelector('img') : null;
    return {
      w: innerWidth, h: innerHeight, scrollY: Math.round(scrollY), hash: location.hash,
      tab: tab ? tab.getAttribute('data-tab') : null, project: proj ? proj.getAttribute('data-project') : null,
      lightbox: lbi ? file(lbi.currentSrc || lbi.src) : null
    };
  }
  function pathD(pts, dx, dy) {
    if (pts.length === 1) pts = [pts[0], pts[0]];
    return pts.map(function (p, i) { return (i ? 'L' : 'M') + Math.round(p[0] - dx) + ' ' + Math.round(p[1] - dy); }).join('');
  }
  function inked(g, d) {
    g.appendChild(s('path', { d: d, stroke: '#FFFFFF', 'stroke-width': 7, 'stroke-opacity': 0.85 }));
    g.appendChild(s('path', { d: d, stroke: POM, 'stroke-width': 3 }));
  }
  function api(body) {
    return fetch(API, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {})
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(setNotes);
  }

  // ---------- layer ----------
  var st = h('style');
  st.textContent = [
    '#lwn{position:fixed;inset:0;z-index:2147483000;pointer-events:none;font:13px/1.4 Manrope,system-ui,sans-serif;color:' + INK + ';text-align:left}',
    '#lwn *{box-sizing:border-box;letter-spacing:0}',
    '#lwn button{font:inherit;cursor:pointer;margin:0}',
    '#lwn .lwn-ink{position:fixed;left:0;top:0;width:100vw;height:100vh;overflow:visible;pointer-events:none}',
    '#lwn .lwn-ink path{fill:none;stroke-linecap:round;stroke-linejoin:round}',
    '#lwn .lwn-catch{position:fixed;inset:0;pointer-events:none}',
    '#lwn.m-note .lwn-catch,#lwn.m-draw .lwn-catch{pointer-events:auto;cursor:crosshair}',
    '#lwn.m-draw .lwn-catch{touch-action:none}',
    '#lwn.is-hidden .lwn-pins,#lwn.is-hidden .lwn-saved{display:none}',
    '#lwn .lwn-hl{position:fixed;left:0;top:0;border:2px dashed ' + POM + ';border-radius:4px;background:rgba(142,47,58,.07);pointer-events:none;display:none}',
    '#lwn .lwn-hl span{position:absolute;left:-2px;bottom:100%;margin-bottom:3px;padding:1px 6px;border-radius:4px;background:' + POM + ';color:#FFFFFF;font-size:11px;white-space:nowrap;max-width:360px;overflow:hidden;text-overflow:ellipsis}',
    '#lwn .lwn-hl.is-below span{bottom:auto;top:100%;margin:3px 0 0}',
    '#lwn .lwn-pin{position:fixed;left:0;top:0;width:24px;height:24px;margin:-12px 0 0 -12px;padding:0;border-radius:50%;border:2px solid #FFFFFF;background:' + POM + ';color:#FFFFFF;font-size:11px;font-weight:700;line-height:20px;text-align:center;pointer-events:auto;box-shadow:0 2px 8px rgba(42,31,30,.35)}',
    '#lwn .lwn-pin{cursor:grab;touch-action:none}',
    '#lwn .lwn-pin.is-drag{cursor:grabbing;box-shadow:0 8px 20px rgba(42,31,30,.45)}',
    '#lwn .lwn-pin.is-done{background:' + MUTED + '}',
    '#lwn .lwn-pin.is-flash{animation:lwnflash .9s 3}',
    '@keyframes lwnflash{50%{box-shadow:0 0 0 12px rgba(142,47,58,.35)}}',
    '#lwn .lwn-card{position:fixed;left:0;top:0;width:290px;padding:10px;border-radius:12px;background:#FFFFFF;border:1px solid ' + LINE + ';box-shadow:0 12px 32px rgba(42,31,30,.25);pointer-events:auto;display:none}',
    '#lwn textarea{display:block;width:100%;min-height:66px;margin:0;resize:vertical;padding:8px;border:1px solid ' + LINE + ';border-radius:8px;font:inherit;font-size:14px;color:' + INK + ';background:' + PAPER + ';outline:none}',
    '#lwn textarea:focus{border-color:' + POM + '}',
    '#lwn .lwn-row{display:flex;gap:6px;justify-content:flex-end;align-items:center;margin-top:8px}',
    '#lwn .lwn-row .lwn-grow{flex:1}',
    '#lwn .lwn-btn{padding:5px 10px;border-radius:8px;border:1px solid ' + LINE + ';background:#FFFFFF;color:' + INK + '}',
    '#lwn .lwn-btn:hover{border-color:' + POM + '}',
    '#lwn .lwn-btn.is-pri{background:' + POM + ';border-color:' + POM + ';color:#FFFFFF}',
    '#lwn .lwn-meta{font-size:11px;color:' + MUTED + ';margin-bottom:3px}',
    '#lwn .lwn-text{white-space:pre-wrap;font-size:14px}',
    '#lwn .lwn-fix{margin-top:5px;font-size:12px;color:' + MUTED + '}',
    '#lwn .lwn-fix b{color:' + INK + '}',
    '#lwn .lwn-bar{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);display:flex;gap:3px;padding:4px;border-radius:12px;background:' + INK + ';box-shadow:0 10px 28px rgba(42,31,30,.3);pointer-events:auto}',
    '#lwn .lwn-bar button{padding:6px 12px;border:0;border-radius:8px;background:transparent;color:#ECE7E0;white-space:nowrap}',
    '#lwn .lwn-bar button:hover{background:rgba(236,231,224,.14)}',
    '#lwn .lwn-bar button.is-on{background:' + POM + ';color:#FFFFFF}',
    '#lwn .lwn-bar b{display:inline-block;min-width:18px;margin-left:5px;padding:0 5px;border-radius:6px;background:rgba(236,231,224,.2);font-size:11px;text-align:center}',
    '#lwn .lwn-list{position:fixed;left:50%;bottom:62px;transform:translateX(-50%);width:400px;max-width:calc(100vw - 24px);max-height:62vh;overflow:auto;padding:6px;border-radius:12px;background:#FFFFFF;border:1px solid ' + LINE + ';box-shadow:0 12px 32px rgba(42,31,30,.25);pointer-events:auto;display:none}',
    '#lwn .lwn-item{padding:8px}',
    '#lwn .lwn-item+.lwn-item{border-top:1px solid #ECE7E0}',
    '#lwn .lwn-item.is-done .lwn-text{color:' + MUTED + ';text-decoration:line-through}',
    '#lwn .lwn-item .lwn-row{justify-content:flex-start;margin-top:6px}'
  ].join('\n');
  document.head.appendChild(st);

  var root = h('div'); root.id = 'lwn'; root.className = 'm-off';
  var ink = s('svg', { class: 'lwn-ink' }), saved = s('g', { class: 'lwn-saved' }), live = s('g', {});
  ink.appendChild(saved); ink.appendChild(live);
  var hl = h('div', 'lwn-hl'), hlTag = h('span'); hl.appendChild(hlTag);
  var catcher = h('div', 'lwn-catch'), pins = h('div', 'lwn-pins');

  // composer
  var comp = h('div', 'lwn-card'), ta = h('textarea'), crow = h('div', 'lwn-row');
  ta.setAttribute('aria-label', 'Note');
  var bUndo = h('button', 'lwn-btn', 'Undo'), bCancel = h('button', 'lwn-btn', 'Cancel'), bSave = h('button', 'lwn-btn is-pri', 'Save');
  bUndo.type = bCancel.type = bSave.type = 'button';
  crow.appendChild(bUndo); crow.appendChild(h('span', 'lwn-grow')); crow.appendChild(bCancel); crow.appendChild(bSave);
  comp.appendChild(ta); comp.appendChild(crow);

  // saved note card
  var card = h('div', 'lwn-card');

  // toolbar + list
  var bar = h('div', 'lwn-bar');
  function barBtn(txt, title) { var b = h('button', '', txt); b.type = 'button'; b.title = title; bar.appendChild(b); return b; }
  var bNote = barBtn('Note', 'Click something, then type what to change (N)');
  var bDraw = barBtn('Draw', 'Mark up the page, then type a note (D)');
  var bList = barBtn('Notes', 'All notes (L)'), count = h('b', '', '0'); bList.appendChild(count);
  var bHide = barBtn('Hide', 'Hide pins and drawings (H)');
  var list = h('div', 'lwn-list');

  [ink, catcher, hl, pins, comp, card, list, bar].forEach(function (el) { root.appendChild(el); });
  document.body.appendChild(root);

  // ---------- notes on the page ----------
  function visibleNotes() { return notes.filter(function (n) { return !n.done || n.id === focusId; }); }
  function setNotes(arr) {
    var js = JSON.stringify(arr);
    if (js === lastJson) return;
    lastJson = js; notes = arr;
    while (saved.firstChild) saved.removeChild(saved.firstChild);
    pins.innerHTML = '';
    visibleNotes().forEach(function (n) {
      n._pin = h('button', 'lwn-pin' + (n.done ? ' is-done' : ''), String(n.id));
      n._pin.type = 'button'; n._pin.title = clean(n.text, 120);
      n._pin.addEventListener('pointerdown', function (e) { dragStart(e, n); });
      n._pin.addEventListener('pointermove', dragMove);
      n._pin.addEventListener('pointerup', dragEnd);
      n._pin.addEventListener('pointercancel', dragEnd);
      pins.appendChild(n._pin);
      if (n.ink && n.ink.length) { n._g = s('g', {}); n.ink.forEach(function (d) { inked(n._g, d); }); saved.appendChild(n._g); }
    });
    if (cardFor) cardFor = notes.filter(function (n) { return n.id === cardFor.id; })[0] || null;
    if (cardFor) fillCard(cardFor); else card.style.display = 'none';
    var open = notes.filter(function (n) { return !n.done; }).length;
    count.textContent = String(open);
    renderList();
  }
  function place(box, x, y, gap) {
    var w = box.offsetWidth, ht = box.offsetHeight;
    var left = Math.min(Math.max(8, x + gap), innerWidth - w - 8);
    var top = y + gap + ht > innerHeight - 70 ? y - gap - ht : y + gap;
    box.style.transform = 'translate(' + Math.round(left) + 'px,' + Math.round(Math.max(8, top)) + 'px)';
  }
  function frame() {
    visibleNotes().forEach(function (n) {
      var el = find(n), ok = shown(el);
      if (n._pin) n._pin.style.display = ok ? '' : 'none';
      if (n._g) n._g.style.display = ok ? '' : 'none';
      if (!ok) { n._xy = null; return; }
      var r = el.getBoundingClientRect(), off = drag && drag.n === n && drag.moved ? [drag.dx, drag.dy] : [0, 0];
      n._xy = [r.left + n.at[0], r.top + n.at[1]];
      n._pin.style.transform = 'translate(' + (n._xy[0] + off[0]) + 'px,' + (n._xy[1] + off[1]) + 'px)';
      if (n._g) n._g.setAttribute('transform', 'translate(' + (r.left + off[0]) + ' ' + (r.top + off[1]) + ')');
    });
    live.setAttribute('transform', 'translate(' + -scrollX + ' ' + -scrollY + ')');
    var target = drag && drag.moved ? drag.target : draft ? draft.el : (mode === 'note' ? hoverEl : null);
    if (target && shown(target)) {
      if (target !== hlFor) { hlFor = target; hlTag.textContent = label(target); }
      var b = target.getBoundingClientRect();
      hl.style.display = 'block';
      hl.style.transform = 'translate(' + (b.left - 2) + 'px,' + (b.top - 2) + 'px)';
      hl.style.width = (b.width + 4) + 'px'; hl.style.height = (b.height + 4) + 'px';
      hl.classList.toggle('is-below', b.top < 22);
    } else hl.style.display = 'none';
    if (draft) place(comp, draft.x - scrollX, draft.y - scrollY, 14);
    if (cardFor) {
      if (cardFor._xy && !hideAll) { card.style.display = 'block'; place(card, cardFor._xy[0], cardFor._xy[1], 16); }
      else card.style.display = 'none';
    }
    requestAnimationFrame(frame);
  }

  // ---------- writing a note ----------
  function startDraft(el, vx, vy) {
    if (!draft) { draft = { strokes: [] }; ta.value = ''; }
    draft.el = el; draft.x = vx + scrollX; draft.y = vy + scrollY;
    bUndo.style.visibility = draft.strokes.length ? 'visible' : 'hidden';
    comp.style.display = 'block';
    openCard(null);
    setTimeout(function () { ta.focus(); }, 0);
  }
  function cancelDraft() {
    if (document.activeElement === ta) ta.blur();
    draft = null; stroke = null;
    while (live.firstChild) live.removeChild(live.firstChild);
    comp.style.display = 'none';
  }
  function saveDraft() {
    if (!draft) return;
    var text = ta.value.trim();
    if (!text && !draft.strokes.length) return cancelDraft();
    var el = draft.el, px = draft.x, py = draft.y, els = null, inks = null;
    if (draft.strokes.length) {
      // anchor a drawing to whatever sits under its middle (what a circle goes around)
      var xs = [], ys = [];
      draft.strokes.forEach(function (st) { st.forEach(function (p) { xs.push(p[0]); ys.push(p[1]); }); });
      var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
      el = pick((x0 + x1) / 2 - scrollX, (y0 + y1) / 2 - scrollY);
      px = x1; py = y0;
      var seen = {}; els = [];
      [[(x0 + x1) / 2, (y0 + y1) / 2]].concat(draft.strokes.reduce(function (a, st) { return a.concat([st[0], st[st.length - 1]]); }, []))
        .forEach(function (p) {
          var vx = p[0] - scrollX, vy = p[1] - scrollY;
          if (vx < 0 || vy < 0 || vx > innerWidth || vy > innerHeight) return;
          var e = pick(vx, vy), k = sel(e);
          if (!seen[k]) { seen[k] = 1; els.push(lite(e)); }
        });
    }
    var r = el.getBoundingClientRect(), ax = r.left + scrollX, ay = r.top + scrollY;
    if (draft.strokes.length) inks = draft.strokes.map(function (st) { return pathD(st, ax, ay); });
    var note = {
      text: text, where: where(el), anchor: sel(el), at: [Math.round(px - ax), Math.round(py - ay)],
      point: [Math.round(px - scrollX), Math.round(py - scrollY)], el: describe(el), view: view()
    };
    if (inks) { note.ink = inks; note.els = els; }
    cancelDraft();
    api({ action: 'add', note: note }).catch(function () { alert('Could not save the note: is python3 _src/notes.py still running?'); });
  }
  bSave.addEventListener('click', saveDraft);
  bCancel.addEventListener('click', cancelDraft);
  bUndo.addEventListener('click', function () {
    if (!draft || !draft.strokes.length) return;
    draft.strokes.pop(); live.removeChild(live.lastChild); live.removeChild(live.lastChild);
    if (!draft.strokes.length) cancelDraft(); else ta.focus();
  });

  catcher.addEventListener('pointermove', function (e) {
    if (mode === 'note' && !draft) hoverEl = pick(e.clientX, e.clientY);
    if (mode === 'draw' && stroke) {
      var p = [e.clientX + scrollX, e.clientY + scrollY], q = stroke.pts[stroke.pts.length - 1];
      if (Math.abs(p[0] - q[0]) + Math.abs(p[1] - q[1]) < 2) return;
      stroke.pts.push(p);
      var d = pathD(stroke.pts, 0, 0); stroke.a.setAttribute('d', d); stroke.b.setAttribute('d', d);
    }
  });
  catcher.addEventListener('pointerleave', function () { if (mode === 'note') hoverEl = null; });
  catcher.addEventListener('click', function (e) {
    if (mode !== 'note') return;
    startDraft(pick(e.clientX, e.clientY), e.clientX, e.clientY);
  });
  catcher.addEventListener('pointerdown', function (e) {
    if (mode !== 'draw' || e.button > 0) return;
    e.preventDefault();
    catcher.setPointerCapture(e.pointerId);
    if (!draft) { draft = { strokes: [] }; ta.value = ''; }
    var p = [e.clientX + scrollX, e.clientY + scrollY], d = pathD([p], 0, 0);
    var a = s('path', { d: d, stroke: '#FFFFFF', 'stroke-width': 7, 'stroke-opacity': 0.85 }), b = s('path', { d: d, stroke: POM, 'stroke-width': 3 });
    live.appendChild(a); live.appendChild(b);
    stroke = { pts: [p], a: a, b: b };
    draft.strokes.push(stroke.pts);
    comp.style.display = 'none';
  });
  function endStroke() {
    if (!stroke) return;
    stroke = null;
    var xs = [], ys = [];
    draft.strokes.forEach(function (st) { st.forEach(function (p) { xs.push(p[0]); ys.push(p[1]); }); });
    var vx = Math.max.apply(null, xs) - scrollX, vy = Math.max.apply(null, ys) - scrollY;
    startDraft(pick((Math.min.apply(null, xs) + Math.max.apply(null, xs)) / 2 - scrollX, (Math.min.apply(null, ys) + Math.max.apply(null, ys)) / 2 - scrollY), vx, vy);
  }
  catcher.addEventListener('pointerup', endStroke);
  catcher.addEventListener('pointercancel', endStroke);

  // ---------- moving a note: drag its pin; it re-attaches to whatever it is dropped on ----------
  function shiftD(d, dx, dy) {
    return d.replace(/([ML])(-?\d+) (-?\d+)/g, function (m, c, x, y) { return c + Math.round(+x + dx) + ' ' + Math.round(+y + dy); });
  }
  function dragStart(e, n) {
    if (e.button > 0) return;
    e.preventDefault(); e.stopPropagation();
    n._pin.setPointerCapture(e.pointerId);
    drag = { n: n, x0: e.clientX, y0: e.clientY, dx: 0, dy: 0, moved: false, target: null };
  }
  function dragMove(e) {
    if (!drag) return;
    drag.dx = e.clientX - drag.x0; drag.dy = e.clientY - drag.y0;
    if (!drag.moved && Math.abs(drag.dx) + Math.abs(drag.dy) < 4) return;
    if (!drag.moved) { drag.moved = true; drag.n._pin.classList.add('is-drag'); openCard(null); }
    if (drag.n._xy) drag.target = pick(drag.n._xy[0] + drag.dx, drag.n._xy[1] + drag.dy);
  }
  function dragEnd() {
    if (!drag) return;
    var d = drag, n = d.n; drag = null;
    n._pin.classList.remove('is-drag');
    if (!d.moved) { openCard(cardFor && cardFor.id === n.id ? null : n); return; }
    var old = find(n);
    if (!n._xy || !shown(old)) return;
    var px = n._xy[0] + d.dx, py = n._xy[1] + d.dy, el = pick(px, py);
    var r0 = old.getBoundingClientRect(), r = el.getBoundingClientRect();
    var fields = {
      where: where(el), anchor: sel(el), at: [Math.round(px - r.left), Math.round(py - r.top)],
      point: [Math.round(px), Math.round(py)], el: describe(el), view: view()
    };
    // a drawing moves with its pin
    if (n.ink) fields.ink = n.ink.map(function (p) { return shiftD(p, r0.left + d.dx - r.left, r0.top + d.dy - r.top); });
    if (fields.ink) {
      // what the moved drawing now touches: its middle (the new anchor) and each stroke's ends
      var seen = {}, els = [];
      [[px, py]].concat(fields.ink.reduce(function (a, p) { var m = p.match(/-?\d+ -?\d+/g); return a.concat([m[0], m[m.length - 1]]); }, [])
        .map(function (q) { q = q.split(' '); return [r.left + +q[0], r.top + +q[1]]; }))
        .forEach(function (q) {
          if (q[0] < 0 || q[1] < 0 || q[0] > innerWidth || q[1] > innerHeight) return;
          var e = pick(q[0], q[1]), k = sel(e);
          if (!seen[k]) { seen[k] = 1; els.push(lite(e)); }
        });
      fields.els = els;
    }
    // show it in place right away; the saved copy comes back from the server
    n.anchor = fields.anchor; n._el = el; n.at = fields.at; n.where = fields.where;
    if (n._g && fields.ink) { n.ink = fields.ink; while (n._g.firstChild) n._g.removeChild(n._g.firstChild); n.ink.forEach(function (p) { inked(n._g, p); }); }
    api({ action: 'update', id: n.id, fields: fields }).catch(function () { alert('Could not move the note: is python3 _src/notes.py still running?'); });
  }

  // ---------- saved note card + list ----------
  function fillCard(n) {
    card.innerHTML = '';
    card.appendChild(h('div', 'lwn-meta', '#' + n.id + ' · ' + n.where));
    if (n.text) card.appendChild(h('div', 'lwn-text', n.text));
    if (n.fix) { var f = h('div', 'lwn-fix'); f.appendChild(h('b', '', 'Fixed: ')); f.appendChild(document.createTextNode(n.fix)); card.appendChild(f); }
    var row = h('div', 'lwn-row'), del = h('button', 'lwn-btn', 'Delete'), x = h('button', 'lwn-btn', 'Close');
    del.type = x.type = 'button';
    del.addEventListener('click', function () { openCard(null); api({ action: 'delete', id: n.id }); });
    x.addEventListener('click', function () { openCard(null); });
    row.appendChild(del); row.appendChild(x); card.appendChild(row);
  }
  function openCard(n) {
    cardFor = n;
    if (n) fillCard(n); else card.style.display = 'none';
  }
  function replayUrl(n) {
    var v = n.view || {}, hash = v.project ? '#' + v.project : (v.tab && v.tab !== 'projects' ? '#' + v.tab : '');
    return location.pathname + '?note=' + n.id + hash;
  }
  function show(n) {
    var el = find(n);
    if (!shown(el) || n.done) {
      // another tab or a closed project: reload the page as it was when the note was left
      var url = replayUrl(n);
      if (location.search === '?note=' + n.id) { history.replaceState(null, '', url); location.reload(); } else location.href = url;
      return;
    }
    var r = el.getBoundingClientRect();
    window.scrollBy({ top: r.top + n.at[1] - innerHeight / 2, behavior: 'smooth' });
    flash(n); openCard(n);
  }
  function flash(n) {
    if (!n._pin) return;
    n._pin.classList.remove('is-flash'); void n._pin.offsetWidth; n._pin.classList.add('is-flash');
  }
  function renderList() {
    list.style.display = listOpen ? 'block' : 'none';
    bList.classList.toggle('is-on', listOpen);
    if (!listOpen) return;
    list.innerHTML = '';
    if (!notes.length) { list.appendChild(h('div', 'lwn-item lwn-meta', 'No notes yet')); return; }
    var order = notes.filter(function (n) { return !n.done; }).concat(notes.filter(function (n) { return n.done; }));
    order.forEach(function (n) {
      var it = h('div', 'lwn-item' + (n.done ? ' is-done' : ''));
      it.appendChild(h('div', 'lwn-meta', '#' + n.id + ' · ' + n.where + (n.ink ? ' · drawing' : '')));
      if (n.text) it.appendChild(h('div', 'lwn-text', n.text));
      if (n.fix) { var f = h('div', 'lwn-fix'); f.appendChild(h('b', '', 'Fixed: ')); f.appendChild(document.createTextNode(n.fix)); it.appendChild(f); }
      var row = h('div', 'lwn-row'), go = h('button', 'lwn-btn', 'Show'), del = h('button', 'lwn-btn', 'Delete');
      go.type = del.type = 'button';
      go.addEventListener('click', function () { show(n); });
      del.addEventListener('click', function () { if (cardFor && cardFor.id === n.id) openCard(null); api({ action: 'delete', id: n.id }); });
      row.appendChild(go); row.appendChild(del); it.appendChild(row);
      list.appendChild(it);
    });
    if (notes.some(function (n) { return n.done; })) {
      var row = h('div', 'lwn-row'), clr = h('button', 'lwn-btn', 'Clear fixed');
      clr.type = 'button';
      clr.addEventListener('click', function () { api({ action: 'clear_done' }); });
      row.appendChild(clr); list.appendChild(row);
    }
  }

  // ---------- modes and keys ----------
  function setMode(m) {
    if (m !== mode) cancelDraft();
    mode = m; hoverEl = null;
    root.className = 'm-' + m + (hideAll ? ' is-hidden' : '');
    bNote.classList.toggle('is-on', m === 'note');
    bDraw.classList.toggle('is-on', m === 'draw');
    if (m !== 'off') { hideAll = false; root.classList.remove('is-hidden'); bHide.classList.remove('is-on'); }
  }
  function toggleList() { listOpen = !listOpen; renderList(); }
  function toggleHide() {
    hideAll = !hideAll; root.classList.toggle('is-hidden', hideAll); bHide.classList.toggle('is-on', hideAll);
    if (hideAll) openCard(null);
  }
  bNote.addEventListener('click', function () { setMode(mode === 'note' ? 'off' : 'note'); });
  bDraw.addEventListener('click', function () { setMode(mode === 'draw' ? 'off' : 'draw'); });
  bList.addEventListener('click', toggleList);
  bHide.addEventListener('click', toggleHide);

  document.addEventListener('keydown', function (e) {
    if (e.target === ta) {
      e.stopPropagation();
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveDraft(); }
      else if (e.key === 'Escape') { e.preventDefault(); cancelDraft(); }
      return;
    }
    var t = e.target, typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    var k = e.key.toLowerCase();
    if (k === 'n') setMode(mode === 'note' ? 'off' : 'note');
    else if (k === 'd') setMode(mode === 'draw' ? 'off' : 'draw');
    else if (k === 'l') toggleList();
    else if (k === 'h') toggleHide();
    else if (e.key === 'Escape' && (mode !== 'off' || listOpen || cardFor)) { setMode('off'); openCard(null); listOpen = false; renderList(); }
    else return;
    e.preventDefault(); e.stopImmediatePropagation();
  }, true);

  // ---------- start: load notes, keep in sync (Claude marks fixed notes in the file), replay ?note= ----------
  api().then(function () {
    if (!focusId) return;
    setTimeout(function () {
      var n = notes.filter(function (x) { return x.id === focusId; })[0], el = n && find(n);
      if (!shown(el)) return;
      var r = el.getBoundingClientRect();
      window.scrollBy({ top: r.top + n.at[1] - n.point[1], behavior: 'instant' });
      flash(n); openCard(n);
    }, 1200);
  }).catch(function () {});
  setInterval(function () { if (!document.hidden) api().catch(function () {}); }, 3000);
  requestAnimationFrame(frame);
})();
