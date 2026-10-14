/* gunzip for the browsers app.js supports that have no DecompressionStream
   (Safari before 16.4, Firefox before 113). The site ships each puzzle as
   puzzles/<id>.js.gz (tools/stage_site.py), and app.js loads this file only
   when it has to inflate one by hand. A plain DEFLATE decoder after zlib's
   puff.c: stored, fixed and dynamic blocks; one gzip member.
   tools/test_inflate.js holds it to zlib. */
(function (root) {
  "use strict";
  const LBASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258];
  const LEXT = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0];
  const DBASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577];
  const DEXT = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13];
  const ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];

  function build(lengths) {
    const count = new Uint16Array(16), offs = new Uint16Array(16), symbol = new Uint16Array(lengths.length);
    for (let i = 0; i < lengths.length; i++) count[lengths[i]]++;
    count[0] = 0;
    for (let i = 1; i < 16; i++) offs[i] = offs[i - 1] + count[i - 1];
    for (let i = 0; i < lengths.length; i++) if (lengths[i]) symbol[offs[lengths[i]]++] = i;
    return { count, symbol };
  }

  function inflateRaw(src, pos) {
    let out = new Uint8Array(src.length * 4 + 1024), olen = 0, bitbuf = 0, bitcnt = 0;
    const bits = (n) => {
      while (bitcnt < n) {
        if (pos >= src.length) throw new Error("inflate: out of input");
        bitbuf |= src[pos++] << bitcnt;
        bitcnt += 8;
      }
      const v = bitbuf & ((1 << n) - 1);
      bitbuf >>>= n;
      bitcnt -= n;
      return v;
    };
    const put = (b) => {
      if (olen === out.length) { const o = new Uint8Array(out.length * 2); o.set(out); out = o; }
      out[olen++] = b;
    };
    const decode = (h) => {
      let code = 0, first = 0, index = 0;
      for (let len = 1; len < 16; len++) {
        code |= bits(1);
        const c = h.count[len];
        if (code - c < first) return h.symbol[index + (code - first)];
        index += c; first += c; first <<= 1; code <<= 1;
      }
      throw new Error("inflate: bad code");
    };
    const codes = (lencode, distcode) => {
      for (;;) {
        let sym = decode(lencode);
        if (sym < 256) { put(sym); continue; }
        if (sym === 256) return;
        sym -= 257;
        if (sym >= 29) throw new Error("inflate: bad length");
        let len = LBASE[sym] + bits(LEXT[sym]);
        const d = decode(distcode);
        if (d >= 30) throw new Error("inflate: bad distance");
        const dist = DBASE[d] + bits(DEXT[d]);
        if (dist > olen) throw new Error("inflate: distance too far");
        while (len--) put(out[olen - dist]);
      }
    };
    let fixed = null, last;
    do {
      last = bits(1);
      const type = bits(2);
      if (type === 0) {
        bitbuf = 0; bitcnt = 0;
        const len = src[pos] | (src[pos + 1] << 8);
        if (((~(src[pos + 2] | (src[pos + 3] << 8))) & 0xffff) !== len) throw new Error("inflate: bad stored block");
        pos += 4;
        if (pos + len > src.length) throw new Error("inflate: out of input");
        for (let i = 0; i < len; i++) put(src[pos++]);
      } else if (type === 1) {
        if (!fixed) {
          const l = new Uint8Array(288);
          l.fill(8, 0, 144); l.fill(9, 144, 256); l.fill(7, 256, 280); l.fill(8, 280, 288);
          fixed = [build(l), build(new Uint8Array(30).fill(5))];
        }
        codes(fixed[0], fixed[1]);
      } else if (type === 2) {
        const nlen = bits(5) + 257, ndist = bits(5) + 1, ncode = bits(4) + 4;
        const cl = new Uint8Array(19);
        for (let i = 0; i < ncode; i++) cl[ORDER[i]] = bits(3);
        const clcode = build(cl);
        const lengths = new Uint8Array(nlen + ndist);
        for (let i = 0; i < nlen + ndist;) {
          let sym = decode(clcode);
          if (sym < 16) { lengths[i++] = sym; continue; }
          let len = 0;
          if (sym === 16) {
            if (!i) throw new Error("inflate: repeat with no length");
            len = lengths[i - 1];
            sym = 3 + bits(2);
          } else sym = sym === 17 ? 3 + bits(3) : 11 + bits(7);
          if (i + sym > nlen + ndist) throw new Error("inflate: too many lengths");
          while (sym--) lengths[i++] = len;
        }
        codes(build(lengths.subarray(0, nlen)), build(lengths.subarray(nlen)));
      } else throw new Error("inflate: bad block type");
    } while (!last);
    return out.subarray(0, olen);
  }

  // The bytes a gzip file holds (RFC 1952), header skipped, trailer unread.
  function gunzip(src) {
    if (src[0] !== 0x1f || src[1] !== 0x8b || src[2] !== 8) throw new Error("gunzip: not gzip");
    const flg = src[3];
    let pos = 10;
    if (flg & 4) pos += 2 + (src[pos] | (src[pos + 1] << 8));
    if (flg & 8) while (src[pos++]);
    if (flg & 16) while (src[pos++]);
    if (flg & 2) pos += 2;
    return inflateRaw(src, pos);
  }

  root.ctGunzip = gunzip;
  if (typeof module !== "undefined" && module.exports) module.exports = gunzip;
})(typeof window !== "undefined" ? window : this);
