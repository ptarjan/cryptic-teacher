/* Web push, from scratch, because the alternative is a dependency in a Worker.

   Two things have to be built for a push to be accepted by Apple's, Google's or
   Mozilla's push service, and neither is optional:

   - VAPID (RFC 8292) says who is sending. An ES256 JWT over the push service's
     own origin, signed with a key whose public half the browser was given when
     it subscribed. It is what stops anyone who has seen an endpoint from
     pushing to it.
   - aes128gcm (RFC 8291) says what is being sent. The payload is encrypted to
     the SUBSCRIBER, using the two keys the browser handed over — `p256dh` and
     `auth` — so the push service relays a body it cannot read.

   The service worker could instead take an empty push and go and fetch what is
   new, which needs none of this. It is not enough here: a push must show a
   notification, so the sender has to decide who hears about which puzzle, and a
   subscriber who only wants the Independent must not be woken for an Everyman
   and then have nothing to show. One puzzle per push, named in the payload.

   Nothing in here is specific to crosswords; sync/worker.js is the caller. */

const enc = new TextEncoder();

export const b64urlToBytes = (s) => {
  const b = atob(s.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
};

export const bytesToB64url = (b) =>
  btoa(String.fromCharCode(...new Uint8Array(b)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

const concat = (...parts) => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
};

/* HKDF in one call: WebCrypto's HKDF is extract-and-expand, which is exactly
   what each of the three derivations below is, so none of them needs HMAC by
   hand. */
async function hkdf(ikm, salt, info, bytes) {
  const key = await crypto.subtle.importKey("raw", ikm, "HKDF", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits(
    { name: "HKDF", hash: "SHA-256", salt, info }, key, bytes * 8);
  return new Uint8Array(bits);
}

/* The body of an aes128gcm push, given the sender's ephemeral key and salt.

   Split out from encrypt() so the RFC 8291 test vector can be reproduced: those
   two values are the only randomness in the scheme, and a test that cannot fix
   them can only check that this code agrees with itself. */
export async function encryptWith(payload, p256dh, auth, ephemeral, salt, recordSize = 4096) {
  const uaPublic = b64urlToBytes(p256dh);
  const asPublic = new Uint8Array(await crypto.subtle.exportKey("raw", ephemeral.publicKey));
  const uaKey = await crypto.subtle.importKey(
    "raw", uaPublic, { name: "ECDH", namedCurve: "P-256" }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits(
    { name: "ECDH", public: uaKey }, ephemeral.privateKey, 256));

  // The key derivation is keyed on both public keys, so a ciphertext cannot be
  // replayed at a different subscriber even by whoever relayed it.
  const keyInfo = concat(enc.encode("WebPush: info"), new Uint8Array([0]), uaPublic, asPublic);
  const ikm = await hkdf(shared, b64urlToBytes(auth), keyInfo, 32);
  const cek = await hkdf(ikm, salt, enc.encode("Content-Encoding: aes128gcm\0"), 16);
  const nonce = await hkdf(ikm, salt, enc.encode("Content-Encoding: nonce\0"), 12);

  // 0x02 is the delimiter of the last record. There is only ever one record
  // here: the payload is a title and a puzzle name, not a file.
  const record = concat(enc.encode(payload), new Uint8Array([2]));
  const aesKey = await crypto.subtle.importKey("raw", cek, "AES-GCM", false, ["encrypt"]);
  const sealed = new Uint8Array(await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: nonce, tagLength: 128 }, aesKey, record));

  const header = new Uint8Array(21);
  header.set(salt, 0);
  new DataView(header.buffer).setUint32(16, recordSize);
  header[20] = asPublic.length;
  return concat(header, asPublic, sealed);
}

export async function encrypt(payload, p256dh, auth) {
  const ephemeral = await crypto.subtle.generateKey(
    { name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const salt = crypto.getRandomValues(new Uint8Array(16));
  return encryptWith(payload, p256dh, auth, ephemeral, salt);
}

/* The Authorization header for one push service.

   `aud` is the push service's ORIGIN and nothing else — a JWT minted for
   fcm.googleapis.com is rejected by web.push.apple.com, so this is per
   endpoint, not per run. Twelve hours is well inside the 24 the RFC allows and
   leaves room for a slow clock at either end. */
export async function vapidHeader(endpoint, jwk, publicKey, subject) {
  const aud = new URL(endpoint).origin;
  const exp = Math.floor(Date.now() / 1000) + 12 * 60 * 60;
  const part = (o) => bytesToB64url(enc.encode(JSON.stringify(o)));
  const signing = `${part({ typ: "JWT", alg: "ES256" })}.${part({ aud, exp, sub: subject })}`;
  const key = await crypto.subtle.importKey(
    "jwk", jwk, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" }, key, enc.encode(signing));
  return `vapid t=${signing}.${bytesToB64url(sig)}, k=${publicKey}`;
}

/* Send one notification. Resolves to the push service's status.

   404 and 410 are the answer that matters: the subscription is gone — the app
   was deleted, or the browser rotated it — and the caller must drop the record
   rather than retry it for a year. */
export async function send(subscription, payload, vapid, ttl = 12 * 60 * 60) {
  const body = await encrypt(payload, subscription.keys.p256dh, subscription.keys.auth);
  const res = await fetch(subscription.endpoint, {
    method: "POST",
    headers: {
      "authorization": await vapidHeader(subscription.endpoint, vapid.jwk, vapid.publicKey,
                                         vapid.subject),
      "content-encoding": "aes128gcm",
      "content-type": "application/octet-stream",
      "ttl": String(ttl),
      "urgency": "normal",
    },
    body,
  });
  return res.status;
}

export const GONE = (status) => status === 404 || status === 410;
