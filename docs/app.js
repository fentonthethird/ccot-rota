/* CCOT preference capture app. Fully client side: nothing leaves the phone except the code the
   consultant chooses to send. Identity and window come from the personalised link and are
   remembered on the device so the installed app opens straight back where it was. */
(() => {
  'use strict';
  const DAY = 86400000;
  const ADMIN_NAME = 'Adam';
  const ADMIN_EMAIL = 'a.woodman-bailey@nhs.net';
  const STORE = 'ccot.v1.';
  const BH = globalThis.CCOT_BANK_HOLIDAYS || {};
  const Codec = globalThis.CCOTCodec;
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const $ = (sel, el) => (el || document).querySelector(sel);

  const utc = (iso) => { const [y, m, d] = iso.split('-').map(Number); return Date.UTC(y, m - 1, d); };
  const toIso = (ms) => new Date(ms).toISOString().slice(0, 10);
  const dow = (ms) => (new Date(ms).getUTCDay() + 6) % 7; // 0 = Monday .. 6 = Sunday
  const fmt = (ms, o) => new Date(ms).toLocaleDateString('en-GB', Object.assign({ timeZone: 'UTC' }, o));
  const isIso = (s) => /^\d{4}-\d{2}-\d{2}$/.test(s || '') && toIso(utc(s)) === s;

  function load(k) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : null; } catch (e) { return null; } }
  function save(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } }

  /* ---------- identity: from the link, else the last link used on this device ---------- */
  function identityFrom(p) {
    const id = {
      c: String(p.c || '').toUpperCase(), k: String(p.k || ''), n: String(p.n || ''), w: String(p.w || ''),
      s: String(p.s || ''), e: String(p.e || ''), d: String(p.d || ''),
      jw: parseInt(p.jw, 10) || 0, je: parseInt(p.je, 10) || 0
    };
    if (!/^[A-Z]{1,3}$/.test(id.c) || !id.w || !isIso(id.s) || !isIso(id.e)) return null;
    const len = (utc(id.e) - utc(id.s)) / DAY + 1;
    if (len < 1 || len > Codec.MAX_LEN) return null;
    if (!isIso(id.d)) id.d = '';
    return id;
  }
  function readIdentity() {
    const q = new URLSearchParams(location.search);
    const o = {}; for (const [k, v] of q) o[k] = v;
    const fromUrl = identityFrom(o);
    if (fromUrl) { save(STORE + 'last', fromUrl); return fromUrl; }
    const last = load(STORE + 'last');
    return last ? identityFrom(last) : null;
  }

  const id = readIdentity();
  if (!id) {
    document.body.innerHTML = '<div class="nolink"><h1>CCOT rota</h1><p>This link is missing your details, so the app cannot tell who you are or which quarter to show.</p><p>Open the personalised link ' + ADMIN_NAME + ' sent you, or ask for a fresh one.</p></div>';
    return;
  }

  /* ---------- state, saved on every change ---------- */
  const startMs = utc(id.s), endMs = utc(id.e), len = (endMs - startMs) / DAY + 1;
  const key = STORE + 'prefs.' + id.w + '.' + id.c;
  const saved = load(key) || {};
  const days = new Uint8Array(len);
  if (typeof saved.days === 'string') for (let i = 0; i < len && i < saved.days.length; i++) days[i] = saved.days[i] === '1' ? 1 : 0;
  const pairSlots = new Set(Codec.pairSlots(id.s, len));
  const pairs = new Set((Array.isArray(saved.pairs) ? saved.pairs : []).filter((p) => pairSlots.has(p)));
  const meta = { lastCode: saved.lastCode || null, lastCodeAt: saved.lastCodeAt || null };
  // Most shifts wanted this window. 0 = no limit (only limited by the days marked).
  let maxWanted = Number.isInteger(saved.max) && saved.max > 0 ? Math.min(saved.max, len) : 0;

  const dateAt = (i) => startMs + i * DAY;
  const inWin = (i) => i >= 0 && i < len;
  const isBH = (i) => Object.prototype.hasOwnProperty.call(BH, toIso(dateAt(i)));
  const isWE = (i) => dow(dateAt(i)) >= 5;

  function persist() {
    save(key, { days: Array.from(days).join(''), pairs: [...pairs].sort((a, b) => a - b), max: maxWanted || null, lastCode: meta.lastCode, lastCodeAt: meta.lastCodeAt, updatedAt: Date.now() });
  }
  function snapshot() { return { days: Uint8Array.from(days), pairs: new Set(pairs) }; }
  function restore(snap) { days.set(snap.days); pairs.clear(); snap.pairs.forEach((p) => pairs.add(p)); persist(); renderAll(); }
  /* Unmarking a Saturday or Sunday drops that weekend's "together" flag. */
  function dropPairFor(i) {
    const d = dow(dateAt(i));
    const sat = d === 5 ? i : d === 6 ? i - 1 : -1;
    if (sat >= 0) pairs.delete(sat);
  }

  function windowLabel() {
    const a = new Date(startMs), b = new Date(endMs);
    const ma = MONTHS[a.getUTCMonth()], mb = MONTHS[b.getUTCMonth()], ya = a.getUTCFullYear(), yb = b.getUTCFullYear();
    if (ya === yb) return ma === mb ? ma + ' ' + ya : ma + ' to ' + mb + ' ' + ya;
    return ma + ' ' + ya + ' to ' + mb + ' ' + yb;
  }
  function counts() {
    let wd = 0, we = 0, bh = 0, together = 0;
    for (let i = 0; i < len; i++) if (days[i]) { if (isBH(i)) bh++; else if (isWE(i)) we++; else wd++; }
    for (const p of pairs) if (days[p] && days[p + 1]) together++;
    return { wd, we, bh, together };
  }

  /* ---------- header ---------- */
  function renderHeader() {
    const c = counts();
    $('#title').textContent = windowLabel();
    $('#who').textContent = id.n ? id.n + ' · ' + id.c : id.c;
    $('#wdCount').textContent = c.wd;
    $('#weCount').textContent = c.we;
    $('#wdOwe').textContent = id.jw ? 'you owe ' + id.jw + ' this year' : 'no weekdays owed';
    $('#weOwe').textContent = id.je ? 'you owe ' + id.je + ' this year' : 'no weekend days owed';
    $('#statWd').classList.toggle('ok', id.jw > 0 && c.wd >= id.jw);
    $('#statWe').classList.toggle('ok', id.je > 0 && c.we >= id.je);
    $('#bhLine').textContent = c.bh ? '+ ' + c.bh + ' bank holiday' + (c.bh > 1 ? 's' : '') : '';
    $('#maxLine').textContent = maxWanted ? 'At most ' + maxWanted + ' shift' + (maxWanted === 1 ? '' : 's') : '';
    renderLimit(c);
    $('#deadline').textContent = id.d ? 'Send your code by ' + fmt(utc(id.d), { weekday: 'short', day: 'numeric', month: 'short' }) : '';
    const banner = $('#banner');
    if (id.d && Date.now() > utc(id.d) + DAY) {
      banner.textContent = 'The deadline (' + fmt(utc(id.d), { weekday: 'long', day: 'numeric', month: 'long' }) + ') has passed. You can still make a code, but check with ' + ADMIN_NAME + ' before relying on it.';
      banner.hidden = false;
    } else banner.hidden = true;
    $('#lastCode').textContent = meta.lastCodeAt
      ? 'You last made a code on ' + fmt(meta.lastCodeAt, { weekday: 'short', day: 'numeric', month: 'short' }) + ' at ' + new Date(meta.lastCodeAt).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) + '. If you have changed anything since, make a new one and send it again.'
      : '';
  }

  /* ---------- most shifts wanted ---------- */
  function renderLimit(c) {
    c = c || counts();
    const input = $('#maxShifts');
    if (document.activeElement !== input) input.value = maxWanted ? String(maxWanted) : '';
    $('#maxDown').disabled = maxWanted <= 1;
    $('#maxUp').disabled = maxWanted >= len;
    $('#maxClear').hidden = !maxWanted;
    const marked = c.wd + c.we + c.bh;
    const owed = id.jw + id.je;
    let hint;
    if (!maxWanted) hint = 'Leave blank for no limit: you could be given any of the days you mark.';
    else {
      hint = 'You will be given no more than ' + maxWanted + ' shift' + (maxWanted === 1 ? '' : 's') + ', however many days you mark.';
      if (owed && maxWanted < owed) hint += ' That is fewer than the ' + owed + ' job plan shift' + (owed === 1 ? '' : 's') + ' you still owe this year.';
      if (marked < maxWanted) hint += ' You have marked ' + marked + ' day' + (marked === 1 ? '' : 's') + ' so far.';
    }
    $('#maxHint').textContent = hint;
  }
  function setMax(v) {
    v = Math.floor(Number(v) || 0);
    maxWanted = v <= 0 ? 0 : Math.min(v, len);
    persist();
    renderHeader();
  }
  $('#maxShifts').addEventListener('input', (ev) => {
    const digits = ev.target.value.replace(/[^0-9]/g, '').slice(0, 3);
    if (digits !== ev.target.value) ev.target.value = digits;
    setMax(digits);
  });
  $('#maxShifts').addEventListener('blur', () => renderLimit());
  $('#maxShifts').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') ev.target.blur(); });
  $('#maxUp').addEventListener('click', () => setMax((maxWanted || 0) + 1));
  $('#maxDown').addEventListener('click', () => { if (maxWanted > 1) setMax(maxWanted - 1); });
  $('#maxClear').addEventListener('click', () => setMax(0));

  /* ---------- month grids ---------- */
  function monthStarts() {
    const out = [];
    let d = new Date(startMs);
    let cur = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1);
    while (cur <= endMs) {
      out.push(cur);
      d = new Date(cur);
      cur = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
    }
    return out;
  }
  function dayLabel(i) {
    const ms = dateAt(i);
    return fmt(ms, { weekday: 'long', day: 'numeric', month: 'long' }) + (isBH(i) ? ', bank holiday' : '') + (days[i] ? ', available' : ', not available');
  }
  function pairChip(sat) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'pair' + (pairs.has(sat) ? ' on' : '');
    b.dataset.sat = sat;
    b.setAttribute('aria-pressed', pairs.has(sat) ? 'true' : 'false');
    b.setAttribute('aria-label', 'Keep Saturday ' + fmt(dateAt(sat), { day: 'numeric', month: 'long' }) + ' and Sunday together');
    b.textContent = (pairs.has(sat) ? '✓ ' : '') + 'Sat + Sun together';
    return b;
  }
  function renderMonth(firstMs) {
    const d = new Date(firstMs);
    const y = d.getUTCFullYear(), m = d.getUTCMonth();
    const nDays = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    const sec = document.createElement('section');
    sec.className = 'month';
    sec.dataset.month = toIso(firstMs).slice(0, 7);
    sec.innerHTML = '<header><h2>' + MONTHS[m] + ' ' + y + '</h2><div class="bulk"><button type="button" data-bulk="on">All</button><button type="button" data-bulk="off">None</button></div></header>';
    const grid = document.createElement('div');
    grid.className = 'grid';
    grid.setAttribute('role', 'group');
    grid.setAttribute('aria-label', MONTHS[m] + ' ' + y);
    DOW.forEach((n, i) => { const e = document.createElement('div'); e.className = 'dow' + (i >= 5 ? ' we' : ''); e.textContent = n; grid.appendChild(e); });
    for (let b = 0; b < dow(firstMs); b++) { const e = document.createElement('div'); e.className = 'blank'; grid.appendChild(e); }
    for (let dd = 1; dd <= nDays; dd++) {
      const ms = Date.UTC(y, m, dd);
      const i = Math.round((ms - startMs) / DAY);
      const ok = inWin(i);
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'day' + (dow(ms) >= 5 ? ' we' : '') + (ok && isBH(i) ? ' bh' : '') + (ok && days[i] ? ' on' : '');
      b.dataset.i = i;
      b.disabled = !ok;
      b.innerHTML = dd + (ok && isBH(i) ? '<small>BH</small>' : '');
      if (ok) { b.setAttribute('aria-pressed', days[i] ? 'true' : 'false'); b.setAttribute('aria-label', dayLabel(i)); }
      else b.setAttribute('aria-label', fmt(ms, { weekday: 'long', day: 'numeric', month: 'long' }) + ', outside this quarter');
      grid.appendChild(b);
      // "Keep together" chip under a weekend where both days are marked. It lives with the
      // Sunday, or with a month-end Saturday whose Sunday falls in the next month.
      const wd = dow(ms);
      const sat = wd === 6 ? i - 1 : wd === 5 && dd === nDays ? i : -1;
      if (sat >= 0 && pairSlots.has(sat) && days[sat] && days[sat + 1]) grid.appendChild(pairChip(sat));
    }
    sec.appendChild(grid);
    return sec;
  }
  function renderMonths() {
    const host = $('#months');
    host.innerHTML = '';
    monthStarts().forEach((ms) => host.appendChild(renderMonth(ms)));
  }
  function rerenderMonthOf(i) {
    const ym = toIso(dateAt(i)).slice(0, 7);
    const old = $('#months section[data-month="' + ym + '"]');
    if (old) old.replaceWith(renderMonth(utc(ym + '-01')));
  }
  function renderAll() { renderHeader(); renderMonths(); }

  /* ---------- interaction ---------- */
  $('#months').addEventListener('click', (ev) => {
    const day = ev.target.closest('button.day');
    if (day && !day.disabled) {
      const i = +day.dataset.i;
      days[i] = days[i] ? 0 : 1;
      if (!days[i]) dropPairFor(i);
      persist();
      // A weekend can straddle two months, so refresh the partner day's month too.
      const d = dow(dateAt(i));
      const partner = d === 5 ? i + 1 : d === 6 ? i - 1 : -1;
      rerenderMonthOf(i);
      if (partner >= 0 && inWin(partner) && toIso(dateAt(partner)).slice(0, 7) !== toIso(dateAt(i)).slice(0, 7)) rerenderMonthOf(partner);
      renderHeader();
      return;
    }
    const chip = ev.target.closest('button.pair');
    if (chip) {
      const sat = +chip.dataset.sat;
      if (pairs.has(sat)) pairs.delete(sat); else pairs.add(sat);
      persist();
      rerenderMonthOf(sat);
      if (toIso(dateAt(sat + 1)).slice(0, 7) !== toIso(dateAt(sat)).slice(0, 7)) rerenderMonthOf(sat + 1);
      renderHeader();
      return;
    }
    const bulk = ev.target.closest('button[data-bulk]');
    if (bulk) {
      const sec = bulk.closest('section.month');
      const ym = sec.dataset.month;
      const snap = snapshot();
      const on = bulk.dataset.bulk === 'on';
      let n = 0;
      for (let i = 0; i < len; i++) if (toIso(dateAt(i)).slice(0, 7) === ym) { days[i] = on ? 1 : 0; if (!on) dropPairFor(i); n++; }
      persist();
      renderAll();
      toast((on ? 'Marked all of ' : 'Cleared ') + sec.querySelector('h2').textContent + (on ? ' available' : ''), () => restore(snap));
    }
  });

  $('#allOn').addEventListener('click', () => {
    const snap = snapshot();
    days.fill(1);
    persist(); renderAll();
    toast('Every day marked available', () => restore(snap));
  });
  $('#allOff').addEventListener('click', () => {
    const snap = snapshot();
    days.fill(0); pairs.clear();
    persist(); renderAll();
    toast('Every day marked unavailable', () => restore(snap));
  });

  let toastTimer = null;
  function hideToast() { $('#toast').hidden = true; }
  function toast(msg, undo) {
    $('#toastMsg').textContent = msg;
    const u = $('#toastUndo');
    u.hidden = !undo;
    u.onclick = () => { if (undo) undo(); hideToast(); };
    $('#toast').hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hideToast, 6000);
  }

  /* ---------- the code ---------- */
  function makeCode() {
    return Codec.encode({ initials: id.c, start: id.s, len, days, pairs: [...pairs].filter((p) => days[p] && days[p + 1]), max: maxWanted, token: id.k });
  }
  function shareText(code) { return 'CCOT availability ' + windowLabel() + ' (' + id.c + '): ' + code; }
  $('#getCode').addEventListener('click', () => {
    let code;
    try { code = makeCode(); } catch (e) { alert('Sorry, the code could not be made: ' + e.message); return; }
    meta.lastCode = code; meta.lastCodeAt = Date.now(); persist(); renderHeader();
    const c = counts();
    const parts = [];
    parts.push(c.wd + ' weekday' + (c.wd === 1 ? '' : 's'));
    parts.push(c.we + ' weekend day' + (c.we === 1 ? '' : 's'));
    if (c.bh) parts.push(c.bh + ' bank holiday' + (c.bh === 1 ? '' : 's'));
    $('#codeSummary').textContent = 'You have marked ' + parts.join(', ') + ' available' + (c.together ? ', with ' + c.together + ' weekend' + (c.together === 1 ? '' : 's') + ' kept together' : '') + '.' + (c.wd + c.we + c.bh === 0 ? ' Sending this tells ' + ADMIN_NAME + ' you cannot do any dates this quarter.' : (maxWanted ? ' You want no more than ' + maxWanted + ' shift' + (maxWanted === 1 ? '' : 's') + ' in total.' : ' No limit on the number of shifts.'));
    $('#codeText').textContent = code;
    $('#codeNote').textContent = 'Send it to ' + ADMIN_NAME + (id.d ? ' by ' + fmt(utc(id.d), { weekday: 'long', day: 'numeric', month: 'long' }) : '') + '. If you change anything later, make a new code and send that. The latest code counts.' +
      (c.bh ? (c.bh === 1
        ? ' You have marked a bank holiday. It is paid as an extra shift unless you tell ' + ADMIN_NAME + ' you would like it to count as a job plan weekend day.'
        : ' You have marked ' + c.bh + ' bank holidays. They are paid as extra shifts unless you tell ' + ADMIN_NAME + ' you would like any of them to count as job plan weekend days.') +
        ' "Email to ' + ADMIN_NAME + '" adds a line for this that you can keep or delete.' : '');
    const subject = 'CCOT availability ' + id.c + ' ' + windowLabel();
    const bhMarked = [];
    for (let i = 0; i < len; i++) if (days[i] && isBH(i)) bhMarked.push(fmt(dateAt(i), { weekday: 'short', day: 'numeric', month: 'short' }));
    const bhLine = bhMarked.length
      ? '\n\nBank holidays: I would like these to count as job plan weekend days instead of extra shifts (delete this paragraph if not, or remove any dates that should stay as extra): ' + bhMarked.join(', ') + '.'
      : '';
    const body = 'Hi ' + ADMIN_NAME + ',\n\nMy CCOT availability code for ' + windowLabel() + ':\n\n' + code + bhLine + '\n\n' + (id.n || id.c);
    $('#mailBtn').href = 'mailto:' + ADMIN_EMAIL + '?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(body);
    $('#mailBtn').textContent = 'Email to ' + ADMIN_NAME;
    $('#shareBtn').hidden = !(navigator.share);
    const dlg = $('#codeDlg');
    if (typeof dlg.showModal === 'function') dlg.showModal(); else dlg.setAttribute('open', '');
  });
  $('#closeDlg').addEventListener('click', () => $('#codeDlg').close());
  $('#codeDlg').addEventListener('click', (ev) => { if (ev.target === ev.currentTarget) ev.currentTarget.close(); });
  $('#copyBtn').addEventListener('click', async () => {
    const code = $('#codeText').textContent;
    let ok = false;
    try { await navigator.clipboard.writeText(code); ok = true; } catch (e) { ok = false; }
    if (!ok) {
      const ta = document.createElement('textarea');
      ta.value = code; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select(); ta.setSelectionRange(0, code.length);
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      ta.remove();
    }
    $('#copyBtn').textContent = ok ? 'Copied ✓' : 'Press and hold the code to copy it';
    setTimeout(() => { $('#copyBtn').textContent = 'Copy code'; }, 2500);
  });
  $('#shareBtn').addEventListener('click', async () => {
    try { await navigator.share({ title: 'CCOT availability', text: shareText($('#codeText').textContent) }); } catch (e) { /* user cancelled */ }
  });

  renderAll();

  if ('serviceWorker' in navigator && /^https?:$/.test(location.protocol)) {
    navigator.serviceWorker.register('./sw.js').catch(() => {});
  }
})();
