#!/usr/bin/env python3
"""Download the Moby Thesaurus II (public domain, Grady Ward) as data only: fetch_moby.py OUT_FILE [URL ...]."""
import sys
import urllib.request

URLS = ["https://www.gutenberg.org/files/3202/files/mthesaur.txt",
        "https://raw.githubusercontent.com/zeke/moby/master/words.txt",
        "https://www.gutenberg.org/cache/epub/3202/pg3202.txt"]

out = sys.argv[1]
for u in sys.argv[2:] or URLS:
    try:
        data = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=90).read()
        print(u, len(data), data[:80])
        if len(data) > 1_000_000:
            open(out, "wb").write(data)
            break
    except Exception as e:
        print(u, "failed", e)
