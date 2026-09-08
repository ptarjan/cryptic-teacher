/* The RFC 8291 test vector, run through sync/webpush.js.

     node tools/test_webpush.js

   Encryption you can only check against itself is encryption you have not
   checked: a push whose keys are derived in the wrong order still decrypts with
   the same wrong order at this end, and the first thing that notices is a phone
   silently showing nothing. So the input here is the appendix of the RFC — its
   subscriber keys, its sender key, its salt — and the output is compared with
   the body the RFC says those produce, byte for byte.

   The VAPID half cannot be pinned that way (ECDSA signs differently every
   time), so it is checked by verifying the signature it produced and reading
   the claims back out. */
import { encryptWith, vapidHeader, bytesToB64url, b64urlToBytes } from "../sync/webpush.js";

const V = {
  plaintext: "When I grow up, I want to be a watermelon",
  p256dh: "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
  auth: "BTBZMqHH6r4Tts7J_aSIgg",
  asPublic: "BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8",
  asPrivate: "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw",
  salt: "DGv6ra1nlYgDCS1FRnbzlw",
  // RFC 8291 section 5, the whole 145-byte body: 21-byte header, the sender's
  // 65-byte public key, then the sealed record.
  body: "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml" +
        "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT" +
        "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN",
};

let failed = 0;
const check = (name, got, want) => {
  if (got === want) return console.log(`ok   ${name}`);
  failed++;
  console.log(`FAIL ${name}\n  got  ${got}\n  want ${want}`);
};

async function senderKeyPair() {
  const pub = b64urlToBytes(V.asPublic);
  const jwk = {
    kty: "EC", crv: "P-256", d: V.asPrivate,
    x: bytesToB64url(pub.slice(1, 33)), y: bytesToB64url(pub.slice(33, 65)),
  };
  return {
    privateKey: await crypto.subtle.importKey("jwk", jwk, { name: "ECDH", namedCurve: "P-256" },
                                              false, ["deriveBits"]),
    publicKey: await crypto.subtle.importKey("raw", pub, { name: "ECDH", namedCurve: "P-256" },
                                             true, []),
  };
}

const body = await encryptWith(V.plaintext, V.p256dh, V.auth, await senderKeyPair(),
                               b64urlToBytes(V.salt));
check("aes128gcm body matches RFC 8291", bytesToB64url(body), V.body);

const vapid = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true,
                                              ["sign", "verify"]);
const jwk = await crypto.subtle.exportKey("jwk", vapid.privateKey);
const pub = bytesToB64url(await crypto.subtle.exportKey("raw", vapid.publicKey));
const header = await vapidHeader("https://fcm.googleapis.com/fcm/send/abc", jwk, pub,
                                 "mailto:nobody@example.com");

const [, token, key] = header.match(/^vapid t=([^,]+), k=(.+)$/) || [];
check("the header carries the public key", key, pub);
const [h, p, sig] = (token || "").split(".");
const claims = JSON.parse(new TextDecoder().decode(b64urlToBytes(p)));
check("aud is the push service's origin, not the endpoint", claims.aud, "https://fcm.googleapis.com");
check("alg is ES256", JSON.parse(new TextDecoder().decode(b64urlToBytes(h))).alg, "ES256");
check("exp is inside the 24h the RFC allows",
      claims.exp - Math.floor(Date.now() / 1000) <= 24 * 60 * 60, true);
check("the signature verifies against the public key",
      await crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, vapid.publicKey,
                                 b64urlToBytes(sig), new TextEncoder().encode(`${h}.${p}`)), true);

process.exit(failed ? 1 : 0);
