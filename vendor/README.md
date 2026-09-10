# Vendored, not written here

`jsQR-1.4.0.js` is [jsQR](https://github.com/cozmo/jsQR) 1.4.0, byte for byte as
npm publishes it, Apache-2.0 (`LICENSE-jsQR.txt`). It decodes a QR code out of a
camera frame, which the sync panel needs and Safari will not do: `BarcodeDetector`
is a Chrome API, and on an iPhone the only way to read the square on another
device is to carry a decoder in the page.

    source  https://unpkg.com/jsqr@1.4.0/dist/jsQR.js
    sha256  bc40c8a15196236b2314db0856f72ca0b49980cd5413b8c852a7349f5fee0859

The version is in the filename because that is the whole cache-busting story for
a file that never changes: `tools/stamp_assets.py` stamps what the site edits,
and a pinned dependency is not that. Bumping it means a new filename and a new
hash here, so the two can never drift apart quietly — `tools/smoke_test.js`
checks the file against the hash above.

It is fetched on the first press of "Scan a code" and never otherwise. A quarter
of a megabyte is a lot to answer a question most people answer by typing eight
characters, and nobody who types them pays for it.
