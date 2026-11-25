/* What worker.js and webpush.js share, so a number or a rule is written once. */

// Seconds, because KV's expirationTtl and a JWT's exp are; times a thousand
// where a Date wants milliseconds.
export const HOUR = 60 * 60;
export const DAY = 24 * HOUR;

// A caller that is not a person: no User-Agent at all, or one that names a
// crawler, a headless browser, a script or a link-preview fetcher. Used by
// every route that would otherwise bill a KV read or count a beacon for it.
const BOT_UA = /bot|crawl|spider|slurp|headless|lightpanda|phantom|lighthouse|puppeteer|playwright|selenium|python|curl|wget|httpclient|facebookexternalhit|preview|monitor|go-http|node-fetch|axios/i;

export function isBot(ua) {
  return !ua || BOT_UA.test(ua);
}
