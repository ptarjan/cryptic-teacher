#!/usr/bin/env python3
"""Download the crossword pages of two archive.org scan sets for image reading.

    python3 tools/scan_fetch.py nation   # collection pub_nation: The Nation, 1943-2011
    python3 tools/scan_fetch.py azed     # Digital Library of India SUNDAY magazine items with Azed

Each issue/item gets a folder under downloads.NATION_SCANS / downloads.AZED_SCANS:
djvu.txt, djvu.xml.gz, pages.json (the pages kept and why) and leaf_NNNN.jpg for each
page whose OCR text matches. Page images come from BookReaderImages.php one leaf at a
time (never the whole jp2.zip). index.json at the root lists every issue's pages.
Requests are paced at least 2 s apart; re-running skips what is on disk.
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import downloads

DELAY = 2.0
_last = [0.0]
AZED_ITEMS = ["dli.bengal.10689.22028", "dli.bengal.10689.23415", "dli.bengal.10689.13117",
              "dli.bengal.10689.15514", "dli.bengal.10689.20788"]


def get(url, tries=4):
    for n in range(tries):
        wait = DELAY - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return urllib.request.urlopen(req, timeout=120).read()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                return None
            err = e
        except Exception as e:
            err = e
        time.sleep(10 * (n + 1))
    raise err


def write(path, data):
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def pages_of(xml):
    """[(leaf, text)] from a djvu.xml: leaf from the OBJECT's PAGE param, else its order."""
    out = []
    for i, m in enumerate(re.finditer(r"<OBJECT\b(.*?)</OBJECT>", xml, re.S), 1):
        blk = m.group(1)
        pm = re.search(r'name="PAGE"\s+value="[^"]*?_(\d+)\.djvu"', blk)
        leaf = int(pm.group(1)) if pm else i
        words = re.findall(r"<WORD[^>]*>([^<]*)</WORD>", blk)
        out.append((leaf, " ".join(words)))
    return out


def want_nation(text):
    return bool(re.search(r"crossword\s+puzzle", text, re.I)) or (
        "ACROSS" in text and "DOWN" in text and re.search(r"crossword", text, re.I))


def want_azed(text):
    return bool(re.search(r"\bazed\b", text, re.I))


def fetch_item(item, root, want, need_txt_hit=None):
    d = os.path.join(root, item)
    done = os.path.join(d, "pages.json")
    if os.path.exists(done):
        return json.load(open(done))
    os.makedirs(d, exist_ok=True)
    base = f"https://archive.org/download/{item}/{item}"
    txt_name = "_djvu.txt"
    if item.startswith("dli."):
        base = f"https://archive.org/download/{item}/{item.split('.', 2)[2]}"
    txt = get(base + "_djvu.txt")
    if txt is None:
        doc = {"item": item, "public": False, "pages": []}
        write(done, json.dumps(doc).encode())
        return doc
    write(os.path.join(d, "djvu.txt"), txt)
    if need_txt_hit and not re.search(need_txt_hit, txt.decode("utf8", "replace"), re.I):
        doc = {"item": item, "public": True, "pages": []}
        write(done, json.dumps(doc).encode())
        return doc
    xml = get(base + "_djvu.xml")
    write(os.path.join(d, "djvu.xml.gz"), gzip.compress(xml, 6))
    pages = pages_of(xml.decode("utf8", "replace"))
    keep = [leaf for leaf, text in pages if want(text)]
    meta = json.loads(get(f"https://archive.org/metadata/{item}"))
    stem = item.split(".", 2)[2] if item.startswith("dli.") else item
    names = {f["name"] for f in meta["files"]}
    zipname = stem + ("_jp2.zip" if stem + "_jp2.zip" in names else "_jp2.tar")
    got = []
    for leaf in keep:
        path = os.path.join(d, f"leaf_{leaf:04d}.jpg")
        if not os.path.exists(path):
            url = f"https://{meta['server']}/BookReader/BookReaderImages.php?" + urllib.parse.urlencode(
                {"zip": f"{meta['dir']}/{zipname}", "file": f"{stem}_jp2/{stem}_{leaf:04d}.jp2",
                 "id": item, "scale": 1, "rotate": 0})
            data = get(url)
            if not data or not data.startswith(b"\xff\xd8"):
                print("bad image", item, leaf, file=sys.stderr)
                continue
            write(path, data)
        got.append(leaf)
    doc = {"item": item, "public": True, "title": meta["metadata"].get("title"),
           "date": meta["metadata"].get("date"), "leaves": len(pages), "pages": got}
    write(done, json.dumps(doc, indent=1).encode())
    return doc


def nation_ids():
    q = urllib.parse.quote("collection:pub_nation")
    r = json.loads(get(f"https://archive.org/advancedsearch.php?q={q}&fl[]=identifier&rows=2000&output=json"))
    return sorted(x["identifier"] for x in r["response"]["docs"]
                  if re.match(r"sim_nation_\d{4}-\d\d-\d\d_", x["identifier"]))


def main(which):
    if which == "nation":
        root, ids, want, hit = str(downloads.NATION_SCANS), nation_ids(), want_nation, r"crossword\s+puzzle"
    else:
        root, ids, want, hit = str(downloads.AZED_SCANS), AZED_ITEMS, want_azed, r"\bazed\b"
    os.makedirs(root, exist_ok=True)
    index = {}
    for n, item in enumerate(ids, 1):
        index[item] = fetch_item(item, root, want, hit)
        if n % 25 == 0 or n == len(ids):
            write(os.path.join(root, "index.json"), json.dumps(index, indent=1).encode())
            print(n, "of", len(ids), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
