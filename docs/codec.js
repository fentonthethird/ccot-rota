/* CCOT preference code, schema version 2 (version 1 codes are still read).

   Bit layout, most significant bit first:
     4   schema version (2)
     15  initials, three letters, A=1 .. Z=26, 0 = blank
     14  window start, days since 2024-01-01
     9   window length in days (1 .. 511)
     9   most shifts wanted in the window, 0 = no limit   (version 2 only)
     N   one bit per day of the window, 1 = available
     P   one bit per weekend whose Saturday and Sunday are both inside the window,
         in date order, 1 = keep both days together
     16  CRC-16/CCITT-FALSE over the bytes above (zero padded to a whole byte)
         followed by the link token bytes
   The stream is zero padded to a multiple of 5 bits and written in Crockford base32.
   Displayed as INITIALS-BODY. On decode, case, hyphens and spaces are ignored and
   O is read as 0, I and L as 1.

   Runs in the browser (globalThis.CCOTCodec) and in a bare JavaScript engine for tests.
   engine/ccot/codec.py is the reference decoder; shared test vectors keep them in step. */
(function (root) {
  'use strict';
  const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
  const EPOCH_ISO = '2024-01-01';
  const EPOCH = Date.UTC(2024, 0, 1);
  const DAY = 86400000;
  const VERSION = 2;
  const READS = [1, 2];
  const MAX_LEN = 511;
  const HEADER_BITS = 4 + 15 + 14 + 9;

  function utc(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso));
    if (!m) throw new Error('bad date ' + iso);
    const ms = Date.UTC(+m[1], +m[2] - 1, +m[3]);
    if (new Date(ms).toISOString().slice(0, 10) !== iso) throw new Error('bad date ' + iso);
    return ms;
  }
  function dayNumber(iso) { return Math.round((utc(iso) - EPOCH) / DAY); }
  function isoFromDayNumber(n) { return new Date(EPOCH + n * DAY).toISOString().slice(0, 10); }

  /* Indices of Saturdays whose Sunday is also inside the window. */
  function pairSlots(startIso, len) {
    const out = [];
    const dow0 = new Date(utc(startIso)).getUTCDay(); // 0 = Sunday .. 6 = Saturday
    for (let i = 0; i < len - 1; i++) if ((dow0 + i) % 7 === 6) out.push(i);
    return out;
  }

  function crc16(bytes) {
    let crc = 0xFFFF;
    for (const b of bytes) {
      crc ^= (b & 0xFF) << 8;
      for (let i = 0; i < 8; i++) crc = (crc & 0x8000) ? ((crc << 1) ^ 0x1021) & 0xFFFF : (crc << 1) & 0xFFFF;
    }
    return crc;
  }
  function hexToBytes(hex) {
    hex = String(hex || '').trim().toLowerCase();
    if (!/^([0-9a-f]{2})*$/.test(hex)) throw new Error('token must be an even-length hex string');
    const out = [];
    for (let i = 0; i < hex.length; i += 2) out.push(parseInt(hex.slice(i, i + 2), 16));
    return out;
  }
  function bitsToBytes(bits) {
    const out = [];
    for (let i = 0; i < bits.length; i += 8) {
      let v = 0;
      for (let j = 0; j < 8; j++) v = (v << 1) | (bits[i + j] || 0);
      out.push(v);
    }
    return out;
  }
  function pushBits(bits, value, n) { for (let b = n - 1; b >= 0; b--) bits.push((value >>> b) & 1); }
  function readBits(bits, pos, n) { let v = 0; for (let i = 0; i < n; i++) v = v * 2 + (bits[pos + i] || 0); return v; }

  function encodeInitials(ini) {
    ini = String(ini || '').toUpperCase();
    if (!/^[A-Z]{1,3}$/.test(ini)) throw new Error('initials must be 1 to 3 letters');
    const bits = [];
    for (let i = 0; i < 3; i++) pushBits(bits, i < ini.length ? ini.charCodeAt(i) - 64 : 0, 5);
    return { bits, ini };
  }
  function base32Encode(bits) {
    let s = '';
    for (let i = 0; i < bits.length; i += 5) s += ALPHABET[readBits(bits, i, 5)];
    return s;
  }
  function normaliseBody(s) {
    return String(s).toUpperCase().replace(/[^0-9A-Z]/g, '').replace(/O/g, '0').replace(/[IL]/g, '1');
  }
  function base32Decode(body) {
    const bits = [];
    for (const ch of body) {
      const v = ALPHABET.indexOf(ch);
      if (v < 0) throw new Error('invalid character ' + ch);
      pushBits(bits, v, 5);
    }
    return bits;
  }

  /* o = { initials, start (ISO), len, days (array of 0/1, length len), pairs (Saturday indices), max (most shifts wanted, 0 or empty = no limit), token (hex) } */
  function encode(o) {
    const start = dayNumber(o.start);
    const len = o.len | 0;
    if (len < 1 || len > MAX_LEN) throw new Error('window length must be 1 to ' + MAX_LEN + ' days');
    if (start < 0 || start >= 16384) throw new Error('window start out of range');
    if (!o.days || o.days.length !== len) throw new Error('days must have one entry per day of the window');
    const slots = pairSlots(o.start, len);
    const pairs = new Set(o.pairs || []);
    for (const p of pairs) if (slots.indexOf(p) < 0) throw new Error('pair flag ' + p + ' is not a Saturday inside the window');
    const ini = encodeInitials(o.initials);
    const max = o.max ? Math.floor(Number(o.max)) : 0;
    if (!(max >= 0 && max <= MAX_LEN)) throw new Error('most shifts wanted must be 0 to ' + MAX_LEN);
    const bits = [];
    pushBits(bits, VERSION, 4);
    bits.push(...ini.bits);
    pushBits(bits, start, 14);
    pushBits(bits, len, 9);
    pushBits(bits, max, 9);
    for (let i = 0; i < len; i++) bits.push(o.days[i] ? 1 : 0);
    for (const s of slots) bits.push(pairs.has(s) ? 1 : 0);
    const crc = crc16(bitsToBytes(bits).concat(hexToBytes(o.token)));
    pushBits(bits, crc, 16);
    while (bits.length % 5) bits.push(0);
    return ini.ini + '-' + base32Encode(bits);
  }

  /* Returns { version, initials, start, end, len, max (null = no limit), days, pairs, pairSlots }. Throws with a plain message on any problem. */
  function decode(code, o) {
    o = o || {};
    let raw = String(code || '').replace(/[‐-―−]/g, '-').trim();
    let prefix = null;
    const hy = raw.lastIndexOf('-');
    if (hy >= 0) { prefix = raw.slice(0, hy).replace(/[^A-Za-z]/g, '').toUpperCase(); raw = raw.slice(hy + 1); }
    const body = normaliseBody(raw);
    if (body.length < Math.ceil(HEADER_BITS / 5)) throw new Error('code is too short to be valid');
    const bits = base32Decode(body);
    let pos = 0;
    const version = readBits(bits, pos, 4); pos += 4;
    if (READS.indexOf(version) < 0) throw new Error('unknown code version ' + version + ' (expected ' + READS.join(' or ') + ')');
    let initials = '';
    for (let i = 0; i < 3; i++) {
      const v = readBits(bits, pos, 5); pos += 5;
      if (v > 26) throw new Error('corrupt code (initials)');
      if (v) initials += String.fromCharCode(64 + v);
    }
    if (!initials) throw new Error('corrupt code (no initials)');
    const start = readBits(bits, pos, 14); pos += 14;
    const len = readBits(bits, pos, 9); pos += 9;
    if (len < 1) throw new Error('corrupt code (window length is zero)');
    let max = 0;
    if (version >= 2) { max = readBits(bits, pos, 9); pos += 9; }
    const startIso = isoFromDayNumber(start);
    const slots = pairSlots(startIso, len);
    const total = pos + len + slots.length + 16;
    const expectChars = Math.ceil(total / 5);
    if (body.length < expectChars) throw new Error('code is truncated: expected ' + expectChars + ' characters after the dash but got ' + body.length);
    if (body.length > expectChars) throw new Error('code is too long: expected ' + expectChars + ' characters after the dash but got ' + body.length);
    const days = [];
    for (let i = 0; i < len; i++) days.push(bits[pos++]);
    const pairs = [];
    for (const s of slots) if (bits[pos++]) pairs.push(s);
    const crc = readBits(bits, pos, 16);
    const want = crc16(bitsToBytes(bits.slice(0, pos)).concat(hexToBytes(o.token)));
    pos += 16;
    for (; pos < bits.length; pos++) if (bits[pos]) throw new Error('corrupt code (padding)');
    if (crc !== want) throw new Error('checksum failed: the code was damaged in transit or was made from a different link');
    if (prefix && prefix !== initials) throw new Error('prefix ' + prefix + ' does not match the initials inside the code (' + initials + ')');
    return { version, initials, start: startIso, end: isoFromDayNumber(start + len - 1), len, max: max || null, days, pairs, pairSlots: slots };
  }

  root.CCOTCodec = { encode, decode, pairSlots, dayNumber, isoFromDayNumber, crc16, VERSION, ALPHABET, EPOCH_ISO, MAX_LEN };
})(typeof globalThis !== 'undefined' ? globalThis : this);
