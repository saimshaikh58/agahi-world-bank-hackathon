/* Agahi chat simulator. Behaves exactly like SMS: every reply is the literal SMS text, with its
   segment budget shown underneath. No external dependencies. Used on "/" and inside the Test Console. */
(function () {
  'use strict';
  var LS_PHONES = 'agahi-phones', LS_CURRENT = 'agahi-current', LS_THEME = 'agahi-theme', LS_PHONEVIEW = 'agahi-phone-view';
  var DEV = '०१२३४५६७८९';

  function store(key, val) {
    try { if (val === undefined) return JSON.parse(localStorage.getItem(key) || 'null'); localStorage.setItem(key, JSON.stringify(val)); }
    catch (e) { return null; }
  }
  function statusWords(st) {
    if (!st) return 'n/a';
    if (st === 'pattern only') return 'rough estimate from past years';
    if (st === 'unavailable') return 'no estimate yet';
    return 'rough estimate';
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function toAscii(s) { return String(s).replace(/[०-९]/g, function (d) { return DEV.indexOf(d); }); }
  function isDev(s) { return /[ऀ-ॿ]/.test(s); }

  /* Numbered follow-ups at the end of a reply ("1 Forecast" one per line, or "1 Price  2 Forecast")
     become tap targets. Only the block of option lines at the very bottom counts. */
  function parseLine(line) {
    var toks = line.trim().split(/\s+/), opts = [], cur = null;
    for (var i = 0; i < toks.length; i++) {
      var t = toks[i];
      if (/^[0-9०-९]$/.test(t)) { if (cur && cur.label) opts.push(cur); cur = {key: toAscii(t), label: ''}; }
      else if (cur) cur.label += (cur.label ? ' ' : '') + t;
      else return null;
    }
    if (cur && cur.label) opts.push(cur);
    return opts.length ? opts : null;
  }
  /* A line in a block of option lines holds one option, or two separated by two spaces
     ("1 Hapta 2 dekhi 4" is ONE option). Only a single packed line is split at every number. */
  function parseMulti(line) {
    var out = [];
    line.trim().split(/\s{2,}/).forEach(function (piece) {
      var m = /^([0-9०-९])\s+(.+)$/.exec(piece);
      if (m) out.push({key: toAscii(m[1]), label: m[2]});
    });
    return out.length ? out : null;
  }
  function parseOptions(text) {
    var lines = String(text).split('\n'), rows = [];
    for (var i = lines.length - 1; i >= 0; i--) {
      if (!/^\s*[0-9०-९]\s/.test(lines[i])) break;
      rows.unshift(lines[i]);
    }
    var block = [];
    if (rows.length === 1) block = parseLine(rows[0]) || [];
    else rows.forEach(function (r) { block = block.concat(parseMulti(r) || []); });
    return block.length >= 2 ? block : [];
  }

  /* Always-visible shortcuts. They send words a farmer could also text. */
  var QUICK = [['price', 'Price'], ['forecast', 'Forecast'], ['weather', 'Weather'], ['sell', 'Sell/Hold'], ['arrivals', 'Arrivals']];

  function mount(root, opts) {
    opts = opts || {};
    var admin = opts.mode === 'admin';
    var st = { phones: store(LS_PHONES) || [], phone: store(LS_CURRENT), offline: false, trace: !!opts.trace,
               msgs: [], busy: false, selected: null, lang: 'rn' };
    var hasLogo = root.dataset.logo === '1' || opts.hasLogo;
    var logo = 'A';

    root.classList.toggle('no-rail', !opts.rail);
    root.innerHTML =
      (opts.rail ? '<aside class="rail">' +
        '<div class="rail-head brand-band">' + (hasLogo ? '<img class="logo" src="/static/brand/logo.png" alt="Agahi">' : '<div class="wordmark">Agahi</div>') +
        '<div class="band-sub">SMS simulator, Kalimati market</div></div>' +
        '<button class="new-btn" data-act="new">+ New farmer</button>' +
        '<div class="rail-section">Simulator numbers</div><div class="numbers" data-el="numbers"></div>' +
        '<div class="rail-foot">' +
          '<div class="toggle"><span>Reply language</span><span class="seg" data-el="langs"><button data-lang="EN">EN</button><button data-lang="RN">RN</button><button data-lang="NE">NE</button></span></div>' +
          '<label class="toggle"><span>Offline mode (cached data)</span><input type="checkbox" data-el="offline"></label>' +
          '<label class="toggle"><span>Dark theme</span><input type="checkbox" data-el="theme"></label>' +
          '<a href="/admin" style="color:var(--ink-3);font-size:12px">Open the admin dashboard</a>' +
        '</div></aside>' : '') +
      '<section class="main">' +
        '<div class="topbar"><button class="icon-btn menu-btn" data-act="rail" aria-label="Open numbers">☰</button>' +
          '<span class="phone" data-el="phone">No number yet</span><span class="chip" data-el="state"></span>' +
          (opts.rail ? '' : '<span class="seg" data-el="langs"><button data-lang="EN">EN</button><button data-lang="RN">RN</button><button data-lang="NE">NE</button></span>' +
            '<label class="toggle" style="gap:6px"><input type="checkbox" data-el="offline"> Offline</label>') +
          '<span class="spacer"></span>' +
          (opts.rail ? '' : '<button class="icon-btn" data-act="new">New farmer</button>') +
          (opts.rail ? '<button class="icon-btn phone-btn" data-act="phoneview" aria-pressed="false" title="Show the chat in a phone-sized frame"><span class="pv-off">Phone view</span><span class="pv-on">Exit phone view</span></button>' : '') +
          '<button class="icon-btn" data-act="reset" title="Forget this number and start again">Reset</button>' +
          '<button class="icon-btn" data-act="trace" aria-pressed="false">' + (opts.rail ? '<span class="long">How replies are made</span><span class="short">Trace</span>' : 'Trace') + '</button></div>' +
        '<div class="thread" data-el="thread"><div class="thread-inner" data-el="inner"></div></div>' +
        '<div class="composer-wrap"><div class="composer">' +
          '<div class="quick" data-el="quick" aria-label="Quick options">' + QUICK.map(function (q) {
            return '<button type="button" class="quick-btn" data-send="' + q[0] + '">' + q[1] + '</button>'; }).join('') + '</div>' +
          '<textarea rows="1" maxlength="480" data-el="input" placeholder="Type like an SMS: golbheda, alu 2 hapta, mausam" aria-label="Message"></textarea>' +
          '<div class="composer-row"><div class="keys" data-el="keys"></div><span class="counter" data-el="counter"></span>' +
          '<button class="send" data-act="send" aria-label="Send" disabled>' +
          '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 13V3M8 3L3.5 7.5M8 3l4.5 4.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button></div>' +
        '</div><div class="hint">New here? Send 1 to start. 0 always returns to the menu. Replies are capped at 2 SMS.</div></div>' +
      '</section>' +
      '<aside class="trace" data-el="tracePane" hidden></aside>';

    function el(name) { return root.querySelector('[data-el="' + name + '"]'); }
    var keys = el('keys');
    '1234567890'.split('').forEach(function (k) { var b = document.createElement('button'); b.textContent = k; b.dataset.key = k; b.type = 'button'; keys.appendChild(b); });

    function api(method, path, body) {
      var h = {'Content-Type': 'application/json'};
      if (admin && method === 'POST') h['X-CSRF-Token'] = opts.csrf();
      return fetch(path, {method: method, headers: h, body: body ? JSON.stringify(body) : undefined, credentials: 'same-origin'})
        .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error((j.error && j.error.message) || r.statusText); return j; }); });
    }

    function savePhones() { store(LS_PHONES, st.phones.slice(-30)); store(LS_CURRENT, st.phone); }

    function renderNumbers() {
      var box = el('numbers');
      el('phone').textContent = st.phone ? st.phone.replace(/^\+977(\d{2})/, '+977 $1 ') : 'No number yet';
      if (!box) return;
      box.innerHTML = st.phones.slice().reverse().map(function (p) {
        return '<button class="num-item' + (p === st.phone ? ' active' : '') + '" data-phone="' + esc(p) + '"><span>' +
          esc(p.replace(/^\+977/, '+977 ')) + '</span><small>' + (p === st.phone ? 'open' : '') + '</small></button>';
      }).join('') || '<div class="rail-section">Press "New farmer" to begin.</div>';
    }

    function meterHtml(m) {
      var seg = m.segments || 1, cells = '';
      for (var i = 0; i < Math.max(2, seg); i++) cells += '<i class="' + (i < seg ? 'on' : '') + '"></i>';
      return '<span class="meter' + (seg > 2 ? ' over' : '') + '" title="SMS segments used of the 2-segment budget">' + cells + '</span>' +
        '<span>' + seg + ' segment' + (seg > 1 ? 's' : '') + ' · ' + (m.encoding === 'UCS2' ? 'UCS-2' : 'GSM-7') + ' · ' + (m.chars || 0) + ' chars</span>';
    }

    function render() {
      var inner = el('inner');
      if (!st.phone || !st.msgs.length) {
        inner.innerHTML = '<div class="empty">' + '' +
          '<h1>Text Agahi the way a farmer would.</h1>' +
          '<p>Each reply below is exactly what a basic phone would receive by SMS: prices from Kalimati, honest forecast ranges and weather for the farmer\'s own district.</p>' +
          '<div class="suggest">' +
            sug('1', 'Start as a new farmer', 'Welcome, then pick a location') +
            sug('golbheda', 'golbheda', 'Today\'s tomato price') +
            sug('alu 2 hapta', 'alu 2 hapta', 'Potato price in two weeks') +
            sug('becham kauli 300kg', 'becham kauli 300kg', 'Sell now or hold?') +
          '</div></div>';
        return;
      }
      inner.innerHTML = st.msgs.map(function (m, i) {
        if (m.direction === 'in') return '<div class="msg-user">' + esc(m.text) + '</div>';
        var pushed = m.channel && m.channel !== 'web' && m.channel !== 'sms';
        var options = (i === st.msgs.length - 1 || i === st.msgs.length - 2) && !pushed ? parseOptions(m.text) : [];
        return '<div class="msg-bot' + (pushed ? ' msg-pushed' : '') + '"><div class="avatar">' + logo + '</div><div>' +
          (pushed ? '<div class="pushed-tag">Sent by Agahi (' + esc(m.channel) + ', simulated delivery)</div>' : '') +
          '<div class="bot-text"' + (isDev(m.text) ? ' lang="ne"' : '') + '>' + esc(m.text) + '</div>' +
          (options.length ? '<div class="options">' + options.map(function (o) {
            return '<button class="opt" data-key="' + esc(o.key) + '"><b>' + esc(o.key) + '</b>' + esc(o.label) + '</button>'; }).join('') + '</div>' : '') +
          '<div class="meta">' + meterHtml(m) + (m.trace ? '<button class="why" data-trace="' + i + '">How this reply was made</button>' : '') + '</div>' +
          '</div></div>';
      }).join('') + (st.busy ? '<div class="msg-bot"><div class="avatar">' + logo + '</div><div class="typing" aria-label="Agahi is replying"><span></span><span></span><span></span></div></div>' : '');
      var th = el('thread');
      th.scrollTop = th.scrollHeight;
    }
    function sug(send, title, sub) { return '<button data-send="' + esc(send) + '"><b>' + esc(title) + '</b><span>' + esc(sub) + '</span></button>'; }

    function renderTrace() {
      var pane = el('tracePane');
      pane.hidden = !st.trace;
      root.classList.toggle('with-trace', st.trace);
      root.querySelector('[data-act="trace"]').setAttribute('aria-pressed', String(st.trace));
      if (!st.trace) return;
      var m = st.selected;
      if (!m) { pane.innerHTML = '<h3>How this reply was made</h3><div class="sub">Send a message to see the trace.</div>'; return; }
      var t = m.trace || {}, probs = t.probs || {}, slots = t.slots || {};
      var bars = Object.keys(probs).map(function (k) {
        var v = Math.min(1, probs[k]);
        return '<div class="bar"><span>' + esc(k) + '</span><div><i style="width:' + (v * 100).toFixed(0) + '%"></i></div><span class="num">' + v.toFixed(2) + '</span></div>';
      }).join('') || '<div class="trace-empty">Menu number, handled by the current screen. No classifier needed.</div>';
      var slotTxt = Object.keys(slots).filter(function (k) { var v = slots[k]; return v != null && !(Array.isArray(v) && !v.length); })
        .map(function (k) { return k + ': ' + JSON.stringify(slots[k]); }).join('\n') || 'none';
      pane.innerHTML = '<h3>How this reply was made</h3><div class="sub">No LLM: rules, aliases, a tiny classifier and templates.</div>' +
        '<dl><dt>State</dt><dd>' + esc((m.state_before || '?') + ' → ' + (m.state_after || '?')) + '</dd>' +
        '<dt>Intent</dt><dd>' + esc(m.intent || '') + (m.intent_confidence != null ? ' (' + Number(m.intent_confidence).toFixed(2) + ')' : '') + '</dd>' +
        '<dt>Normalised</dt><dd>' + esc(t.normalised || '') + '</dd>' +
        '<dt>Rule</dt><dd>' + esc(t.rule || 'none') + '</dd>' +
        '<dt>Data used</dt><dd>' + esc((t.sources || []).join(', ') || 'menu text only') + '</dd>' +
        '<dt>Model</dt><dd>' + esc(t.model || 'none') + '</dd>' +
        '<dt>Label</dt><dd>' + esc(statusWords(t.status)) + '</dd>' +
        '<dt>Dropped parts</dt><dd>' + esc((t.dropped_parts || []).join(', ') || 'none (fits)') + '</dd>' +
        '<dt>Latency</dt><dd class="num">' + esc(m.latency_ms != null ? m.latency_ms + ' ms' : 'n/a') + '</dd>' +
        '<dt>Data / run</dt><dd>v' + esc(t.data_version) + ' / run ' + esc(t.model_run) + (t.offline ? ' (offline)' : '') + '</dd></dl>' +
        '<h3>Intent probabilities</h3>' + bars + '<h3 style="margin-top:14px">Slots</h3><pre>' + esc(slotTxt) + '</pre>';
    }

    function loadHistory() {
      if (!st.phone) { st.msgs = []; render(); return Promise.resolve(); }
      return api('GET', '/api/chat/history?phone=' + encodeURIComponent(st.phone)).then(function (j) {
        var msgs = j.messages.map(function (m) {
          var tr = m.trace_json ? JSON.parse(m.trace_json) : null;
          return {direction: m.direction, text: m.text, channel: m.channel, segments: m.segments, encoding: m.encoding,
                  chars: m.chars, intent: m.intent, trace: tr, id: m.id};
        });
        var changed = msgs.length !== st.msgs.length;
        st.msgs = msgs;
        if (changed) render();
      }).catch(function () {});
    }

    function newFarmer() {
      return api('POST', admin ? '/api/admin/test/new-farmer' : '/api/chat/new', {}).then(function (j) {
        st.phone = j.phone; st.phones.push(j.phone); st.msgs = []; st.selected = null;
        savePhones(); renderNumbers(); render(); renderTrace(); el('input').focus();
      }).catch(function (e) { toast(e.message); });
    }

    function send(text) {
      text = (text || '').trim();
      if (!text || st.busy) return;
      var go = st.phone ? Promise.resolve() : newFarmer();
      go.then(function () {
        st.msgs.push({direction: 'in', text: text}); st.busy = true; render();
        var body = {phone: st.phone, text: text, offline: st.offline};
        return api('POST', admin ? '/api/admin/test/chat' : '/api/chat/send', body).then(function (r) {
          st.busy = false;
          var m = {direction: 'out', text: r.text, channel: 'web', segments: r.segments, encoding: r.encoding, chars: r.chars,
                   trace: r.trace, intent: r.intent, intent_confidence: r.intent_confidence, state_before: r.state_before,
                   state_after: r.state_after, latency_ms: r.latency_ms};
          st.msgs.push(m); st.selected = m; st.lang = r.lang;
          el('state').textContent = r.state_after + ' · ' + r.lang.toUpperCase();
          markLang(); render(); renderTrace();
          if (opts.onReply) opts.onReply(r);
        });
      }).catch(function (e) { st.busy = false; render(); toast(e.message); });
    }

    function markLang() {
      root.querySelectorAll('[data-lang]').forEach(function (b) { b.setAttribute('aria-pressed', String(b.dataset.lang.toLowerCase() === st.lang)); });
    }

    function toast(msg) {
      var inner = el('inner'), d = document.createElement('div');
      d.className = 'chip bad'; d.style.alignSelf = 'center'; d.textContent = msg;
      inner.appendChild(d); setTimeout(function () { d.remove(); }, 5000);
    }

    root.addEventListener('click', function (e) {
      var b = e.target.closest('button, a'); if (!b) return;
      if (b.dataset.act === 'new') newFarmer();
      else if (b.dataset.act === 'send') { send(el('input').value); el('input').value = ''; updateCounter(); }
      else if (b.dataset.act === 'trace') { st.trace = !st.trace; renderTrace(); }
      else if (b.dataset.act === 'rail') root.classList.toggle('rail-open');
      else if (b.dataset.act === 'phoneview') setPhoneView(!root.classList.contains('phone-view'));
      else if (b.dataset.act === 'reset' && st.phone) {
        api('POST', admin ? '/api/admin/test/reset' : '/api/chat/reset', {phone: st.phone}).then(function () {
          st.msgs = []; st.selected = null; el('state').textContent = 'NEW'; render(); renderTrace(); });
      }
      else if (b.dataset.key) send(b.dataset.key);
      else if (b.dataset.send) send(b.dataset.send);
      else if (b.dataset.lang) send('LANG ' + b.dataset.lang);
      else if (b.dataset.phone) { st.phone = b.dataset.phone; savePhones(); renderNumbers(); st.msgs = []; root.classList.remove('rail-open'); loadHistory(); }
      else if (b.dataset.trace) { st.selected = st.msgs[+b.dataset.trace]; st.trace = true; renderTrace(); }
    });
    var input = el('input');
    function updateCounter() {
      var v = input.value, dev = isDev(v), n = v.length, per = dev ? (n > 70 ? 67 : 70) : (n > 160 ? 153 : 160);
      el('counter').textContent = n ? n + ' chars, ' + Math.max(1, Math.ceil(n / per)) + ' SMS' : '';
      root.querySelector('[data-act="send"]').disabled = !v.trim();
      input.style.height = 'auto'; input.style.height = Math.min(140, input.scrollHeight) + 'px';
    }
    input.addEventListener('input', updateCounter);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input.value); input.value = ''; updateCounter(); }
    });
    var off = el('offline'); if (off) off.addEventListener('change', function () { st.offline = off.checked; });
    function setPhoneView(on) {
      root.classList.toggle('phone-view', on);
      document.body.classList.toggle('phone-view-on', on);
      var pb = root.querySelector('[data-act="phoneview"]'); if (pb) pb.setAttribute('aria-pressed', String(on));
      try { localStorage.setItem(LS_PHONEVIEW, on ? '1' : '0'); } catch (e) {}
    }
    if (opts.rail) { var pv = '0'; try { pv = localStorage.getItem(LS_PHONEVIEW) || '0'; } catch (e) {} setPhoneView(pv === '1'); }
    var theme = el('theme');
    if (theme) {
      theme.checked = document.documentElement.dataset.theme === 'dark';
      theme.addEventListener('change', function () {
        var t = theme.checked ? 'dark' : 'light'; document.documentElement.dataset.theme = t;
        try { localStorage.setItem(LS_THEME, t); } catch (err) { /* private mode */ }
      });
    }

    fetch('/api/chat/meta').then(function (r) { return r.json(); }).then(function (j) {
      var banner = document.getElementById('sampleBanner'); if (banner) banner.hidden = !j.is_sample;
    }).catch(function () {});
    renderNumbers(); markLang(); renderTrace(); loadHistory();
    setInterval(function () { if (!st.busy && document.visibilityState === 'visible') loadHistory(); }, 6000);
    return { send: send, newFarmer: newFarmer };
  }

  window.AgahiChat = { mount: mount, parseOptions: parseOptions };
})();
