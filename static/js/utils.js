function toast(t, k) {
  var e = document.getElementById('toast');
  if (!e) return;
  e.textContent = t;
  e.className = 'toast on ' + (k || '');
  clearTimeout(toast.t);
  toast.t = setTimeout(function () { e.classList.remove('on'); }, 2400);
}

function copyText(t) {
  var ok = function () { toast('Copied to clipboard', 'ok'); };
  var fb = function () {
    var a = document.createElement('textarea');
    a.value = t;
    a.style.cssText = 'position:fixed;opacity:0;left:-9999px';
    document.body.appendChild(a);
    a.select();
    try { document.execCommand('copy'); ok(); } catch (e) { toast('Copy failed', 'err'); }
    a.remove();
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(t).then(ok, fb);
  } else {
    fb();
  }
}

function cp(id, b) {
  var el = document.getElementById(id);
  if (!el) return;
  copyText(el.value);
  var t = b.textContent;
  if (t.trim()) {
    b.textContent = 'Copied';
    setTimeout(function () { b.textContent = t; }, 1200);
  }
}
