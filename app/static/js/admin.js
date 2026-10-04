/* Agahi admin dashboard. Vanilla JS, one file. Calls only routes in docs/API_CONTRACT.md.
   Every panel loads independently: a failure shows an error with Retry and never breaks the page. */
(function () {
  'use strict';
  var CSRF = '', charts = [], sse = null, jobSse = null, poller = null, jobPoller = null, currentPage = 'overview', statusCache = {};
  var POLL_MS = 5000;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]; }); }
  function fmt(v, d) { if (v == null || isNaN(v)) return 'n/a'; return Number(v).toLocaleString('en-US', {maximumFractionDigits: d == null ? 0 : d, minimumFractionDigits: d || 0}); }
  function pct(v, d) { return v == null ? 'n/a' : fmt(v * 100, d == null ? 1 : d) + '%'; }
  function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  function api(method, path, body, isForm) {
    var h = {};
    if (method === 'POST') h['X-CSRF-Token'] = CSRF;
    if (body && !isForm) h['Content-Type'] = 'application/json';
    return fetch(path, {method: method, headers: h, credentials: 'same-origin', body: body ? (isForm ? body : JSON.stringify(body)) : undefined})
      .then(function (r) {
        var ct = r.headers.get('content-type') || '';
        if (!ct.includes('json')) { if (!r.ok) throw new Error(r.statusText); return r.text(); }
        return r.json().then(function (j) {
          if (r.status === 401) { showLogin(); throw new Error('Please sign in.'); }
          if (!r.ok) throw new Error((j.error && j.error.message) || r.statusText);
          return j;
        });
      });
  }

  /* ---------- panel helper: skeleton, error with retry ---------- */
  function panel(target, loader, render) {
    var box = typeof target === 'string' ? $(target) : target;
    if (!box) return;
    box.innerHTML = '<div class="skel" style="width:40%"></div><div class="skel"></div><div class="skel" style="width:70%"></div>';
    loader().then(function (d) {
      try { render(d, box); } catch (e) { fail(e); }
    }).catch(fail);
    function fail(e) {
      box.innerHTML = '<div class="err">Could not load: ' + esc(e.message) + ' <button class="btn">Retry</button></div>';
      $('button', box).onclick = function () { panel(box, loader, render); };
      if (window.console) console.error(e);
    }
  }

  /* ---------- charts (tables still render if Chart.js is missing) ---------- */
  function palette() {
    return {brand: css('--brand-600') || '#1f3b29', brand5: css('--brand-500') || '#475e4f', ink3: css('--ink-3'), line: css('--line'),
            ok: css('--ok'), warn: css('--warn'), bad: css('--bad'), info: css('--info'), accent: '#b08d2c',
            series: ['#1f3b29', '#b08d2c', '#2c5f86', '#8a4f7d', '#5f8f6b', '#b3372e', '#6b6b6b', '#3f7fa0']};
  }
  function chart(canvasHolder, config) {
    var holder = typeof canvasHolder === 'string' ? $(canvasHolder) : canvasHolder;
    if (!holder) return null;
    if (!window.Chart) { holder.innerHTML = '<div class="chart-missing">Chart library not loaded (offline or CDN blocked). The tables on this page still show the numbers. See README to vendor Chart.js.</div>'; return null; }
    holder.innerHTML = '<canvas></canvas>';
    var p = palette();
    Chart.defaults.color = p.ink3; Chart.defaults.borderColor = p.line;
    Chart.defaults.font.family = css('--sans');
    config.options = Object.assign({responsive: true, maintainAspectRatio: false, animation: false, layout: {padding: {top: 4, right: 8, bottom: 0, left: 0}},
      plugins: {legend: {position: 'top', align: 'start', labels: {boxWidth: 10, boxHeight: 10, padding: 12}}}}, config.options || {});
    var c = new Chart($('canvas', holder), config);
    charts.push(c);
    return c;
  }
  function clearCharts() { charts.forEach(function (c) { try { c.destroy(); } catch (e) { /* already gone */ } }); charts = []; }
  window.addEventListener('chartjs', function () { go(currentPage); });

  /* ---------- nav ---------- */
  var ICON = {
    overview: '<path d="M3 13h4V3H3zM9 13h4V7H9z"/>', conversations: '<path d="M2 3h12v8H6l-4 3z"/>',
    market: '<path d="M2 12l4-4 3 2 5-6"/><path d="M10 4h4v4"/>', models: '<rect x="2" y="2" width="5" height="5"/><rect x="9" y="2" width="5" height="5"/><rect x="2" y="9" width="5" height="5"/><rect x="9" y="9" width="5" height="5"/>',
    data: '<ellipse cx="8" cy="4" rx="5" ry="2"/><path d="M3 4v8c0 1.1 2.2 2 5 2s5-.9 5-2V4"/><path d="M3 8c0 1.1 2.2 2 5 2s5-.9 5-2"/>',
    console: '<path d="M2 3h12v10H2z"/><path d="M5 7l2 2-2 2M9 11h3"/>', weather: '<path d="M4 11a3 3 0 010-6 4 4 0 017.6 1A2.5 2.5 0 0111.5 11z"/><path d="M6 13l-1 2M10 13l-1 2"/>',
    farmers: '<circle cx="8" cy="5" r="3"/><path d="M2 15c1-3 3.5-4 6-4s5 1 6 4"/>', alerts: '<path d="M8 2a4 4 0 014 4v3l1.5 2.5h-11L4 9V6a4 4 0 014-4z"/><path d="M6.5 14a1.5 1.5 0 003 0"/>',
    sms: '<path d="M2 4h12v8H2z"/><path d="M2 4l6 5 6-5"/>', quality: '<circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/>'
  };
  var NAV = [
    ['Monitor', [['overview', 'Overview'], ['conversations', 'Conversations'], ['farmers', 'Farmers'], ['sms', 'SMS operations']]],
    ['Market', [['market', 'Market & forecasts'], ['weather', 'Weather outlook']]],
    ['Models', [['models', 'Models & evaluation'], ['data', 'Data & training']]],
    ['Tools', [['console', 'Test Console'], ['alerts', 'Alerts & broadcast'], ['quality', 'Quality queue']]]
  ];
  function buildNav() {
    $('#nav').innerHTML = NAV.map(function (g) {
      return '<div class="nav-group">' + g[0] + '</div>' + g[1].map(function (it) {
        return '<button class="nav-item" data-page="' + it[0] + '"><svg viewBox="0 0 16 16">' + ICON[it[0]] + '</svg>' + it[1] + '</button>';
      }).join('');
    }).join('');
  }
  var TITLES = {overview: 'Overview', conversations: 'Conversations', market: 'Market & forecasts', models: 'Models & evaluation',
    data: 'Data & training', console: 'Test Console', weather: 'Weather outlook', farmers: 'Farmers', alerts: 'Alerts & broadcast',
    sms: 'SMS operations', quality: 'Quality queue'};

  function go(page) {
    if (!PAGES[page]) page = 'overview';
    currentPage = page;
    clearCharts();
    if (sse && page !== 'conversations') { sse.close(); sse = null; }
    if (poller) { clearInterval(poller); poller = null; }
    $$('.nav-item').forEach(function (b) { b.classList.toggle('active', b.dataset.page === page); });
    $('#pageTitle').textContent = TITLES[page];
    $('#range').style.display = page === 'overview' ? '' : 'none';
    $('#app').classList.remove('side-open');
    if (location.hash !== '#' + page) history.replaceState(null, '', '#' + page);
    PAGES[page]($('#page'));
  }

  /* ---------- status + banners ---------- */
  function loadStatus() {
    return api('GET', '/api/admin/status').then(function (s) {
      statusCache = s;
      $('#pillFresh').textContent = s.today ? 'Prices to ' + s.today : 'No price data';
      $('#pillData').textContent = 'Data v' + (s.data_version || '?') + (s.is_sample ? ' (sample)' : '');
      var b = '';
      if (s.is_sample) b += '<div class="banner warn"><b>SAMPLE DATA, not real prices.</b> Upload the real ZIP on Data & training.</div>';
      if (!s.models_trained) b += '<div class="banner bad">Forecast models are not trained yet. <button class="btn" data-train-now>Train now</button></div>';
      if (s.demo_rows) b += '<div class="banner info">Demo data included: ' + fmt(s.demo_rows) + ' seeded messages, not real usage. <button class="btn" data-purge>Purge demo data</button></div>';
      $('#banners').innerHTML = b;
      var t = $('[data-train-now]'); if (t) t.onclick = function () { startTraining('fast'); go('data'); };
      var p = $('[data-purge]'); if (p) p.onclick = function () {
        if (!confirm('Delete all demo conversations and farmers?')) return;
        api('POST', '/api/admin/demo/purge', {}).then(function () { loadStatus(); go(currentPage); });
      };
    }).catch(function () { /* banners are optional */ });
  }

  function statusClass(s) { return s === 'reliable' ? 'status-reliable' : s === 'indicative' ? 'status-indicative' : s === 'pattern only' ? 'status-pattern' : 'status-unavailable'; }
  function statusChip(s) { var c = s === 'reliable' ? 'ok' : s === 'indicative' ? 'warn' : s === 'pattern only' ? '' : 'bad'; return '<span class="chip ' + c + '">' + esc(s || 'n/a') + '</span>'; }
  function table(cols, rows, opts) {
    opts = opts || {};
    if (!rows.length) return '<div class="empty-state">' + esc(opts.empty || 'Nothing to show yet.') + '</div>';
    return '<div class="table-wrap"><table><thead><tr>' + cols.map(function (c) { return '<th class="' + (c.r ? 'r' : '') + '">' + esc(c.t) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + rows.map(function (r, i) {
        return '<tr' + (opts.click ? ' class="click" data-i="' + i + '"' : '') + '>' + cols.map(function (c) {
          var v = c.f ? c.f(r) : esc(r[c.k]); return '<td class="' + (c.r ? 'r num' : '') + '">' + (v == null ? '' : v) + '</td>'; }).join('') + '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  /* ================= PAGES ================= */
  var PAGES = {};

  PAGES.overview = function (root) {
    root.innerHTML = '<div class="kpis" id="kpis"></div><div class="grid g2">' +
      card('cVol', 'Messages by language', 'Inbound messages per day, stacked by reply language.', 'span2') +
      card('cIntent', 'Intent mix', 'What farmers asked for.') + card('cCrops', 'Top crops', 'Crops mentioned in inbound messages.') +
      card('cLoc', 'Farmers by location', 'Saved location of every farmer.') + card('cLang', 'Languages', 'Share of inbound messages.') +
      card('cHeat', 'When people text', 'Hour of day (Asia/Kathmandu) by weekday.') + card('cLat', 'Reply latency', 'p50 and p95 per day, in milliseconds.') +
      card('cSeg', 'SMS segments per reply', 'Every reply is capped at 2 segments.') + '</div>';
    var range = $('#range').value;
    panel('#kpis', function () { return api('GET', '/api/admin/overview?range=' + range); }, function (d, box) {
      var k = d.kpis, ch = k.messages_change_pct;
      box.innerHTML = kpi('Messages', fmt(k.messages), ch == null ? 'no earlier data' : (ch >= 0 ? '+' : '') + fmt(ch, 1) + '% vs previous period', ch > 0 ? 'up' : ch < 0 ? 'down' : '') +
        kpi('Unique farmers', fmt(k.unique_farmers), 'texted in this period') +
        kpi('Onboarding completion', pct(k.onboarding_completion, 0), fmt(k.onboarding_started) + ' new numbers started') +
        kpi('Avg segments per reply', fmt(k.avg_segments, 2), 'budget is 2') +
        kpi('Latency p50 / p95', fmt(k.latency_p50, 1) + ' / ' + fmt(k.latency_p95, 1) + ' ms', 'engine time per reply') +
        kpi('Unknown intent rate', pct(k.unknown_rate), 'see Quality queue') +
        kpi('Estimated SMS cost', 'Rs ' + fmt(k.sms_cost_npr, 1), 'at configured cost per segment') +
        kpi('Forecast requests', pct(k.forecast_share), 'share of inbound messages');
      var p = palette();
      var langName = {en: 'English', rn: 'Roman Nepali', ne: 'Nepali'};
      chart('#cVol .chart-box', {type: 'line', data: {labels: d.volume.days, datasets: ['rn', 'en', 'ne'].map(function (l, i) {
        return {label: langName[l], data: d.volume.series[l], fill: true, stack: 's', backgroundColor: p.series[i] + '55', borderColor: p.series[i], pointRadius: 0, tension: .25}; })},
        options: {scales: {y: {stacked: true, beginAtZero: true}}}});
      bar('#cIntent .chart-box', d.intents, p.brand, true);
      bar('#cCrops .chart-box', d.crops, p.brand5, true);
      bar('#cLoc .chart-box', d.locations, p.brand, true);
      chart('#cLang .chart-box', {type: 'doughnut', data: {labels: d.languages.map(function (x) { return langName[x[0]] || x[0]; }),
        datasets: [{data: d.languages.map(function (x) { return x[1]; }), backgroundColor: p.series.slice(0, 3)}]}, options: {cutout: '62%'}});
      heat('#cHeat .chart-box', d.heatmap);
      chart('#cLat .chart-box', {type: 'line', data: {labels: d.latency.map(function (x) { return x.date; }), datasets: [
        {label: 'p50', data: d.latency.map(function (x) { return x.p50; }), borderColor: p.brand, pointRadius: 2},
        {label: 'p95', data: d.latency.map(function (x) { return x.p95; }), borderColor: p.accent, pointRadius: 2}]}, options: {scales: {y: {beginAtZero: true}}}});
      bar('#cSeg .chart-box', d.segments.sort(function (a, b) { return a[0] - b[0]; }).map(function (x) { return [x[0] + ' segment' + (x[0] > 1 ? 's' : ''), x[1]]; }), p.brand5);
      if (!d.kpis.messages) box.insertAdjacentHTML('beforeend', '<div class="empty-state" style="grid-column:1/-1">No messages in this period. Try a longer range or chat in the simulator.</div>');
    });
  };
  function card(id, title, desc, cls) { return '<div class="panel ' + (cls || '') + '" id="' + id + '"><h3>' + esc(title) + '</h3><p class="desc">' + esc(desc) + '</p><div class="chart-box"></div></div>'; }
  function kpi(label, value, sub, cls) { return '<div class="kpi"><div class="kpi-label">' + esc(label) + '</div><div class="kpi-value">' + esc(value) + '</div><div class="kpi-sub ' + (cls || '') + '">' + esc(sub) + '</div></div>'; }
  function bar(sel, pairs, color, horizontal) {
    if (!pairs || !pairs.length) { var h = $(sel); if (h) h.innerHTML = '<div class="chart-missing">No data in this period.</div>'; return; }
    chart(sel, {type: 'bar', data: {labels: pairs.map(function (x) { return x[0]; }), datasets: [{label: 'count', data: pairs.map(function (x) { return x[1]; }), backgroundColor: color, borderRadius: 3}]},
      options: {indexAxis: horizontal ? 'y' : 'x', plugins: {legend: {display: false}}, scales: {x: {beginAtZero: true}}}});
  }
  function heat(sel, m) {
    var max = 1; m.forEach(function (r) { r.forEach(function (v) { max = Math.max(max, v); }); });
    var days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    $(sel).innerHTML = '<div class="table-wrap"><table class="heat"><tr><td></td>' + Array.from({length: 24}, function (_, h) { return '<td style="font-size:10px;color:var(--ink-3);text-align:center">' + (h % 3 ? '' : h) + '</td>'; }).join('') + '</tr>' +
      m.map(function (r, i) { return '<tr><td style="font-size:11px;color:var(--ink-3);padding-right:6px">' + days[i] + '</td>' + r.map(function (v) {
        return '<td title="' + v + ' messages" style="background:' + (v ? 'color-mix(in srgb, var(--brand-600) ' + Math.round(15 + 85 * v / max) + '%, transparent)' : 'var(--surface-2)') + '"></td>'; }).join('') + '</tr>'; }).join('') + '</table></div>';
  }

  /* ---------- conversations ---------- */
  PAGES.conversations = function (root) {
    root.innerHTML = '<div class="panel"><div class="form-row">' +
      '<label>Language <select id="fLang"><option value="">All</option><option value="en">English</option><option value="rn">Roman Nepali</option><option value="ne">Nepali</option></select></label>' +
      '<label>Intent <select id="fIntent"><option value="">All</option>' + ['PRICE', 'FORECAST', 'WEATHER', 'ADVICE', 'ARRIVALS', 'COMPARE', 'LOCATION', 'HELP', 'STOP', 'UNKNOWN'].map(function (i) { return '<option>' + i + '</option>'; }).join('') + '</select></label>' +
      '<label>Location <select id="fLoc"><option value="">All</option></select></label>' +
      '<label><input type="checkbox" id="fUnk"> Has unknown messages</label><span class="spacer"></span><span class="chip ok" id="liveChip">Live</span></div>' +
      '<div class="inbox"><div class="conv-list" id="convList"></div><div id="convPane"><div class="empty-state">Select a conversation.</div></div></div></div>';
    var open = null;
    api('GET', '/api/admin/data').then(function (d) {
      $('#fLoc').innerHTML += d.locations.map(function (l) { return '<option value="' + esc(l.key) + '">' + esc(l.name_en) + '</option>'; }).join('');
    }).catch(function () {});
    function list() {
      var q = '?lang=' + $('#fLang').value + '&intent=' + $('#fIntent').value + '&location=' + $('#fLoc').value + '&unknown=' + $('#fUnk').checked;
      panel('#convList', function () { return api('GET', '/api/admin/conversations' + q); }, function (d, box) {
        box.innerHTML = d.items.map(function (c) {
          return '<button class="conv' + (open === c.id ? ' active' : '') + '" data-id="' + c.id + '"><div class="row1"><b class="num">' + esc(c.phone) + '</b><span class="chip">' + esc(c.lang) + '</span></div>' +
            '<div class="row2">' + esc(c.last_text || '') + '</div><div class="row2">' + esc(c.location || 'no location') + ' · ' + esc((c.last_seen || '').slice(0, 16).replace('T', ' ')) + (c.demo ? ' · demo' : '') + '</div></button>';
        }).join('') || '<div class="empty-state">No conversations match these filters.</div>';
        $$('.conv', box).forEach(function (b) { b.onclick = function () { open = +b.dataset.id; $$('.conv', box).forEach(function (x) { x.classList.toggle('active', x === b); }); thread(); }; });
      });
    }
    function thread() {
      if (!open) return;
      panel('#convPane', function () { return api('GET', '/api/admin/conversations/' + open); }, function (d, box) {
        var f = d.farmer;
        box.innerHTML = '<div class="panel-head"><div><h3 class="num">' + esc(f.phone) + '</h3><p class="desc">' + esc(f.location || 'no location') + ' · ' + esc(f.lang) + ' · ' + esc(f.onboarding_state) + (f.subscribed ? '' : ' · opted out') + '</p></div></div>' +
          '<div class="convo" id="convo">' + d.messages.map(function (m) {
            var chips = m.direction === 'out' ? '<div class="chips">' + (m.intent ? '<span class="chip">' + esc(m.intent) + '</span>' : '') +
              (m.encoding ? '<span class="chip">' + (m.encoding === 'UCS2' ? 'UCS-2' : 'GSM-7') + '</span>' : '') + (m.segments ? '<span class="chip ' + (m.segments > 2 ? 'bad' : '') + '">' + m.segments + ' seg</span>' : '') +
              (m.location ? '<span class="chip">' + esc(m.location) + '</span>' : '') + '<span class="chip">' + esc((m.ts || '').slice(5, 16).replace('T', ' ')) + '</span></div>' : '';
            var tr = m.trace ? '<details><summary>How this reply was made</summary><pre>' + esc(JSON.stringify(m.trace, null, 1)) + '</pre></details>' : '';
            return '<div class="bubble ' + m.direction + '">' + esc(m.text) + chips + tr + '</div>';
          }).join('') + '</div>' +
          '<div class="form-row" style="margin-top:12px"><input type="text" id="opText" maxlength="480" placeholder="Reply as operator (sent through the outbox)" style="flex:1"><span class="counter" id="opCount"></span><button class="btn btn-primary" id="opSend">Send</button></div>';
        var c = $('#convo'); c.scrollTop = c.scrollHeight;
        $('#opText').oninput = function () { var v = $('#opText').value; $('#opCount').textContent = v ? v.length + ' chars' : ''; };
        $('#opSend').onclick = function () {
          var t = $('#opText').value.trim(); if (!t) return;
          api('POST', '/api/admin/conversations/' + open + '/reply', {text: t}).then(function () { $('#opText').value = ''; setTimeout(thread, 1500); }).catch(function (e) { alert(e.message); });
        };
      });
    }
    ['#fLang', '#fIntent', '#fLoc', '#fUnk'].forEach(function (s) { $(s).onchange = list; });
    list();
    function poll() {
      if (sse) { sse.close(); sse = null; }
      if (poller) return;
      var chip = $('#liveChip'); if (chip) { chip.className = 'chip info'; chip.textContent = 'Updates every 5 s'; }
      poller = setInterval(function () { if (currentPage === 'conversations' && document.visibilityState === 'visible') { list(); thread(); } }, POLL_MS);
    }
    if (statusCache.serverless || !window.EventSource) poll();
    else if (!sse) {
      sse = new EventSource('/api/admin/events');
      var t = null, opened = false;
      sse.addEventListener('message', function () { clearTimeout(t); t = setTimeout(function () { list(); thread(); }, 800); });
      sse.onopen = function () { opened = true; var c = $('#liveChip'); if (c) { c.className = 'chip ok'; c.textContent = 'Live'; } };
      sse.onerror = function () { if (!opened || sse.readyState === 2) poll(); };
    }
  };

  /* ---------- market & forecasts ---------- */
  PAGES.market = function (root, crop) {
    root.innerHTML = '<div class="panel"><div class="form-row"><label>Crop <select id="mCrop"></select></label><label><input type="checkbox" id="mAll"> Show all history</label>' +
      '<span class="desc" style="margin:0">Kalimati wholesale, primary variant, Rs/kg. Forecast ranges are P10 to P90, coloured by honest status.</span></div>' +
      '<div class="chart-box tall" id="mPrice"></div><div class="legend"><span class="chip ok">reliable</span><span class="chip warn">indicative</span><span class="chip">pattern only (seasonal range, not a forecast)</span></div>' +
      '<div class="grid g2" style="margin-top:12px"><div><p class="desc">Arrivals at Kalimati (tonnes per day)</p><div class="chart-box short" id="mArr"></div></div><div><p class="desc">Rain, whole-area average (mm per day)</p><div class="chart-box short" id="mRain"></div></div></div></div>' +
      '<div class="grid g2"><div class="panel"><h3>Forecasts</h3><p class="desc">Latest model run. Skill is versus the best baseline in walk-forward backtests.</p><div id="mFc"></div></div>' +
      '<div class="panel"><h3>Data health</h3><div id="mHealth"></div></div>' +
      '<div class="panel"><h3>Variant comparison</h3><p class="desc" id="mVarDesc"></p><div class="chart-box" id="mVar"></div></div>' +
      '<div class="panel"><h3>Weather and market, lagged correlation</h3><p class="desc">Correlation, not causation. Rain is the 7-day whole-area total, lagged 0-14 days, against 7-day price and arrivals changes.</p><div id="mCorr"></div></div>' +
      '<div class="panel span2"><h3>Latest 14 days</h3><div id="mLatest"></div></div></div>';
    function load(c) {
      clearCharts();
      panel('#mFc', function () { return api('GET', '/api/admin/market?crop=' + encodeURIComponent(c || '')); }, function (d) {
        var sel = $('#mCrop');
        if (!sel.options.length) { sel.innerHTML = d.crops.map(function (x) { return '<option value="' + x.key + '">' + esc(x.name) + '</option>'; }).join(''); sel.onchange = function () { load(sel.value); }; }
        sel.value = d.crop;
        drawMarket(d);
      });
    }
    $('#mAll').onchange = function () { load($('#mCrop').value); };
    load(crop);
  };
  function drawMarket(d) {
    var p = palette(), all = $('#mAll').checked;
    var hist = all ? d.history : d.history.slice(-365);
    var labels = hist.map(function (h) { return h.date; });
    var last = labels[labels.length - 1];
    var fut = d.forecasts.filter(function (f) { return f.target_date; }).map(function (f) { return f.target_date; }).sort();
    fut.forEach(function (t) { if (t > last && labels.indexOf(t) < 0) labels.push(t); });
    labels.sort();
    var idx = {}; labels.forEach(function (l, i) { idx[l] = i; });
    function series(fn) { var a = new Array(labels.length).fill(null); hist.forEach(function (h) { a[idx[h.date]] = fn(h); }); return a; }
    var colorFor = function (s) { return s === 'reliable' ? p.ok : s === 'indicative' ? p.warn : p.ink3; };
    var ds = [
      {label: 'Min', data: series(function (h) { return h.min; }), borderWidth: 0, pointRadius: 0, fill: false},
      {label: 'Max (band)', data: series(function (h) { return h.max; }), borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: p.brand + '1f'},
      {label: 'Average price', data: series(function (h) { return h.avg; }), borderColor: p.brand, borderWidth: 1.6, pointRadius: 0, tension: .1}
    ];
    var fan = d.forecasts.filter(function (f) { return f.p50 != null && /^d/.test(f.horizon); }).sort(function (a, b) { return a.target_date < b.target_date ? -1 : 1; });
    if (fan.length) {
      var lo = new Array(labels.length).fill(null), hi = lo.slice(), mid = lo.slice();
      var start = idx[last];
      lo[start] = hi[start] = mid[start] = fan[0].price0;
      fan.forEach(function (f) { var i = idx[f.target_date]; lo[i] = f.p10; hi[i] = f.p90; mid[i] = f.p50; });
      var col = colorFor(fan[0].status);
      ds.push({label: 'P10', data: lo, borderColor: col, borderDash: [3, 3], borderWidth: 1, pointRadius: 0, spanGaps: true, fill: false});
      ds.push({label: 'Forecast P10-P90', data: hi, borderColor: col, borderDash: [3, 3], borderWidth: 1, pointRadius: 0, spanGaps: true, fill: '-1', backgroundColor: col + '30'});
      ds.push({label: 'Forecast P50 (7-28 days)', data: mid, borderColor: col, borderWidth: 2, pointRadius: fan.map ? 3 : 0, spanGaps: true,
        pointBackgroundColor: labels.map(function (l) { var f = fan.find(function (x) { return x.target_date === l; }); return f ? colorFor(f.status) : col; })});
    }
    d.forecasts.filter(function (f) { return f.p50 != null && /^m/.test(f.horizon); }).forEach(function (f) {
      var a = new Array(labels.length).fill(null), i = idx[f.target_date];
      if (i == null) return;
      a[i] = f.p50;
      ds.push({label: f.horizon + ' outlook (' + f.status + ')', data: a, type: 'line', showLine: false, pointRadius: 6, pointStyle: 'rectRot', borderColor: colorFor(f.status), backgroundColor: colorFor(f.status)});
    });
    chart('#mPrice', {type: 'line', data: {labels: labels, datasets: ds}, options: {interaction: {mode: 'index', intersect: false},
      plugins: {legend: {labels: {filter: function (it) { return !/^(Min|P10)$/.test(it.text); }}}}, scales: {x: {ticks: {maxTicksLimit: 10}}, y: {title: {display: true, text: 'Rs/kg'}}}}});
    var arrMap = {}; d.arrivals.forEach(function (a) { arrMap[a.date] = a.arrivals_kg; });
    var rainMap = {}; d.rain.forEach(function (r) { rainMap[r.date] = r.rain; });
    chart('#mArr', {type: 'bar', data: {labels: labels, datasets: [{label: 'Arrivals (t)', data: labels.map(function (l) { return arrMap[l] != null ? arrMap[l] / 1000 : null; }), backgroundColor: p.brand5}]},
      options: {plugins: {legend: {display: false}}, scales: {x: {ticks: {maxTicksLimit: 8}}}}});
    chart('#mRain', {type: 'bar', data: {labels: labels, datasets: [{label: 'Rain (mm)', data: labels.map(function (l) { return rainMap[l] != null ? rainMap[l] : null; }), backgroundColor: p.info}]},
      options: {plugins: {legend: {display: false}}, scales: {x: {ticks: {maxTicksLimit: 8}}}}});
    $('#mFc').innerHTML = table([{t: 'Horizon', k: 'horizon'}, {t: 'Target', k: 'target_date'}, {t: 'P10', r: 1, f: function (r) { return fmt(r.p10); }},
      {t: 'P50', r: 1, f: function (r) { return fmt(r.p50); }}, {t: 'P90', r: 1, f: function (r) { return fmt(r.p90); }},
      {t: 'Change', r: 1, f: function (r) { return r.pct_change_p50 == null ? 'n/a' : fmt(r.pct_change_p50, 1) + '%'; }},
      {t: 'Status', f: function (r) { return statusChip(r.status); }}, {t: 'Model', k: 'model_name'},
      {t: 'Skill', r: 1, f: function (r) { return pct(r.backtest && r.backtest.skill); }}], d.forecasts, {empty: 'Not trained yet. Go to Data & training and click Train all.'});
    var h = d.health;
    $('#mHealth').innerHTML = '<div class="grid g2">' + mini('First price day', h.first) + mini('Latest price day', h.last) + mini('Days with a real price', fmt(h.days_with_price) + ' of ' + fmt(h.calendar_days)) +
      mini('Missing days', fmt(h.missing_days)) + mini('Carried-over share', pct(h.carried_over_share)) + mini('Primary variant', d.variant) + '</div>';
    $('#mVarDesc').textContent = d.variants.name ? 'Primary variant (' + d.variant + ') against ' + d.variants.name + '.' : 'Only one variant has data for this crop.';
    if (d.variants.name) {
      var vmap = {}; d.variants.series.forEach(function (v) { vmap[v.date] = v.avg; });
      chart('#mVar', {type: 'line', data: {labels: hist.map(function (x) { return x.date; }), datasets: [
        {label: d.variant, data: hist.map(function (x) { return x.avg; }), borderColor: p.brand, pointRadius: 0, borderWidth: 1.4},
        {label: d.variants.name, data: hist.map(function (x) { return vmap[x.date] != null ? vmap[x.date] : null; }), borderColor: p.accent, pointRadius: 0, borderWidth: 1.4}]},
        options: {scales: {x: {ticks: {maxTicksLimit: 8}}}}});
    } else $('#mVar').innerHTML = '<div class="chart-missing">No second variant.</div>';
    var cc = d.corr.crop;
    $('#mCorr').innerHTML = cc ? '<div class="table-wrap"><table class="heat"><tr><td></td>' + d.corr.lags.map(function (l) { return '<td style="font-size:11px;text-align:center;color:var(--ink-3)">' + l + '</td>'; }).join('') + '</tr>' +
      [['rain_price', 'Rain vs price'], ['rain_arrivals', 'Rain vs arrivals'], ['tmax_price', 'Tmax vs price']].map(function (row) {
        var r = cc[row[0]];
        return '<tr><td style="font-size:12px;padding-right:8px;white-space:nowrap">' + row[1] + '</td>' + r.r.map(function (v, i) {
          var col = v == null ? 'var(--surface-2)' : v > 0 ? 'color-mix(in srgb, var(--info) ' + Math.round(Math.abs(v) * 250) + '%, transparent)' : 'color-mix(in srgb, var(--bad) ' + Math.round(Math.abs(v) * 250) + '%, transparent)';
          return '<td title="r=' + (v == null ? 'n/a' : v.toFixed(2)) + ', n=' + r.n[i] + '" style="background:' + col + ';height:24px;font-size:10px;text-align:center">' + (v == null ? '' : v.toFixed(2).replace('0.', '.')) + '</td>'; }).join('') + '</tr>';
      }).join('') + '</table></div><p class="desc" style="margin-top:6px">Columns are lag in days. Hover a cell for r and sample size. Blue positive, red negative.</p>' : '<div class="empty-state">Correlation is computed during training.</div>';
    $('#mLatest').innerHTML = table([{t: 'Date', k: 'date'}, {t: 'Avg', r: 1, f: function (r) { return fmt(r.avg_kg, 1); }}, {t: 'Min', r: 1, f: function (r) { return fmt(r.min_kg, 1); }},
      {t: 'Max', r: 1, f: function (r) { return fmt(r.max_kg, 1); }}, {t: 'Carried over', f: function (r) { return r.carried_over ? 'yes' : ''; }}], d.latest);
  }
  function mini(label, value) { return '<div><div class="kpi-label">' + esc(label) + '</div><div style="font-weight:600" class="num">' + esc(value == null ? 'n/a' : value) + '</div></div>'; }

  /* ---------- models & evaluation ---------- */
  PAGES.models = function (root) {
    root.innerHTML = '<div class="grid g3"><div class="panel"><h3>Latest run</h3><div id="moRun"></div></div><div class="panel"><h3>Model footprint</h3><p class="desc">Small enough for a laptop or a cheap server.</p><div id="moFoot"></div></div>' +
      '<div class="panel"><h3>Intent classifier</h3><p class="desc">TF-IDF character n-grams + logistic regression, 20% held out.</p><div id="moIntent"></div></div></div>' +
      '<div class="panel"><div class="panel-head"><div><h3>Forecast status by crop and horizon</h3><p class="desc">Cell shows skill against the best baseline. Click a cell for its backtest. Many cells being pattern only is expected and reported honestly.</p></div>' +
      '<a class="btn" href="/api/admin/reports/model_card.md">Download model card</a></div><div id="moMatrix"></div></div>' +
      '<div id="moCell" class="grid g2"></div>' +
      '<div class="grid g2"><div class="panel"><h3>Weather weeks 2-4: skill vs climatology</h3><p class="desc">A model is kept only if it beats climatology by 3% or more. Otherwise replies say climatology, not a forecast.</p><div class="chart-box" id="moWxChart"></div><div id="moWx"></div></div>' +
      '<div class="panel"><h3>Intent confusion matrix</h3><div id="moConf"></div></div>' +
      '<div class="panel span2"><h3>Casual messages: what still fails</h3><div id="moCasual"></div></div>' +
      '<div class="panel span2"><h3>Run history</h3><div id="moRuns"></div></div></div>';
    panel('#moRun', function () { return api('GET', '/api/admin/models'); }, function (d, box) {
      if (!d.run) { box.innerHTML = '<div class="empty-state">No model run yet. Train on Data & training.</div>'; return; }
      var s = d.run.summary || {}, sc = s.status_counts || {};
      box.innerHTML = '<div class="grid g2">' + mini('Run', '#' + d.run.id + ' (' + d.run.mode + ')') + mini('Finished', (d.run.finished_at || 'running').replace('T', ' ').slice(0, 16)) +
        mini('Reliable cells', sc.reliable || 0) + mini('Indicative cells', sc.indicative || 0) + mini('Pattern only', sc['pattern only'] || 0) + mini('Unavailable', sc.unavailable || 0) + '</div>';
      var f = d.footprint;
      $('#moFoot').innerHTML = '<div class="grid g2">' + mini('Total on disk', fmt(f.total_bytes / 1024) + ' KB') + mini('Price models', f.price_files + ' files, ' + fmt(f.price_bytes / 1024) + ' KB') +
        mini('Median CPU inference', fmt(f.median_inference_ms, 2) + ' ms') + mini('Intent model', fmt(f.intent_bytes / 1024) + ' KB') + mini('Weather models', fmt(f.weather_bytes / 1024) + ' KB') + mini('Runtime LLM', 'none') + '</div>';
      var it = d.intent;
      $('#moIntent').innerHTML = it ? '<div class="grid g2">' + mini('Held-out accuracy', pct(it.accuracy)) + mini('Test examples', it.n_test) +
        Object.keys(it.by_lang).map(function (l) { return mini('Accuracy ' + l, pct(it.by_lang[l])); }).join('') + mini('Inference', fmt(it.inference_ms, 2) + ' ms') +
        mini('Casual set, whole NLU', it.casual_pipeline_accuracy == null ? 'n/a' : pct(it.casual_pipeline_accuracy) + ' of ' + it.casual_n) +
        mini('Casual set, classifier only', pct(it.casual_classifier_accuracy)) + '</div>' +
        (it.comparison ? '<p class="desc" style="margin:12px 0 6px">Model comparison (cross-validation on the training split). Kept: <b>' + esc(it.chosen) + '</b></p>' +
          table([{t: 'Model', k: 'name'}, {t: 'CV accuracy', r: 1, f: function (r) { return pct(r.cv_accuracy, 2); }}, {t: 'Spread', r: 1, f: function (r) { return pct(r.cv_std, 2); }},
            {t: 'Time', r: 1, f: function (r) { return fmt(r.seconds, 1) + ' s'; }}], Object.keys(it.comparison).map(function (k) { return Object.assign({name: k}, it.comparison[k]); })) : '')
        : '<div class="empty-state">Not trained.</div>';
      if (it) $('#moCasual').innerHTML = '<p class="desc">Hand-written casual and noisy messages, run through the whole understanding step (rules, spelling fixes, classifier). ' +
        (it.casual_by_lang ? Object.keys(it.casual_by_lang).map(function (l) { return l + ' ' + pct(it.casual_by_lang[l]); }).join(', ') : '') + '. Weak spots below.</p>' +
        table([{t: 'Message', k: 'text'}, {t: 'Expected', k: 'expected'}, {t: 'Got', k: 'got'}, {t: 'Confidence', r: 1, f: function (r) { return fmt(r.confidence, 2); }}],
          it.casual_misses || [], {empty: 'Every casual message was understood.'});
      if (it) $('#moConf').innerHTML = '<div class="table-wrap"><table class="heat"><tr><td></td>' + it.labels.map(function (l) { return '<td style="font-size:10px;writing-mode:vertical-rl;padding:2px">' + l + '</td>'; }).join('') + '</tr>' +
        it.confusion.map(function (row, i) { var tot = row.reduce(function (a, b) { return a + b; }, 0) || 1; return '<tr><td style="font-size:11px;padding-right:6px">' + it.labels[i] + '</td>' + row.map(function (v, j) {
          return '<td title="' + v + '" style="text-align:center;font-size:10px;height:20px;background:' + (v ? 'color-mix(in srgb, ' + (i === j ? 'var(--ok)' : 'var(--bad)') + ' ' + Math.round(20 + 80 * v / tot) + '%, transparent)' : 'transparent') + '">' + (v || '') + '</td>'; }).join('') + '</tr>'; }).join('') + '</table></div><p class="desc" style="margin-top:6px">Rows are true intents, columns predicted.</p>';
      var crops = []; d.matrix.forEach(function (m) { if (crops.indexOf(m.crop) < 0) crops.push(m.crop); }); crops.sort();
      var get = function (c, h) { return d.matrix.find(function (m) { return m.crop === c && m.horizon === h; }); };
      $('#moMatrix').innerHTML = d.matrix.length ? '<div class="table-wrap" style="max-height:none"><table class="matrix"><thead><tr><th>Crop</th>' + d.horizons.map(function (h) { return '<th style="text-align:center">' + h + '</th>'; }).join('') + '</tr></thead><tbody>' +
        crops.map(function (c) { return '<tr><td>' + esc(c) + '</td>' + d.horizons.map(function (h) { var m = get(c, h);
          return m ? '<td class="' + statusClass(m.status) + '" data-c="' + c + '" data-h="' + h + '" title="' + esc(m.status + ', model ' + m.model + ', coverage ' + pct(m.coverage) + ', direction ' + pct(m.dir_acc)) + '">' + (m.skill == null ? 'n/a' : fmt(m.skill * 100, 0) + '%') + '</td>' : '<td class="status-unavailable">n/a</td>'; }).join('') + '</tr>'; }).join('') +
        '</tbody></table></div><div class="legend"><span class="chip ok">reliable</span><span class="chip warn">indicative</span><span class="chip">pattern only</span><span class="chip bad">unavailable</span></div>' : '<div class="empty-state">No backtests yet.</div>';
      $$('#moMatrix td[data-c]').forEach(function (td) { td.onclick = function () { $$('#moMatrix td').forEach(function (x) { x.classList.remove('sel'); }); td.classList.add('sel'); cell(td.dataset.c, td.dataset.h); }; });
      var first = $('#moMatrix td[data-c]'); if (first) { first.classList.add('sel'); cell(first.dataset.c, first.dataset.h); }
      $('#moWx').innerHTML = table([{t: 'Location', k: 'location'}, {t: 'Variable', k: 'variable'}, {t: 'Week', k: 'week', r: 1}, {t: 'MAE model', r: 1, f: function (r) { return fmt(r.mae_model, 2); }},
        {t: 'MAE climatology', r: 1, f: function (r) { return fmt(r.mae_clim, 2); }}, {t: 'Skill', r: 1, f: function (r) { return pct(r.skill); }}, {t: 'Kept', f: function (r) { return r.kept ? '<span class="chip ok">model</span>' : '<span class="chip">climatology</span>'; }}], d.weather);
      var rain = d.weather.filter(function (w) { return w.variable === 'rain_total'; }), locs = [];
      rain.forEach(function (w) { if (locs.indexOf(w.location) < 0) locs.push(w.location); });
      var p = palette();
      chart('#moWxChart', {type: 'bar', data: {labels: locs, datasets: [2, 3, 4].map(function (wk, i) { return {label: 'Rain, week ' + wk, backgroundColor: p.series[i],
        data: locs.map(function (l) { var r = rain.find(function (x) { return x.location === l && x.week === wk; }); return r && r.skill != null ? r.skill * 100 : null; })}; })},
        options: {scales: {y: {title: {display: true, text: 'skill vs climatology, %'}}}}});
      $('#moRuns').innerHTML = table([{t: 'Run', k: 'id', r: 1}, {t: 'Mode', k: 'mode'}, {t: 'Started', f: function (r) { return esc((r.started_at || '').replace('T', ' ').slice(0, 16)); }},
        {t: 'Finished', f: function (r) { return esc((r.finished_at || 'not finished').replace('T', ' ').slice(0, 16)); }}, {t: 'Data', f: function (r) { return 'v' + r.data_version; }},
        {t: 'Status counts', f: function (r) { return esc(JSON.stringify((r.summary || {}).status_counts || {})); }}, {t: 'Intent acc.', r: 1, f: function (r) { return pct((r.summary || {}).intent_accuracy); }}], d.runs);
    });
  };
  function cell(crop, h) {
    var box = $('#moCell');
    box.innerHTML = '<div class="panel span2" id="cellHead"></div><div class="panel"><h3>Actual vs predicted (test windows)</h3><p class="desc">Out-of-sample walk-forward predictions with the 80% conformal interval.</p><div class="chart-box" id="cAvp"></div></div>' +
      '<div class="panel"><h3>Error by horizon</h3><p class="desc">Mean absolute error in Rs/kg: chosen model vs best baseline.</p><div class="chart-box" id="cErr"></div></div>' +
      '<div class="panel"><h3>Interval calibration</h3><p class="desc">Nominal vs actual coverage, each point calibrated only on earlier residuals.</p><div class="chart-box" id="cCal"></div></div>' +
      '<div class="panel"><h3>Residuals (log ratio)</h3><div class="chart-box" id="cRes"></div></div>' +
      '<div class="panel"><h3>Permutation feature importance</h3><p class="desc">Increase in MAE when a feature is shuffled (learned models only).</p><div class="chart-box" id="cImp"></div></div>' +
      '<div class="panel"><h3>Live accuracy</h3><p class="desc">Every production forecast is logged; the realised price fills in as new data arrives.</p><div id="cLed"></div></div>';
    panel('#cellHead', function () { return api('GET', '/api/admin/models/cell?crop=' + crop + '&horizon=' + h); }, function (d, head) {
      var p = palette(), chosen = d.by_model.find(function (m) { return m.chosen; }) || {};
      head.innerHTML = '<h3>' + esc(crop) + ', ' + esc(h) + '</h3><p class="desc">Chosen ' + esc(chosen.model) + ' (' + esc(chosen.status) + '); best baseline ' + esc(d.meta.best_baseline) + '. Artifact ' + fmt((d.meta.file_bytes || 0) / 1024, 1) + ' KB, inference ' + fmt(d.meta.inference_ms, 2) + ' ms.</p>' +
        table([{t: 'Model', f: function (r) { return esc(r.model) + (r.chosen ? ' <span class="chip ok">chosen</span>' : ''); }}, {t: 'MAE Rs', r: 1, f: function (r) { return fmt(r.mae_rs, 2); }},
          {t: 'MAPE', r: 1, f: function (r) { return pct(r.mape); }}, {t: 'Direction', r: 1, f: function (r) { return pct(r.dir_acc); }}, {t: 'Skill', r: 1, f: function (r) { return pct(r.skill); }},
          {t: 'Pinball', r: 1, f: function (r) { return fmt(r.pinball, 4); }}, {t: '80% coverage', r: 1, f: function (r) { return pct(r.coverage); }}, {t: 'Mean width', r: 1, f: function (r) { return fmt(r.width, 2); }},
          {t: 'Test origins', r: 1, k: 'n_test'}, {t: 'Status', f: function (r) { return statusChip(r.status); }}], d.by_model);
      var pr = d.preds;
      chart('#cAvp', {type: 'line', data: {labels: pr.map(function (x) { return x.date; }), datasets: [
        {label: 'lo', data: pr.map(function (x) { return x.lo; }), pointRadius: 0, borderWidth: 0},
        {label: '80% interval', data: pr.map(function (x) { return x.hi; }), pointRadius: 0, borderWidth: 0, fill: '-1', backgroundColor: p.brand + '22'},
        {label: 'Actual', data: pr.map(function (x) { return x.actual; }), borderColor: p.ink3, pointRadius: 0, borderWidth: 1.2},
        {label: 'Predicted', data: pr.map(function (x) { return x.pred; }), borderColor: p.brand, pointRadius: 0, borderWidth: 1.6}]},
        options: {plugins: {legend: {labels: {filter: function (i) { return i.text !== 'lo'; }}}}, scales: {x: {ticks: {maxTicksLimit: 8}}}}});
      var hs = ['d7', 'd14', 'd21', 'd28', 'm1', 'm2', 'm3'], base = ['persistence', 'seasonal_naive', 'mean_reversion'];
      chart('#cErr', {type: 'bar', data: {labels: hs, datasets: [
        {label: 'Chosen model', backgroundColor: p.brand, data: hs.map(function (x) { var r = d.by_horizon.find(function (b) { return b.horizon === x && b.chosen; }); return r ? r.mae_rs : null; })},
        {label: 'Best baseline', backgroundColor: p.accent, data: hs.map(function (x) { var rs = d.by_horizon.filter(function (b) { return b.horizon === x && base.indexOf(b.model) >= 0 && b.mae_rs != null; });
          return rs.length ? Math.min.apply(null, rs.map(function (b) { return b.mae_rs; })) : null; })}]}, options: {scales: {y: {beginAtZero: true, title: {display: true, text: 'Rs/kg'}}}}});
      chart('#cCal', {type: 'line', data: {labels: d.calibration.map(function (c) { return pct(c.nominal, 0); }), datasets: [
        {label: 'Actual coverage', data: d.calibration.map(function (c) { return c.actual * 100; }), borderColor: p.brand, pointRadius: 3},
        {label: 'Perfect calibration', data: d.calibration.map(function (c) { return c.nominal * 100; }), borderColor: p.ink3, borderDash: [4, 4], pointRadius: 0}]},
        options: {scales: {y: {min: 0, max: 100, title: {display: true, text: '% of outcomes inside interval'}}}}});
      chart('#cRes', {type: 'bar', data: {labels: d.residuals.edges.slice(0, -1).map(function (e) { return e.toFixed(2); }), datasets: [{label: 'count', data: d.residuals.counts, backgroundColor: p.brand5}]},
        options: {plugins: {legend: {display: false}}, scales: {x: {ticks: {maxTicksLimit: 8}}}}});
      if (d.importance.length) bar('#cImp', d.importance.map(function (x) { return [x.feature, x.importance]; }), p.brand, true);
      else $('#cImp').innerHTML = '<div class="chart-missing">Not computed for this cell (baselines, or fast mode beyond 14 days).</div>';
      $('#cLed').innerHTML = table([{t: 'Origin', k: 'origin_date'}, {t: 'Target', k: 'target_date'}, {t: 'P10', r: 1, f: function (r) { return fmt(r.p10); }}, {t: 'P50', r: 1, f: function (r) { return fmt(r.p50); }},
        {t: 'P90', r: 1, f: function (r) { return fmt(r.p90); }}, {t: 'Realised', r: 1, f: function (r) { return r.realised == null ? 'waiting' : fmt(r.realised); }},
        {t: 'Inside range', f: function (r) { return r.realised == null ? '' : (r.realised >= r.p10 && r.realised <= r.p90 ? 'yes' : 'no'); }}], d.ledger, {empty: 'No live forecasts logged yet.'});
    });
  }

  /* ---------- data & training ---------- */
  PAGES.data = function (root) {
    root.innerHTML = '<div class="grid g2"><div class="panel"><h3>Upload data bundle</h3><p class="desc">One ZIP with the scraper and GEE CSVs. Files are recognised by their columns, not their names.</p>' +
      '<div class="drop" id="drop">Drop a .zip here or <label style="text-decoration:underline;cursor:pointer">choose a file<input type="file" id="file" accept=".zip" hidden></label></div><div id="upStatus" style="margin-top:10px"></div></div>' +
      '<div class="panel"><h3>Train all models</h3><p class="desc">Data prep, price models per crop, weather models, intent classifier, reports. One job at a time.</p>' +
      '<div class="form-row"><label>Mode <select id="mode"><option value="fast">fast (about 3 min)</option><option value="full">full (up to 15 min)</option></select></label>' +
      '<button class="btn btn-primary" id="trainBtn">Train all</button><button class="btn" id="cancelBtn" disabled>Cancel</button></div>' +
      '<div class="progress"><i id="prog" style="width:0"></i></div><p class="desc" id="jobLine" style="margin-top:6px"></p><div class="log" id="jobLog">No training job yet.</div></div></div>' +
      '<div class="panel"><h3>Validation report (active dataset)</h3><div id="report"></div></div>' +
      '<div class="grid g2"><div class="panel"><h3>System check</h3><div id="sys"></div></div><div class="panel"><h3>Dataset versions</h3><div id="versions"></div></div></div>';
    panel('#report', function () { return api('GET', '/api/admin/data'); }, function (d, box) {
      $('#mode').value = d.default_mode || 'fast';
      renderReport(d.report, box);
      $('#versions').innerHTML = table([{t: 'Version', f: function (r) { return 'v' + r.id + (r.active ? ' <span class="chip ok">active</span>' : ''); }}, {t: 'Created', f: function (r) { return esc((r.created_at || '').replace('T', ' ').slice(0, 16)); }},
        {t: 'Checksum', k: 'checksum'}, {t: 'Type', f: function (r) { return r.is_sample ? '<span class="chip warn">sample</span>' : 'real'; }}], d.versions);
      if (d.last_job) showJob(d.last_job);
      if (d.last_job && d.last_job.status === 'running') streamJob(d.last_job.id);
    });
    panel('#sys', function () { return api('GET', '/api/admin/syscheck'); }, function (d, box) {
      box.innerHTML = d.checks.map(function (c) { return '<div class="check"><span class="dot ' + (c.ok ? 'ok' : 'bad') + '"></span><b>' + esc(c.name) + '</b><span>' + esc(c.detail) + '</span></div>'; }).join('');
    });
    var drop = $('#drop');
    ['dragenter', 'dragover'].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('over'); }); });
    ['dragleave', 'drop'].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('over'); }); });
    drop.addEventListener('drop', function (e) { if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); });
    $('#file').onchange = function () { if (this.files[0]) upload(this.files[0]); };
    $('#trainBtn').onclick = function () { startTraining($('#mode').value); };
    if (statusCache.serverless) {
      $('#trainBtn').disabled = true;
      $('#jobLine').textContent = 'Training is turned off on this host. Train locally, run scripts/prepare_deploy.py, then redeploy.';
    }
    $('#cancelBtn').onclick = function () { var id = $('#cancelBtn').dataset.job; if (id) api('POST', '/api/admin/jobs/' + id + '/cancel', {}); };
  };
  function upload(f) {
    var fd = new FormData(); fd.append('file', f);
    $('#upStatus').innerHTML = '<div class="skel"></div>Uploading and validating ' + esc(f.name) + '...';
    api('POST', '/api/admin/upload', fd, true).then(function (r) {
      $('#upStatus').innerHTML = '<div class="banner info" style="margin:0">' + (r.report.skipped ? esc(r.report.skipped) : 'Loaded as dataset v' + r.version_id + '.') + ' <button class="btn" id="trainNow">Train now</button></div>';
      $('#trainNow').onclick = function () { startTraining($('#mode').value); };
      renderReport(r.report, $('#report')); loadStatus();
    }).catch(function (e) { $('#upStatus').innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
  }
  function renderReport(r, box) {
    if (!r) { box.innerHTML = '<div class="empty-state">No dataset loaded yet. Upload a ZIP above.</div>'; return; }
    box.innerHTML = (r.warnings && r.warnings.length ? '<div class="banner warn" style="margin:0 0 12px">' + r.warnings.map(esc).join('<br>') + '</div>' : '') +
      '<div class="grid g2"><div><p class="desc">Files detected by column signature</p>' + table([{t: 'File', k: 'name'}, {t: 'Detected as', k: 'kind'}, {t: 'Rows', r: 1, f: function (x) { return fmt(x.rows); }}], r.files || []) + '</div>' +
      '<div><p class="desc">Farmer locations from the weather file (boundary_mean is the whole-area average, not offered to farmers)</p>' + table([{t: 'Key', k: 'key'}, {t: 'Name', k: 'name'},
        {t: 'Offered', f: function (x) { return x.selectable ? 'yes' : 'no (area average)'; }}, {t: 'Live forecast', f: function (x) { return x.has_coords ? 'yes' : 'history only'; }}], r.locations || []) + '</div>' +
      '<div><p class="desc">Per-crop price days (primary variant), ' + esc((r.date_range || []).join(' to ')) + '</p>' + table([{t: 'Crop', k: 'crop'}, {t: 'Variant', k: 'variant'}, {t: 'Days', r: 1, k: 'days'},
        {t: 'Missing', r: 1, k: 'missing_days'}, {t: 'Carried over', r: 1, f: function (x) { return pct(x.carried_over_share); }}], r.crops || []) + '</div>' +
      '<div><p class="desc">Weather coverage per location</p>' + table([{t: 'Location', k: 'location'}, {t: 'Rows', r: 1, k: 'rows'}, {t: 'From', k: 'first'}, {t: 'To', k: 'last'},
        {t: 'Missing days', r: 1, k: 'missing_days'}], r.weather_coverage || []) + '</div></div>';
  }
  function startTraining(mode) {
    api('POST', '/api/admin/train', {mode: mode}).then(function (r) { streamJob(r.job_id); }).catch(function (e) { alert(e.message); });
  }
  function showJob(j) {
    if (!$('#prog')) return;
    $('#prog').style.width = Math.round((j.progress || 0) * 100) + '%';
    var dur = j.finished_at && j.started_at ? ((new Date(j.finished_at) - new Date(j.started_at)) / 1000).toFixed(0) + ' s' : '';
    $('#jobLine').textContent = 'Job #' + j.id + ': ' + j.status + ' ' + Math.round((j.progress || 0) * 100) + '%' + (dur ? ', took ' + dur : '') + (j.error ? ', ' + j.error : '');
    $('#jobLog').textContent = j.log || '';
    $('#jobLog').scrollTop = 1e9;
    var running = j.status === 'running';
    $('#trainBtn').disabled = running || !!statusCache.serverless; $('#cancelBtn').disabled = !running; $('#cancelBtn').dataset.job = j.id;
  }
  function streamJob(id) {
    if (jobSse) { jobSse.close(); jobSse = null; }
    if (jobPoller) { clearInterval(jobPoller); jobPoller = null; }
    function done(j) { return j.status !== 'running' && j.status !== 'queued'; }
    function pollJob() {
      if (jobSse) { jobSse.close(); jobSse = null; }
      if (jobPoller) return;
      jobPoller = setInterval(function () {
        api('GET', '/api/admin/jobs/' + id).then(function (j) {
          showJob(j); if (done(j)) { clearInterval(jobPoller); jobPoller = null; loadStatus(); }
        }).catch(function () { /* keep trying */ });
      }, POLL_MS);
    }
    if (statusCache.serverless || !window.EventSource) { pollJob(); return; }
    jobSse = new EventSource('/api/admin/jobs/' + id + '/stream');
    jobSse.addEventListener('job', function (e) {
      var j = JSON.parse(e.data); showJob(j);
      if (done(j)) { jobSse.close(); jobSse = null; loadStatus(); }
    });
    jobSse.onerror = function () { if (jobSse) pollJob(); };
  }

  /* ---------- test console ---------- */
  PAGES.console = function (root) {
    var tabs = [['chat', 'Chat test'], ['forecast', 'Forecast tester'], ['weather', 'Weather tester'], ['scen', 'Scenario runner'], ['tpl', 'Template check']];
    root.innerHTML = '<div class="panel"><div class="tabs" id="ctabs">' + tabs.map(function (t, i) { return '<button data-t="' + t[0] + '" class="' + (i ? '' : 'active') + '">' + t[1] + '</button>'; }).join('') + '</div><div id="ctab" style="padding-top:12px"></div></div>';
    $$('#ctabs button').forEach(function (b) { b.onclick = function () { $$('#ctabs button').forEach(function (x) { x.classList.toggle('active', x === b); }); clearCharts(); CT[b.dataset.t]($('#ctab')); }; });
    CT.chat($('#ctab'));
  };
  var CT = {};
  CT.chat = function (box) {
    box.innerHTML = '<p class="desc">The real engine, exactly as SMS would see it. The debug trace on the right shows state, intent probabilities, slots, data used, model and status, SMS stats and latency.</p><div class="console-chat"><div id="consoleChat" class="chat-app"></div></div>';
    var root = $('#consoleChat'); root.dataset.logo = $('#app').dataset.logo;
    AgahiChat.mount(root, {mode: 'admin', rail: false, trace: true, csrf: function () { return CSRF; }});
  };
  function options(arr, sel) { return arr.map(function (x) { return '<option value="' + esc(x[0]) + '"' + (x[0] === sel ? ' selected' : '') + '>' + esc(x[1]) + '</option>'; }).join(''); }
  function smsBoxes(sms) {
    return ['en', 'rn', 'ne'].map(function (l) { var s = sms[l]; return '<div class="sms-box"><div class="kpi-label">' + {en: 'English', rn: 'Roman Nepali', ne: 'Nepali'}[l] + '</div><div class="t">' + esc(s.text) + '</div><div class="m">' +
      s.segments + ' segment' + (s.segments > 1 ? 's' : '') + ' · ' + (s.encoding === 'UCS2' ? 'UCS-2' : 'GSM-7') + ' · ' + s.chars + ' chars' + (s.segments > 2 ? ' <span class="chip bad">over budget</span>' : '') + '</div></div>'; }).join('');
  }
  CT.forecast = function (box) {
    api('GET', '/api/admin/market').then(function (m) {
      box.innerHTML = '<div class="form-row"><label>Crop <select id="tfCrop">' + options(m.crops.map(function (c) { return [c.key, c.name]; })) + '</select></label>' +
        '<label>Horizon <select id="tfH">' + options([['d7', '7 days'], ['d14', '14 days'], ['d21', '21 days'], ['d28', '28 days'], ['m1', '1 month'], ['m2', '2 months'], ['m3', '3 months']]) + '</select></label>' +
        '<button class="btn btn-primary" id="tfGo">Get forecast</button></div><div id="tfOut"></div>';
      $('#tfGo').onclick = run; run();
    }).catch(function (e) { box.innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
    function run() {
      panel('#tfOut', function () { return api('GET', '/api/admin/test/forecast?crop=' + $('#tfCrop').value + '&horizon=' + $('#tfH').value); }, function (d, out) {
        out.innerHTML = '<div class="grid g2"><div><div class="grid g4">' + mini('P10', fmt(d.p10)) + mini('P50', fmt(d.p50)) + mini('P90', fmt(d.p90)) + mini('Today', fmt(d.price0)) + '</div>' +
          '<p style="margin:12px 0">' + statusChip(d.status) + ' model: ' + esc(d.model || 'none') + '</p>' +
          table([{t: 'Model', f: function (r) { return esc(r.model) + (r.chosen ? ' <span class="chip ok">chosen</span>' : ''); }}, {t: 'MAE Rs', r: 1, f: function (r) { return fmt(r.mae_rs, 2); }},
            {t: 'Skill', r: 1, f: function (r) { return pct(r.skill); }}, {t: 'Direction', r: 1, f: function (r) { return pct(r.dir_acc); }}, {t: 'Coverage', r: 1, f: function (r) { return pct(r.coverage); }},
            {t: 'n', r: 1, k: 'n_test'}], d.baselines) + '</div><div>' + smsBoxes(d.sms) + '</div></div>';
      });
    }
  };
  CT.weather = function (box) {
    api('GET', '/api/admin/data').then(function (dd) {
      box.innerHTML = '<div class="form-row"><label>Location <select id="twLoc">' + options(dd.locations.map(function (l) { return [l.key, l.name_en]; })) + '</select></label>' +
        '<label>Horizon <select id="twH">' + options([['d7', 'Next 7 days'], ['w24', 'Weeks 2-4'], ['m13', 'Months 1-3']]) + '</select></label><button class="btn btn-primary" id="twGo">Get weather</button></div><div id="twOut"></div>';
      $('#twGo').onclick = run; run();
    }).catch(function (e) { box.innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
    function run() {
      panel('#twOut', function () { return api('GET', '/api/admin/test/weather?location=' + $('#twLoc').value + '&horizon=' + $('#twH').value); }, function (d, out) {
        out.innerHTML = '<div class="grid g2"><div><p>Method: <span class="chip ' + (d.method === 'live' ? 'ok' : 'warn') + '">' + esc(d.method) + '</span></p><pre class="log">' + esc(JSON.stringify(d.values, null, 1)) + '</pre></div><div>' + smsBoxes(d.sms) + '</div></div>';
      });
    }
  };
  CT.scen = function (box) {
    box.innerHTML = '<div class="form-row"><button class="btn btn-primary" id="scGo">Run all scenarios</button><span id="scSum" class="desc" style="margin:0"></span></div><div id="scOut"></div>';
    panel('#scOut', function () { return api('GET', '/api/admin/test/scenarios'); }, function (d, out) {
      out.innerHTML = d.scenarios.map(function (s) { return '<div class="scen"><b>' + esc(s.name) + '</b> <span class="desc">' + esc(s.steps.join(' → ')) + '</span></div>'; }).join('');
    });
    $('#scGo').onclick = function () {
      $('#scGo').disabled = true; $('#scSum').textContent = 'Running through the real engine...';
      panel('#scOut', function () { return api('POST', '/api/admin/test/scenarios/run', {name: null}); }, function (d, out) {
        $('#scGo').disabled = false;
        $('#scSum').innerHTML = '<b>' + d.passed + ' of ' + d.total + ' passed</b>';
        out.innerHTML = d.results.map(function (r) {
          return '<details class="scen"><summary><span class="chip ' + (r.passed ? 'ok' : 'bad') + '">' + (r.passed ? 'pass' : 'fail') + '</span>' + esc(r.name) + (r.passed ? '' : ' <span class="desc" style="margin:0">' + esc(r.detail) + '</span>') + '</summary>' +
            table([{t: 'Sent', k: 'in'}, {t: 'Reply', k: 'out'}, {t: 'State', k: 'state'}, {t: 'Intent', k: 'intent'}], r.transcript) + '</details>';
        }).join('');
      });
    };
  };
  CT.tpl = function (box) {
    box.innerHTML = '<p class="desc">Renders every forecast, price, weather and onboarding template for all crops, horizons, locations and languages with worst-case numbers, with and without the [SAMPLE] prefix.</p><div id="tplOut"></div>';
    panel('#tplOut', function () { return api('GET', '/api/admin/test/template-check'); }, function (d, out) {
      out.innerHTML = '<div class="grid g3">' + mini('Templates rendered', fmt(d.total)) + mini('Over 2 segments or truncated', d.over) + mini('Maximum segments', d.max_segments) + '</div>' +
        (d.failures.length ? table([{t: 'Lang', k: 'lang'}, {t: 'Kind', k: 'kind'}, {t: 'Crop', k: 'crop'}, {t: 'Horizon', k: 'horizon'}, {t: 'Segments', k: 'segments', r: 1}, {t: 'Text', k: 'text'}], d.failures)
          : '<p style="margin-top:12px"><span class="chip ok">All within budget</span></p>');
    });
  };

  /* ---------- weather outlook ---------- */
  PAGES.weather = function (root, loc) {
    root.innerHTML = '<div class="panel"><div class="form-row"><label>Location <select id="wLoc"></select></label><span id="wMethod"></span></div><div class="grid g2">' +
      '<div><p class="desc">Next 7 days: rain (bars) and temperature (lines)</p><div class="chart-box" id="w7"></div></div>' +
      '<div><p class="desc">Last 60 days: observed rain against climatology</p><div class="chart-box" id="wRecent"></div></div></div></div>' +
      '<div class="grid g2"><div class="panel"><h3>Weeks 2-4</h3><p class="desc">P10 to P90. Climatology unless a model beat it in backtests.</p><div id="wWeeks"></div></div>' +
      '<div class="panel"><h3>Months 1-3 (climatology)</h3><p class="desc" id="wAnom"></p><div id="wMonths"></div></div></div>';
    panel('#wWeeks', function () { return api('GET', '/api/admin/weather?location=' + (loc || '')); }, function (d) {
      var sel = $('#wLoc');
      sel.innerHTML = options(d.locations.map(function (l) { return [l.key, l.name + (l.has_coords ? '' : ' (history only)')]; }), d.location);
      sel.onchange = function () { clearCharts(); PAGES.weather(root, sel.value); };
      var n = d.next7, p = palette();
      $('#wMethod').innerHTML = '<span class="chip ' + (n.method === 'climatology' ? 'warn' : 'ok') + '">7-day source: ' + esc(n.method === 'climatology' ? 'climatology (live forecast unavailable)' : n.method) + '</span>';
      chart('#w7', {data: {labels: n.days.map(function (x) { return x.date; }), datasets: [
        {type: 'bar', label: 'Rain (mm)', data: n.days.map(function (x) { return x.rain; }), backgroundColor: p.info, yAxisID: 'y'},
        {type: 'line', label: 'Tmax (C)', data: n.days.map(function (x) { return x.tmax; }), borderColor: p.bad, yAxisID: 'y1'},
        {type: 'line', label: 'Tmin (C)', data: n.days.map(function (x) { return x.tmin; }), borderColor: p.brand5, yAxisID: 'y1'}]},
        options: {scales: {y: {beginAtZero: true, position: 'left'}, y1: {position: 'right', grid: {drawOnChartArea: false}}}}});
      chart('#wRecent', {data: {labels: d.recent.map(function (x) { return x.date; }), datasets: [
        {type: 'bar', label: 'Observed rain', data: d.recent.map(function (x) { return x.rain; }), backgroundColor: p.info},
        {type: 'line', label: 'Climatology mean', data: d.recent.map(function (x) { return x.rain_clim; }), borderColor: p.ink3, pointRadius: 0}]}, options: {scales: {x: {ticks: {maxTicksLimit: 8}}}}});
      $('#wWeeks').innerHTML = table([{t: 'Week', k: 'week', r: 1}, {t: 'Starts', k: 'start'}, {t: 'Rain P10-P90 (mm)', f: function (r) { return fmt(r.rain_total.p10) + ' to ' + fmt(r.rain_total.p90); }},
        {t: 'Rain P50', r: 1, f: function (r) { return fmt(r.rain_total.p50); }}, {t: 'Tmax P50', r: 1, f: function (r) { return fmt(r.tmax_mean.p50, 1); }},
        {t: 'Method', f: function (r) { return '<span class="chip">' + esc(r.rain_total.method) + '</span>'; }}], d.weeks.weeks || []);
      var m = d.months;
      $('#wAnom').textContent = m.recent30_mm != null ? 'Last 30 days of data (to ' + m.data_end + '): ' + fmt(m.recent30_mm) + ' mm against a normal of ' + fmt(m.normal30_mm) + ' mm.' : '';
      $('#wMonths').innerHTML = table([{t: 'Month', k: 'month', r: 1}, {t: 'Starts', k: 'start'}, {t: 'Rain P10-P90 (mm)', f: function (r) { return fmt(r.p10) + ' to ' + fmt(r.p90); }},
        {t: 'Below / near / above normal', f: function (r) { return r.probs ? pct(r.probs.below, 0) + ' / ' + pct(r.probs.near, 0) + ' / ' + pct(r.probs.above, 0) : 'n/a'; }}, {t: 'Years', r: 1, k: 'n_years'}], m.months || []);
    });
  };

  /* ---------- farmers ---------- */
  PAGES.farmers = function (root) {
    root.innerHTML = '<div class="panel"><div class="form-row"><label>Location <select id="faLoc"><option value="">All</option></select></label>' +
      '<label>Onboarding <select id="faState"><option value="">All</option><option>DONE</option><option>ASK_LOCATION</option><option>WELCOME</option><option>NEW</option></select></label>' +
      '<span class="spacer"></span><a class="btn" href="/api/admin/farmers.csv">Export CSV (masked)</a></div><div id="faTable"></div></div>';
    api('GET', '/api/admin/data').then(function (d) { $('#faLoc').innerHTML += d.locations.map(function (l) { return '<option value="' + l.key + '">' + esc(l.name_en) + '</option>'; }).join(''); }).catch(function () {});
    function load() {
      panel('#faTable', function () { return api('GET', '/api/admin/farmers?location=' + $('#faLoc').value + '&state=' + $('#faState').value); }, function (d, box) {
        box.innerHTML = '<p class="desc">' + fmt(d.total) + ' farmers. Phone numbers are masked everywhere in the dashboard.</p>' + table([{t: 'Phone', k: 'phone'}, {t: 'Location', k: 'location'}, {t: 'Language', k: 'lang'},
          {t: 'Onboarding', k: 'onboarding_state'}, {t: 'Subscribed', f: function (r) { return r.subscribed ? 'yes' : '<span class="chip warn">opted out</span>'; }},
          {t: 'Last seen', f: function (r) { return esc((r.last_seen || '').replace('T', ' ').slice(0, 16)); }}, {t: 'Demo', f: function (r) { return r.demo ? 'demo' : ''; }}], d.items, {empty: 'No farmers yet. Try the chat simulator.'});
      });
    }
    $('#faLoc').onchange = load; $('#faState').onchange = load; load();
  };

  /* ---------- alerts & broadcast ---------- */
  PAGES.alerts = function (root) {
    root.innerHTML = '<div class="grid g2"><div class="panel"><h3>Compose a broadcast</h3><p class="desc">Goes only to subscribed, onboarded farmers who consented. Never during quiet hours (21:00-06:00 Kathmandu).</p>' +
      '<textarea class="in" id="bText" maxlength="480" placeholder="Agahi: ..."></textarea><div class="desc" id="bCount"></div>' +
      '<div class="form-row"><label>Crop <select id="bCrop"><option value="">Any</option></select></label><label>Location <select id="bLoc"><option value="">Any</option></select></label>' +
      '<label>Language <select id="bLang"><option value="">Any</option><option value="en">English</option><option value="rn">Roman Nepali</option><option value="ne">Nepali</option></select></label></div>' +
      '<div class="form-row"><button class="btn" id="bPrev">Preview audience</button><button class="btn btn-primary" id="bSend">Send broadcast</button><label><input type="checkbox" id="bOverride"> Override quiet hours (testing only)</label></div><div id="bOut"></div></div>' +
      '<div class="panel"><h3>Daily alerts</h3><p class="desc">One per farmer per day at most: price moved 10% or more, 20 mm or more rain tomorrow at their saved location (live forecast only), or a reliable 7-day forecast moving 10% or more.</p>' +
      '<div class="form-row"><button class="btn btn-primary" id="aRun">Run alerts now</button><label><input type="checkbox" id="aOverride"> Override quiet hours (testing only)</label></div><div id="aOut"></div>' +
      '<h3 style="margin-top:16px">Broadcast history</h3><div id="bHist"></div></div></div>';
    api('GET', '/api/admin/data').then(function (d) { $('#bLoc').innerHTML += d.locations.map(function (l) { return '<option value="' + l.key + '">' + esc(l.name_en) + '</option>'; }).join(''); }).catch(function () {});
    api('GET', '/api/admin/market').then(function (m) { $('#bCrop').innerHTML += m.crops.map(function (c) { return '<option value="' + c.key + '">' + esc(c.name) + '</option>'; }).join(''); }).catch(function () {});
    function body() { return {text: $('#bText').value.trim(), crop: $('#bCrop').value || null, location: $('#bLoc').value || null, lang: $('#bLang').value || null, override_quiet: $('#bOverride').checked}; }
    $('#bText').oninput = function () { var v = $('#bText').value; $('#bCount').textContent = v.length + ' chars'; };
    $('#bPrev').onclick = function () {
      if (!body().text) return;
      api('POST', '/api/admin/broadcast/preview', body()).then(function (r) {
        $('#bOut').innerHTML = '<div class="grid g4" style="margin-top:8px">' + mini('Recipients', r.recipients) + mini('Segments', r.segments + (r.over_budget ? ' (over 2)' : '')) + mini('Encoding', r.encoding === 'UCS2' ? 'UCS-2' : 'GSM-7') + mini('Est. cost', 'Rs ' + fmt(r.cost_npr, 1)) + '</div>' +
          (r.quiet_hours ? '<div class="banner warn" style="margin:10px 0 0">It is quiet hours in Kathmandu now. Sending is blocked unless overridden.</div>' : '');
      }).catch(function (e) { $('#bOut').innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
    };
    $('#bSend').onclick = function () {
      if (!body().text || !confirm('Send this broadcast now?')) return;
      api('POST', '/api/admin/broadcast/send', body()).then(function (r) { $('#bOut').innerHTML = '<p><span class="chip ok">Queued ' + r.queued + '</span> Delivery is simulated by the mock provider.</p>'; hist(); })
        .catch(function (e) { $('#bOut').innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
    };
    $('#aRun').onclick = function () {
      api('POST', '/api/admin/alerts/run', {override_quiet: $('#aOverride').checked}).then(function (r) {
        $('#aOut').innerHTML = r.skipped_quiet_hours ? '<div class="banner warn" style="margin:0">Skipped: quiet hours.</div>' : '<p>Checked ' + r.checked + ' farmers, queued ' + r.queued + ' alerts.</p>';
      }).catch(function (e) { $('#aOut').innerHTML = '<div class="err">' + esc(e.message) + '</div>'; });
    };
    function hist() { panel('#bHist', function () { return api('GET', '/api/admin/broadcasts'); }, function (d, box) {
      box.innerHTML = table([{t: 'When', f: function (r) { return esc(r.ts.replace('T', ' ').slice(0, 16)); }}, {t: 'Text', k: 'text'}, {t: 'Recipients', r: 1, k: 'recipients'}], d.items, {empty: 'No broadcasts yet.'}); }); }
    hist();
  };

  /* ---------- SMS operations ---------- */
  PAGES.sms = function (root) {
    root.innerHTML = '<div id="smsTop"></div><div class="grid g2"><div class="panel"><h3>Outbox funnel</h3><div class="chart-box short" id="smsFunnel"></div></div><div class="panel"><h3>Webhook log</h3><div id="smsHooks"></div></div>' +
      '<div class="panel span2"><h3>Outbox</h3><p class="desc">Alerts, broadcasts, operator replies and (in phase 2) SMS replies. Retries back off exponentially, then fail after 3 attempts.</p><div id="smsOut"></div></div></div>';
    panel('#smsTop', function () { return api('GET', '/api/admin/sms'); }, function (d, box) {
      box.innerHTML = '<div class="kpis">' + kpi('Provider', d.provider, d.simulated ? 'SIMULATED (mock provider)' : 'live provider') + kpi('Opt-outs', fmt(d.optouts), 'sent STOP') +
        kpi('Quiet hours now', d.quiet_hours ? 'yes' : 'no', '21:00-06:00 Kathmandu') + kpi('Cost per segment', 'Rs ' + d.cost_per_segment, 'estimate for dashboards') + '</div>';
      var order = ['queued', 'sending', 'sent', 'delivered', 'failed', 'expired'], p = palette();
      bar('#smsFunnel', order.map(function (s) { return [s, d.funnel[s] || 0]; }), p.brand);
      $('#smsHooks').innerHTML = table([{t: 'When', f: function (r) { return esc(r.ts.replace('T', ' ').slice(5, 16)); }}, {t: 'Kind', k: 'kind'}, {t: 'OK', f: function (r) { return r.ok ? 'yes' : '<span class="chip bad">no</span>'; }}, {t: 'Note', k: 'note'}], d.webhooks, {empty: 'No webhooks yet. They arrive once a real SMS provider is connected (phase 2).'});
      $('#smsOut').innerHTML = table([{t: 'Id', k: 'id', r: 1}, {t: 'When', f: function (r) { return esc(r.created_at.replace('T', ' ').slice(5, 16)); }}, {t: 'Phone', k: 'phone'}, {t: 'Kind', k: 'kind'},
        {t: 'Status', f: function (r) { return '<span class="chip ' + (r.status === 'delivered' ? 'ok' : r.status === 'failed' || r.status === 'expired' ? 'bad' : 'warn') + '">' + esc(r.status) + '</span>'; }},
        {t: 'Tries', r: 1, k: 'attempts'}, {t: 'Seg', r: 1, k: 'segments'}, {t: 'Text', k: 'text'}, {t: 'Error', k: 'error'}], d.outbox, {empty: 'Outbox is empty.'});
      if (d.simulated) $('#pillEnv').textContent = 'Phase 1: Web simulator, SMS SIMULATED';
    });
  };

  /* ---------- quality ---------- */
  PAGES.quality = function (root) {
    root.innerHTML = '<div class="grid g2"><div class="panel"><h3>Not understood</h3><p class="desc">Free-text messages the bot could not act on. Save a crop word as an alias and it is understood from the next message.</p><div id="qUnk"></div></div>' +
      '<div class="panel"><h3>Template viewer</h3><p class="desc">Live renders with segment counts.</p><div id="qTpl"></div></div></div>';
    panel('#qUnk', function () { return api('GET', '/api/admin/quality'); }, function (d, box) {
      var cropOpts = d.crops.map(function (c) { return '<option value="' + c.key + '">' + esc(c.name) + '</option>'; }).join('');
      box.innerHTML = d.unknown.length ? d.unknown.map(function (u) {
        return '<div class="check"><b style="width:auto;flex:1">' + esc(u.text) + '</b><span class="chip">' + esc(u.lang) + '</span>' + (u.demo ? '<span class="chip">demo</span>' : '') +
          '<select data-alias="' + esc(u.text) + '">' + cropOpts + '</select><button class="btn" data-save="' + esc(u.text) + '">Save alias</button></div>'; }).join('') : '<div class="empty-state">Nothing in the queue.</div>';
      $$('[data-save]', box).forEach(function (b) { b.onclick = function () {
        var sel = b.previousElementSibling;
        api('POST', '/api/admin/quality/alias', {alias: b.dataset.save.slice(0, 40), crop: sel.value}).then(function () { b.textContent = 'Saved'; b.disabled = true; }).catch(function (e) { alert(e.message); });
      }; });
      $('#qTpl').innerHTML = d.templates.map(function (t) { return '<div class="sms-box"><div class="kpi-label">' + esc(t.name) + ', ' + esc(t.lang) + '</div><div class="t">' + esc(t.text) + '</div><div class="m">' +
        t.segments + ' segment' + (t.segments > 1 ? 's' : '') + ' · ' + (t.encoding === 'UCS2' ? 'UCS-2' : 'GSM-7') + ' · ' + t.chars + ' chars</div></div>'; }).join('');
    });
  };

  /* ---------- boot ---------- */
  function showLogin() { $('#login').hidden = false; $('#app').hidden = true; }
  function boot() {
    api('GET', '/api/admin/me').then(function (r) {
      CSRF = r.csrf; $('#login').hidden = true; $('#app').hidden = false;
      buildNav(); loadStatus();
      $('#nav').onclick = function (e) { var b = e.target.closest('[data-page]'); if (b) go(b.dataset.page); };
      go((location.hash || '#overview').slice(1));
    }).catch(function () { showLogin(); });
  }
  $('#loginForm').onsubmit = function (e) {
    e.preventDefault();
    fetch('/api/admin/login', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password: $('#pw').value}), credentials: 'same-origin'})
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error.message); return j; }); })
      .then(function () { $('#loginErr').textContent = ''; boot(); }).catch(function (err) { $('#loginErr').textContent = err.message; });
  };
  $('#range').onchange = function () { go('overview'); };
  $('#sideToggle').onclick = function () { $('#app').classList.toggle('side-open'); };
  $('#logoutBtn').onclick = function () { api('POST', '/api/admin/logout', {}).then(showLogin).catch(showLogin); };
  $('#themeBtn').onclick = function () {
    var t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = t; try { localStorage.setItem('agahi-theme', t); } catch (e) { /* private mode */ }
    $('#themeBtn').textContent = t === 'dark' ? 'Light' : 'Dark'; go(currentPage);
  };
  window.addEventListener('hashchange', function () { var p = location.hash.slice(1); if (p !== currentPage && PAGES[p]) go(p); });
  boot();
})();
