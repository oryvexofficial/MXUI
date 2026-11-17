var $ = function (id) { return document.getElementById(id); };
var set = function (i, v) { var e = $(i); if (e) e.textContent = v; };
var esc = function (s) {
  return String(s || '').replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
};
var ic = function (n) { return '<svg class="i"><use href="#' + n + '"/></svg>'; };
var J = function (u, b, m) {
  return fetch(u, { method: m || 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
};
var jerr = async function (r, d) { try { var j = await r.json(); return j.detail || d; } catch (e) { return d; } };
var fmtBytes = function (b) {
  b = b || 0;
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
  if (b < 1073741824) return (b / 1048576).toFixed(2) + ' MB';
  return (b / 1073741824).toFixed(2) + ' GB';
};
var fmtMB = function (m) { return m >= 1024 ? (m / 1024).toFixed(2) + ' GB' : m.toFixed(1) + ' MB'; };
var fmtGB = function (g) { return g >= 1024 ? (g / 1024).toFixed(2) + ' TB' : g.toFixed(1) + ' GB'; };

function toggleTheme() {
  var d = document.documentElement;
  d.dataset.theme = d.dataset.theme === 'dark' ? 'light' : 'dark';
  try { localStorage.setItem('mx-theme', d.dataset.theme); } catch (e) {}
}

var stack = [];
var confirmRes = null;
var onOpen = {
  databaseModal: function () { loadDatabaseInfo(); },
  healthModal: function () { loadHealthConfigs(); },
  settingsModal: function () { loadSettingsModal(); },
  ipSuggestModal: function () { initIPModal(); },
  connectionsModal: function () { loadConnectionsAndActivity(); }
};

function toggleModal(id, show) {
  var m = $(id);
  if (!m) return;
  if (show) {
    if (stack.indexOf(id) >= 0) return;
    m._from = document.activeElement;
    stack.push(id);
    m.classList.add('open');
    document.body.classList.add('lock');
    setTimeout(function () {
      var sh = m.querySelector('.sheet');
      if (sh) sh.focus();
    }, 30);
    if (onOpen[id]) onOpen[id]();
  } else {
    var i = stack.indexOf(id);
    if (i < 0) return;
    stack.splice(i, 1);
    m.classList.remove('open');
    if (!stack.length) document.body.classList.remove('lock');
    if (id === 'confirmModal') answer(false);
    if (m._from && m._from.focus) m._from.focus();
  }
}

document.querySelectorAll('.modal').forEach(function (m) {
  m.addEventListener('pointerdown', function (e) { if (e.target === m) toggleModal(m.id, false); });
});

document.addEventListener('keydown', function (e) {
  var id = stack[stack.length - 1];
  if (id && e.key === 'Escape') toggleModal(id, false);
});

function answer(v) { if (confirmRes) { var r = confirmRes; confirmRes = null; r(v); } }
function customConfirm(msg, ok, danger, title) {
  set('confirmMessage', msg);
  set('confirmTitle', title || 'Confirm action');
  var b = $('confirmOk');
  b.textContent = ok || 'Confirm';
  b.className = 'btn ' + (danger ? 'danger' : 'primary');
  $('confirmBadge').className = 'bdg' + (danger ? '' : ' info');
  return new Promise(function (resolve) {
    answer(false);
    confirmRes = resolve;
    toggleModal('confirmModal', true);
  });
}
function _confirmYes() { answer(true); toggleModal('confirmModal', false); }
function _confirmNo() { answer(false); toggleModal('confirmModal', false); }
function triggerAlert(title, msg, icon) {
  set('alertTitle', title);
  set('alertMessage', msg);
  var ai = $('alertIcon');
  if (ai) ai.innerHTML = '<use href="#' + (icon || 'info') + '"/>';
  toggleModal('customAlert', true);
}

async function getCurrentPaths() {
  try {
    var r = await fetch('/api/current-paths');
    if (!r.ok) throw 0;
    return await r.json();
  } catch (e) {
    return { dashboard: '/dashboard', login: '/login', sub: '/sub', setup: '/setup' };
  }
}

async function goLogin() {
  var p = await getCurrentPaths();
  try { await fetch('/api/logout', { method: 'POST' }); } catch (e) {}
  location.href = p.login || '/login';
}

var sysOpen = false;
function toggleSystemDetails() {
  sysOpen = !sysOpen;
  var wrap = $('systemDetailsWrapper');
  if (wrap) wrap.classList.toggle('open', sysOpen);
  var btn = $('toggleSystemBtn');
  if (btn) btn.setAttribute('aria-expanded', String(sysOpen));
  set('toggleSystemText', sysOpen ? 'Show less' : 'Show more');
}

function ring(k, pct, val) {
  pct = Math.min(100, Math.max(0, pct || 0));
  var r = $('ring-' + k);
  if (r) r.setAttribute('stroke-dasharray', pct + ' 100');
  set('ring-' + k + '-pct', pct.toFixed(1) + '%');
  set('ring-' + k + '-val', val);
}

async function updateStats() {
  try {
    var res = await fetch('/stats');
    if (!res.ok) return;
    var d = await res.json();
    var n = function (x) { return Number(x) || 0; };
    var tr = n(d.total_traffic_mb), cpu = n(d.cpu_percent), rT = n(d.ram_total_mb), rU = n(d.ram_used_mb);
    var sT = n(d.swap_total_mb), sU = n(d.swap_used_mb), dT = n(d.disk_total_gb), dU = n(d.disk_used_gb);

    set('uptime-display', d.uptime || '00:00:00');
    set('total-traffic', fmtMB(tr));
    set('total-usage', (tr / 1024).toFixed(2) + ' GB');
    set('total-inbounds', d.links_count || 0);
    set('active-connections', d.active_connections || 0);
    set('xray-status-pill', d.xray_running ? 'Xray Active' : 'Panel Mode');

    ring('cpu', cpu, n(d.cpu_cores) + ' cores');
    ring('ram', n(d.ram_percent), (rU / 1024).toFixed(2) + ' / ' + (rT / 1024).toFixed(2) + ' GB');
    ring('swap', n(d.swap_percent), (sU / 1024).toFixed(2) + ' / ' + (sT / 1024).toFixed(2) + ' GB');
    ring('disk', n(d.disk_percent), fmtGB(dU) + ' / ' + fmtGB(dT));

    var g = function (m) { return (m / 1024).toFixed(2) + ' GB'; };
    var S = {
      'cpu-load-avg': (d.cpu_load_1m !== undefined ? d.cpu_load_1m : cpu.toFixed(1) + '%'),
      'cpu-cores-detail': d.cpu_cores ? d.cpu_cores + ' cores' : '--',
      'cpu-user': n(d.cpu_user).toFixed(1) + '%',
      'cpu-system': n(d.cpu_system).toFixed(1) + '%',
      'cpu-idle': n(d.cpu_idle).toFixed(1) + '%',
      'ram-total-detail': g(rT),
      'ram-used-detail': g(rU),
      'ram-free-detail': g(Math.max(0, rT - rU)),
      'ram-available-detail': g(n(d.ram_available_mb)),
      'ram-cached-detail': g(n(d.ram_cached_mb)),
      'swap-total-detail': g(sT),
      'swap-used-detail': g(sU),
      'swap-free-detail': g(Math.max(0, sT - sU)),
      'swap-usage-detail': n(d.swap_percent).toFixed(1) + '%',
      'disk-total-detail': fmtGB(dT),
      'disk-used-detail': fmtGB(dU),
      'disk-free-detail': fmtGB(Math.max(0, dT - dU)),
      'disk-usage-detail': n(d.disk_percent).toFixed(1) + '%',
      'network-total': fmtMB(tr),
      'network-requests': d.total_requests || 0,
      'network-connections': d.active_connections || 0,
      'network-errors': d.total_errors || 0,
      'sys-uptime': d.uptime || '00:00:00',
      'sys-active-configs': d.active_links || 0,
      'sys-total-configs': d.links_count || 0,
      'sys-expired-configs': d.expired_links || 0
    };
    for (var k in S) { set(k, S[k]); }
  } catch (e) {}
}

var links = [];
async function getLinks() {
  var r = await fetch('/api/links');
  if (r.status === 401 || r.status === 403) {
    var p = await getCurrentPaths();
    location.href = p.login || '/login';
    throw new Error('auth');
  }
  if (!r.ok) throw new Error('Failed to load configs');
  var d = await r.json();
  links = d.links || [];
  return links;
}

function protoBadge(proto) {
  if (proto === 'all') return 'ALL MODES · XHTTP + WS';
  var p = (proto || 'vless-ws').toUpperCase();
  return p.replace('-PACKET-UP', ' · XHTTP-P').replace('-STREAM-UP', ' · XHTTP-S').replace('-WS', ' · WS');
}

function row(l) {
  var act = Boolean(l.active && !l.expired);
  var def = Boolean(l.is_default);
  var proto = l.protocol || 'vless-ws';
  var lim = Boolean(!l.limit_bytes);
  var used = l.used_bytes || 0;
  var pct = lim ? 0 : Math.min(100, (used / l.limit_bytes) * 100);
  var sp = l.speed_limit_bytes > 0 ? ((l.speed_limit_bytes * 8) / 1048576).toFixed(1) + ' Mbps' : 'Unlimited';
  var exp = l.expires_at ? new Date(l.expires_at).toISOString().slice(0, 10) : 'Unlimited';
  var ap = l.applied_ips_count || 0;
  var net = proto === 'all' ? 'xhttp + ws' : (proto.indexOf('xhttp') >= 0 ? 'xhttp' : 'ws');

  var out = '<div class="row' + (def ? ' def' : '') + '" data-uuid="' + esc(l.uuid) + '">';
  out += '<div><div class="name"><span class="tag acc">' + esc(protoBadge(proto)) + '</span><b>' + esc(l.label || 'Unnamed') + '</b>';
  out += '<span class="pill ' + (act ? 'ok' : 'off') + '"><i></i>' + (act ? 'Active' : 'Inactive') + '</span>';
  if (l.region && l.region !== 'Auto') out += '<span class="tag">' + esc(l.region) + '</span>';
  if (def) out += '<span class="tag warn">Default</span>';
  if (ap) out += '<span class="tag">' + ap + ' edge IP' + (ap > 1 ? 's' : '') + '</span>';
  out += '</div>';
  out += '<div class="meta"><span>Transport <b>' + net + '</b></span><span>Expiry <b>' + exp + '</b></span><span>Usage <b>' + fmtBytes(used) + ' / ' + (lim ? 'Unlimited' : fmtBytes(l.limit_bytes)) + '</b></span><span>IP limit <b>' + (l.ip_limit || 'Unlimited') + '</b></span><span>Speed <b>' + sp + '</b></span>';
  if (l.cdn_host) out += '<span>CDN <b>' + esc(l.cdn_host) + '</b></span>';
  if (l.note) out += '<span>Note <b>' + esc(l.note) + '</b></span>';
  out += '</div>';
  out += '<div class="bar ' + (pct > 90 ? 'full' : pct > 70 ? 'warn' : '') + '"><i style="width:' + pct + '%"></i></div></div>';
  out += '<div class="ctl">';
  out += '<label class="sw"><input type="checkbox" data-t ' + (act ? 'checked' : '') + ' ' + (def ? 'disabled' : '') + '><i></i><em>' + (act ? 'Enabled' : 'Disabled') + '</em></label>';
  out += '<div class="lk"><input class="input" readonly value="' + esc(l.vless_link) + '" aria-label="Config link"><button class="ib sm" data-a="copy" title="Copy link">' + ic('copy') + '</button></div>';
  out += '<button class="ib sm" data-a="qr" title="QR codes">' + ic('qr') + '</button>';
  out += '<button class="ib sm" data-a="portal" title="Subscription page">' + ic('open') + '</button>';
  if (def) {
    out += '<span class="tag warn">Protected</span>';
  } else {
    out += '<button class="ib sm" data-a="edit" title="Edit">' + ic('edit') + '</button><button class="ib sm" data-a="reset" title="Reset traffic">' + ic('reset') + '</button><button class="ib sm danger" data-a="del" title="Delete">' + ic('trash') + '</button>';
  }
  out += '</div></div>';
  return out;
}

function renderLinks() {
  var q = ($('search') ? $('search').value : '').trim().toLowerCase();
  var items = links.filter(function (l) {
    return !q || String(l.label || '').toLowerCase().indexOf(q) >= 0 || String(l.protocol || '').toLowerCase().indexOf(q) >= 0;
  });
  var c = $('config-list');
  if (!c) return;
  if (items.length) {
    c.innerHTML = items.map(row).join('');
  } else {
    c.innerHTML = '<div class="empty"><b>' + (links.length ? 'No matches' : 'No configs yet') + '</b>' + (links.length ? 'Try a different keyword.' : 'Select "Add config" to create your first one.') + '</div>';
  }
}

async function loadConfigs() {
  try {
    await getLinks();
    renderLinks();
    updateStats();
  } catch (e) {}
}

var sInp = $('search');
if (sInp) sInp.oninput = renderLinks;

var cl = $('config-list');
if (cl) {
  cl.addEventListener('click', function (e) {
    var b = e.target.closest('[data-a]');
    if (!b) return;
    var r = b.closest('.row');
    if (!r) return;
    var l = links.find(function (x) { return x.uuid === r.dataset.uuid; });
    if (!l) return;
    var act = b.dataset.a;
    if (act === 'copy') copyText(l.vless_link);
    else if (act === 'qr') openQrModal(l);
    else if (act === 'portal') window.open(l.portal_url || ('/sub/user?uuid=' + encodeURIComponent(l.uuid)), '_blank');
    else if (act === 'edit') openEdit(l);
    else if (act === 'reset') resetTraffic(l.uuid);
    else if (act === 'del') deleteConfig(l.uuid);
  });
  cl.addEventListener('change', function (e) {
    if (e.target.matches('[data-t]')) {
      var r = e.target.closest('.row');
      if (r) toggleConfigStatus(r.dataset.uuid, e.target.checked, e.target);
    }
  });
}

async function toggleConfigStatus(uuid, on, cb) {
  try {
    var r = await J('/api/links/' + uuid + '/toggle', { active: on }, 'PATCH');
    if (!r.ok) throw 0;
    toast('Config ' + (on ? 'enabled' : 'disabled'), 'ok');
    loadConfigs();
  } catch (e) {
    toast('Could not change status', 'err');
    cb.checked = !on;
  }
}

var cfgBody = function (p) {
  var g = function (k) { var el = $(p + '-' + k); return el ? el.value : ''; };
  return {
    label: g('label').trim() || 'New Config',
    protocol: g('protocol') || 'vless-ws',
    fingerprint: g('fp') || 'chrome',
    alpn: g('alpn').trim(),
    sni: g('sni').trim(),
    cdn_host: g('cdn').trim(),
    region: g('region').trim() || 'Auto',
    limit_value: parseFloat(g('limit')) || 0,
    limit_unit: 'MB',
    expires_days: parseInt(g('expiry'), 10) || 0,
    ip_limit: parseInt(g('iplimit'), 10) || 0,
    speed_limit_value: parseFloat(g('speed')) || 0,
    speed_limit_unit: g('speed-unit') || 'MBIT',
    note: g('note').trim()
  };
};

async function createConfig() {
  try {
    var r = await J('/api/links', cfgBody('new'));
    if (!r.ok) throw new Error(await jerr(r, 'Could not create config'));
    toggleModal('inboundModal', false);
    toast('Config created', 'ok');
    ['label', 'alpn', 'sni', 'cdn', 'note'].forEach(function (k) { var el = $('new-' + k); if (el) el.value = ''; });
    ['limit', 'expiry', 'iplimit', 'speed'].forEach(function (k) { var el = $('new-' + k); if (el) el.value = '0'; });
    loadConfigs();
  } catch (e) {
    toast(e.message, 'err');
  }
}

function openEdit(l) {
  var v = function (k, val) { var el = $('edit-' + k); if (el) el.value = val; };
  $('edit-uuid').value = l.uuid;
  set('editNodeTitle', l.label);
  v('label', l.label || '');
  v('protocol', l.protocol || 'vless-ws');
  v('fp', l.fingerprint || 'chrome');
  v('alpn', l.alpn || '');
  v('sni', l.sni || '');
  v('cdn', l.cdn_host || '');
  v('region', l.region || 'Auto');
  v('limit', l.limit_bytes ? Math.round(l.limit_bytes / 1048576) : 0);
  v('iplimit', l.ip_limit || 0);
  v('speed', l.speed_limit_bytes ? ((l.speed_limit_bytes * 8) / 1048576).toFixed(1) : 0);
  v('note', l.note || '');
  toggleModal('editModal', true);
}

async function saveEdit() {
  try {
    var payload = cfgBody('edit');
    if (parseInt($('edit-expiry').value, 10) === 0) payload.clear_expiry = false;
    var r = await J('/api/links/' + $('edit-uuid').value, payload, 'PATCH');
    if (!r.ok) throw new Error(await jerr(r, 'Could not update config'));
    toggleModal('editModal', false);
    toast('Config updated', 'ok');
    loadConfigs();
  } catch (e) {
    toast(e.message, 'err');
  }
}

async function deleteConfig(uuid) {
  var ok = await customConfirm('Delete this configuration? This cannot be undone.', 'Delete', true, 'Delete config');
  if (!ok) return;
  try {
    var r = await fetch('/api/links/' + uuid, { method: 'DELETE' });
    if (!r.ok) throw 0;
    toast('Config deleted', 'ok');
    loadConfigs();
  } catch (e) {
    toast('Could not delete config', 'err');
  }
}

async function resetTraffic(uuid) {
  var ok = await customConfirm('Reset traffic counters for this config?', 'Reset', true, 'Reset traffic');
  if (!ok) return;
  try {
    var r = await fetch('/api/links/' + uuid + '/reset-traffic', { method: 'POST' });
    if (!r.ok) throw 0;
    toast('Traffic reset', 'ok');
    loadConfigs();
  } catch (e) {
    toast('Could not reset traffic', 'err');
  }
}

async function qrInto(id, data) {
  var img = $(id);
  if (!img) return;
  img.removeAttribute('src');
  try {
    var res = await fetch('/api/qr?data=' + encodeURIComponent(data) + '&size=300');
    var d = await res.json();
    if (d.qr) img.src = d.qr;
  } catch (e) {}
}

function openQrModal(l) {
  set('qrTargetLabel', l.label || 'Config');
  set('qrTextPayload', l.vless_link || '');
  set('qrSubPayload', l.sub_url || '');
  qrInto('qrImage', l.vless_link || '');
  qrInto('qrSubImage', l.sub_url || '');
  toggleModal('qrModal', true);
}

var domainSt = { is_paas_default: false, host: '', platform: '' };
var ips = [];
async function initIPModal() {
  await checkDomain();
  fetchSuggestions();
}
async function checkDomain() {
  try {
    var r = await fetch('/api/domain/check');
    domainSt = await r.json();
    renderDomain();
  } catch (e) {
    toast('Could not check domain', 'err');
  }
}
function renderDomain() {
  var paas = Boolean(domainSt.is_paas_default);
  var n = $('domainStatus');
  if (n) {
    n.className = 'note ' + (paas ? 'warn' : 'ok');
    n.innerHTML = ic(paas ? 'alert' : 'ok') + '<div><b>' + esc(domainSt.platform || 'Server') + (paas ? ' default domain detected' : ' domain ready') + '</b><p>' + (paas ? 'For Cloudflare CDN edge IPs, set a Custom Domain or CDN Host in Settings.' : 'Edge IP pool routing is ready.') + '</p><p class="mono">' + esc(domainSt.host + ':' + (domainSt.port || 443)) + '</p></div>';
  }
}
async function fetchSuggestions() {
  try {
    var r = await fetch('/api/ips/suggest');
    var d = await r.json();
    ips = d.ips || [];
    var sl = $('suggestList');
    if (sl) {
      if (ips.length) {
        sl.innerHTML = ips.map(function (ip) {
          return '<label class="chk mono"><input type="checkbox" class="suggest-ip-checkbox" value="' + esc(ip) + '" checked>' + esc(ip) + '</label>';
        }).join('');
      } else {
        sl.innerHTML = '<p class="mut" style="grid-column:1/-1;text-align:center;font-size:13px">No IPs available.</p>';
      }
    }
    await loadApplyTargets();
    set('applyStatus', ips.length ? ips.length + ' IP(s) loaded' : 'No IPs loaded');
  } catch (e) {
    toast('Could not load IP suggestions', 'err');
  }
}
async function loadApplyTargets() {
  try { await getLinks(); } catch (e) { return; }
  var atl = $('applyTargetList');
  if (atl) {
    if (links.length) {
      atl.innerHTML = links.map(function (l) {
        return '<label class="chk"><input type="checkbox" class="suggest-target-checkbox" value="' + esc(l.uuid) + '"><span>' + esc(l.label) + '</span>' + (l.applied_ips_count ? '<span class="tag acc">' + l.applied_ips_count + ' IP' + (l.applied_ips_count > 1 ? 's' : '') + '</span>' : '') + '</label>';
      }).join('');
    } else {
      atl.innerHTML = '<p class="mut" style="font-size:12px;padding:8px">Create a config first.</p>';
    }
  }
  updateApplyBtn();
}
function updateApplyBtn() {
  var tg = document.querySelectorAll('.suggest-target-checkbox:checked').length;
  var b = $('applySuggestBtn');
  if (b) b.disabled = !tg || !ips.length;
}
var atlEl = $('applyTargetList');
if (atlEl) atlEl.addEventListener('change', updateApplyBtn);

async function applySuggestedIPs() {
  var sel = [];
  document.querySelectorAll('.suggest-ip-checkbox:checked').forEach(function (x) { sel.push(x.value); });
  var tg = [];
  document.querySelectorAll('.suggest-target-checkbox:checked').forEach(function (x) { tg.push(x.value); });
  if (!sel.length) return toast('Select at least one IP', 'err');
  if (!tg.length) return toast('Select at least one config', 'err');
  var ok = await customConfirm('Apply ' + sel.length + ' IP(s) to ' + tg.length + ' config(s)?', 'Apply', false, 'Apply IPs');
  if (!ok) return;
  var b = $('applySuggestBtn');
  b.disabled = true;
  b.textContent = 'Applying...';
  try {
    var r = await J('/api/ips/apply', { ips: sel, target_uuids: tg });
    if (!r.ok) throw new Error(await jerr(r, 'Apply failed'));
    toast('IPs applied successfully', 'ok');
    loadConfigs();
    set('applyStatus', 'Applied to ' + tg.length + ' config(s)');
  } catch (e) {
    toast(e.message, 'err');
  } finally {
    b.innerHTML = ic('check') + 'Apply to selected';
    updateApplyBtn();
  }
}

async function loadHealthConfigs() {
  set('healthStatus', 'Select configs to test');
  $('healthResults').innerHTML = '';
  try { await getLinks(); } catch (e) { toast('Could not load configs', 'err'); return; }
  var hl = $('healthConfigList');
  if (hl) {
    if (links.length) {
      hl.innerHTML = links.map(function (l) {
        return '<label class="chk"><input type="checkbox" class="health-config-checkbox" value="' + esc(l.uuid) + '" checked><span>' + esc(l.label) + '</span><span class="tag ' + (l.active ? 'acc' : '') + '">' + (l.active ? 'Active' : 'Inactive') + '</span></label>';
      }).join('');
    } else {
      hl.innerHTML = '<p class="mut" style="font-size:13px;padding:8px;text-align:center">No configurations found.</p>';
    }
  }
  updateHealthBtn();
}
function updateHealthBtn() {
  var c = document.querySelectorAll('.health-config-checkbox:checked').length;
  var b = $('healthTestBtn');
  if (b) b.disabled = !c;
  set('healthStatus', c ? c + ' config(s) selected' : 'Select at least one config');
}
var hclEl = $('healthConfigList');
if (hclEl) hclEl.addEventListener('change', updateHealthBtn);

async function testSelectedConfigs() {
  var uuids = [];
  document.querySelectorAll('.health-config-checkbox:checked').forEach(function (x) { uuids.push(x.value); });
  if (!uuids.length) return;
  var b = $('healthTestBtn');
  b.disabled = true;
  b.textContent = 'Testing...';
  set('healthStatus', 'Probing endpoints...');
  try {
    var r = await J('/api/configs/test', { uuids: uuids });
    if (!r.ok) throw new Error(await jerr(r, 'Test failed'));
    var d = await r.json();
    var res = d.results || {};
    var ks = Object.keys(res);
    var hr = $('healthResults');
    if (hr) {
      if (ks.length) {
        var rows = ks.map(function (k) {
          var x = res[k];
          var c = links.find(function (l) { return l.uuid === k; });
          return '<tr><td>' + esc(c ? c.label : k.slice(0, 8)) + '</td><td class="mono">' + esc(x.endpoint || '-') + '</td><td class="' + (x.healthy ? 'good' : 'bad') + '">' + (x.healthy ? 'Healthy' : esc(x.error || 'Unreachable')) + '</td><td class="mono">' + (x.latency ? x.latency.toFixed(1) + ' ms' : '-') + '</td></tr>';
        }).join('');
        hr.innerHTML = '<div class="tw c2" style="padding:6px"><table class="tbl"><thead><tr><th>Config</th><th>Endpoint</th><th>Status</th><th>Latency</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
      } else {
        hr.innerHTML = '<p class="mut">No results.</p>';
      }
    }
    set('healthStatus', 'Test completed');
  } catch (e) {
    toast(e.message, 'err');
    set('healthStatus', 'Test failed');
  } finally {
    b.innerHTML = ic('play') + 'Test selected';
    updateHealthBtn();
  }
}

async function loadConnectionsAndActivity() {
  try {
    var [rc, ra] = await Promise.all([fetch('/api/connections'), fetch('/api/activity')]);
    var dc = await rc.json();
    var da = await ra.json();
    var cb = $('connectionsBody');
    if (cb) {
      var conns = dc.connections || [];
      cb.innerHTML = conns.length ? conns.map(function (c) {
        return '<tr><td class="mono">' + esc(c.ip) + '</td><td><span class="tag acc">' + esc(c.transport) + '</span></td><td class="r mono">' + fmtBytes(c.bytes) + '</td><td class="mono">' + esc(String(c.connected_at || '').slice(11, 19)) + '</td></tr>';
      }).join('') : '<tr><td colspan="4" style="text-align:center;color:var(--mut)">No active connections</td></tr>';
    }
    var ab = $('activityBody');
    if (ab) {
      var logs = da.logs || [];
      ab.innerHTML = logs.length ? logs.slice(0, 30).map(function (l) {
        return '<tr><td><span class="tag">' + esc(l.kind) + '</span></td><td>' + esc(l.message) + '</td><td class="mono">' + esc(String(l.time || '').slice(11, 19)) + '</td></tr>';
      }).join('') : '<tr><td colspan="3" style="text-align:center;color:var(--mut)">No activity yet</td></tr>';
    }
  } catch (e) {}
}

async function loadDatabaseInfo() {
  try {
    await getLinks();
    var tr = links.reduce(function (a, l) { return a + (l.used_bytes || 0); }, 0);
    set('db-total-configs', links.length);
    set('db-active-configs', links.filter(function (l) { return l.active; }).length);
    set('db-total-traffic', fmtBytes(tr));
    set('db-last-saved', new Date().toLocaleTimeString());
    var dbBody = $('dbConfigsBody');
    if (dbBody) {
      if (links.length) {
        dbBody.innerHTML = links.map(function (l) {
          return '<tr><td>' + esc(l.label || 'Unnamed') + '</td><td class="mono">' + esc(String(l.uuid).slice(0, 12)) + '...</td><td class="r mono">' + fmtBytes(l.used_bytes) + '</td><td class="r mono">' + (l.limit_bytes ? fmtBytes(l.limit_bytes) : 'Unlimited') + '</td><td><span class="pill ' + (l.active ? 'ok' : 'off') + '"><i></i>' + (l.active ? 'Active' : 'Inactive') + '</span></td><td class="r mono">' + (l.connected_ips || 0) + '</td></tr>';
        }).join('');
      } else {
        dbBody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--mut)">No configurations found</td></tr>';
      }
    }
  } catch (e) {
    toast('Could not load database info', 'err');
  }
}

async function downloadDatabase() {
  try {
    var r = await fetch('/api/database/export');
    if (!r.ok) throw new Error('Export failed');
    var d = await r.json();
    var blob = new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' });
    var a = document.createElement('a');
    var u = URL.createObjectURL(blob);
    a.href = u;
    a.download = 'mx-ui.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(u);
    toast('Database downloaded', 'ok');
  } catch (e) {
    toast(e.message, 'err');
  }
}

var _countriesLoaded = false;
function applyPanelLocationUI(loc) {
  if (!loc) return;
  var flagUrl = loc.flag_url || ('/static/flags/' + (loc.country_code || 'un') + '.svg');
  var label = loc.country_name || 'Global';
  ['panel-flag-img', 'sys-flag-img'].forEach(function (id) {
    var img = $(id);
    if (img) { img.src = flagUrl; img.alt = loc.country_code || 'flag'; }
  });
  set('panel-location-text', label);
  set('sys-location-text', label);
}

function previewSettingsFlag() {
  var sel = $('settings-country');
  var prev = $('settings-flag-preview');
  if (sel && prev && sel.value) {
    prev.src = '/static/flags/' + sel.value + '.svg';
  }
}

async function loadSettingsModal() {
  if (!_countriesLoaded) {
    try {
      var rc = await fetch('/api/countries');
      if (rc.ok) {
        var dc = await rc.json();
        var sel = $('settings-country');
        if (sel && dc.countries) {
          sel.innerHTML = dc.countries.map(function (c) {
            return '<option value="' + esc(c.code) + '">' + esc(c.name) + ' (' + c.code.toUpperCase() + ')</option>';
          }).join('');
          _countriesLoaded = true;
        }
      }
    } catch (e) {}
  }
  ['current', 'new', 'confirm'].forEach(function (k) {
    var el = $('settings-' + k + '-pw');
    if (el) el.value = '';
  });
  var err = $('settingsError');
  if (err) err.classList.add('hidden');
  try {
    var r = await fetch('/api/settings');
    if (r.ok) {
      var s = await r.json();
      if ($('settings-cdn-host')) $('settings-cdn-host').value = s.cdn_host || '';
      if (s.panel_location) {
        if ($('settings-country')) $('settings-country').value = s.panel_location.country_code || 'us';
        if ($('settings-city')) $('settings-city').value = s.panel_location.city || '';
        previewSettingsFlag();
      }
    }
  } catch (e) {}
}

async function saveNetworkSettings() {
  try {
    var cdn = $('settings-cdn-host') ? $('settings-cdn-host').value.trim() : '';
    var r = await J('/api/settings', { cdn_host: cdn });
    if (!r.ok) throw new Error('Could not save settings');
    toast('Network settings saved', 'ok');
    loadConfigs();
  } catch (e) {
    toast(e.message, 'err');
  }
}

async function changePassword() {
  var cur = $('settings-current-pw').value, nw = $('settings-new-pw').value, cf = $('settings-confirm-pw').value, er = $('settingsError');
  er.classList.add('hidden');
  var fail = function (m) { er.textContent = m; er.classList.remove('hidden'); };
  if (!cur || !nw || !cf) return fail('All fields are required.');
  if (nw.length < 4) return fail('New password must be at least 4 characters.');
  if (nw !== cf) return fail('New password and confirmation do not match.');
  try {
    var r = await J('/api/change-password', { current_password: cur, new_password: nw });
    if (!r.ok) throw new Error(await jerr(r, 'Could not update password'));
    toggleModal('settingsModal', false);
    triggerAlert('Password updated', 'Your password was changed. You will be signed out.', 'ok');
    setTimeout(goLogin, 2000);
  } catch (e) {
    fail(e.message);
  }
}

loadConfigs();
setInterval(updateStats, 5000);
setInterval(loadConfigs, 15000);
