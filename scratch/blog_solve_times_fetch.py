#!/usr/bin/env python3
"""Sample ~200 bigdave44 posts plus every annotated one; posts' comments (3s crawl delay) into ~/.cache/blog_solve_times/bigdave44.

Stratified by series from tools/data/blog_facts, posts dated 2023+, seed 0."""
import json, random, re, sys, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from fetch_wp_blog import UA, BLOGS
BD = BLOGS["bigdave44"]
OUT = Path.home() / ".cache/blog_solve_times/bigdave44"
PLAN = {"telegraph": 70, "toughie": 60, "sundaytel": 40, "sundaytough": 30}

def main():
    link2id = {}
    for f in BD.posts.glob("*.json"):
        p = json.loads(f.read_text())
        link2id[p["link"].rstrip("/")] = p["id"]
    rng = random.Random(0)
    sample = {}
    for series, n in PLAN.items():
        facts = json.loads((ROOT / f"tools/data/blog_facts/{series}.json").read_text())
        cand = sorted(pid for pid, v in facts.items() if v.get("blog") == "bigdave44"
                      and re.search(r"/20(2[3-6])/", v["url"]) and v["url"].rstrip("/") in link2id)
        for pid in rng.sample(cand, min(n, len(cand))):
            sample[pid] = link2id[facts[pid]["url"].rstrip("/")]
        # Plus every annotated puzzle: only those have a clue index to validate against.
        import difficulty as D
        from fetch_puzzle import read_puzzle_file
        for pid, v in facts.items():
            f = ROOT / "puzzles" / f"{pid}.json"
            if (v.get("blog") == "bigdave44" and v["url"].rstrip("/") in link2id and f.exists()
                    and D.puzzle_is_annotated(read_puzzle_file(f))):
                sample[pid] = link2id[v["url"].rstrip("/")]
    (OUT / "sample.json").write_text(json.dumps(sample, indent=0))
    todo = [p for p in sorted(set(sample.values())) if not (OUT / f"{p}.json").exists()]
    print(f"{len(sample)} sampled, {len(todo)} to fetch", flush=True)
    for i in range(0, len(todo), 2):
        batch = todo[i:i + 2]
        rows, page = [], 1
        while True:
            u = (f"{BD.api}comments?post={','.join(map(str, batch))}&per_page=100&page={page}"
                 "&_fields=id,post,parent,date,author_name,content")
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60) as r:
                got = json.load(r); pages = int(r.headers.get("X-WP-TotalPages", 1))
            rows += got
            time.sleep(BD.crawl_delay)
            if page >= pages: break
            page += 1
        for p in batch:
            (OUT / f"{p}.json").write_text(json.dumps([x for x in rows if x["post"] == p]))
        print(f"  {i + len(batch)}/{len(todo)} +{len(rows)}", flush=True)

main()
