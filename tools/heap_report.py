"""Diagnostic only (tools/heap_probe.js): summarise a V8 heap snapshot.

  heap_report.py SNAP OUT.json   prints a report, writes per-constructor totals
  heap_report.py --diff A.json B.json   what grew between two snapshots

Run by tools/heap_probe.js on the runner (numpy only: nightly-smoke.yml's pip).
Retained sizes are approximated by the shortest-path (BFS) tree from the root,
weak edges skipped: each object is charged to the first path that reaches it.
"""
import json
import mmap
import sys

import numpy as np

MB = 1048576.0
STRLIKE = ("number", "string", "concatenated string", "sliced string")


def num_section(buf, key):
    k = buf.find(b'"' + key + b'":[')
    start = k + len(key) + 4
    end = buf.find(b"]", start)
    return start, end


def parse_nums(buf, key, dtype):
    s, e = num_section(buf, key)
    return np.fromstring(buf[s:e].decode("ascii"), dtype=dtype, sep=",")


def load(path):
    with open(path, "rb") as f:
        buf = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    dec = json.JSONDecoder()
    k = buf.find(b'"snapshot":')
    head = buf[k + 11:k + 11 + 200000].decode("utf8", "replace")
    meta = dec.raw_decode(head)[0]["meta"]
    nodes = parse_nums(buf, b"nodes", np.int64)
    edges = parse_nums(buf, b"edges", np.uint32)
    k = buf.find(b'"locations":[')
    locs = parse_nums(buf, b"locations", np.int64) if k >= 0 else np.zeros(0, np.int64)
    k = buf.find(b'"strings":[')
    strings = dec.raw_decode(buf[k + 10:].decode("utf8", "replace"))[0]
    return meta, nodes, edges, locs, strings


def main(path, out):
    meta, nodes, edges, locs, strings = load(path)
    nf, ef = meta["node_fields"], meta["edge_fields"]
    NF, EF = len(nf), len(ef)
    ntypes, etypes = meta["node_types"][0], meta["edge_types"][0]
    N = len(nodes) // NF
    ntype = nodes[nf.index("type")::NF].astype(np.int8)
    nname = nodes[nf.index("name")::NF].astype(np.int64)
    size = nodes[nf.index("self_size")::NF].astype(np.float64)
    ecount = nodes[nf.index("edge_count")::NF].astype(np.int64)
    del nodes
    etype = edges[ef.index("type")::EF].astype(np.int8)
    ename = edges[ef.index("name_or_index")::EF].astype(np.int64)
    eto = (edges[ef.index("to_node")::EF] // NF).astype(np.int32)
    del edges
    E = len(eto)
    first = np.zeros(N + 1, np.int64)
    np.cumsum(ecount, out=first[1:])
    isweak = etype == etypes.index("weak")
    visited = np.zeros(N, bool)
    visited[0] = True
    pred = np.full(N, -1, np.int64)
    depth = np.full(N, -1, np.int32)
    depth[0] = 0
    levels = [np.array([0], np.int64)]
    frontier = levels[0]
    d = 0
    while frontier.size:
        cnt_f = ecount[frontier]
        tot = int(cnt_f.sum())
        if not tot:
            break
        off = np.repeat(first[frontier] - (np.cumsum(cnt_f) - cnt_f), cnt_f)
        eidx = np.arange(tot, dtype=np.int64) + off
        par = np.repeat(frontier, cnt_f)
        tgt = eto[eidx].astype(np.int64)
        m = ~isweak[eidx] & ~visited[tgt]
        tgt, par = tgt[m], par[m]
        u, fi = np.unique(tgt, return_index=True)
        d += 1
        visited[u] = True
        pred[u] = par[fi]
        depth[u] = d
        levels.append(u)
        frontier = u
        del eidx, off, par, tgt, m
    ret = np.where(depth >= 0, size, 0.0)
    for idx in reversed(levels[1:]):
        np.add.at(ret, pred[idx], ret[idx])
    loc = {}
    for i in range(0, len(locs), 4):
        loc[int(locs[i]) // NF] = (int(locs[i + 1]), int(locs[i + 2]) + 1)

    def label(i):
        t = ntypes[ntype[i]]
        nm = strings[nname[i]] if t not in ("number",) else str(nname[i])
        nm = nm.replace("\n", " ")[:70]
        extra = f" @script{loc[i][0]}:{loc[i][1]}" if i in loc else ""
        return f"{t}:{nm}{extra}"

    def edge_to(parent, child):
        for e in range(first[parent], first[parent + 1]):
            if eto[e] == child:
                t = etypes[etype[e]]
                return f"[{ename[e]}]" if t in ("element", "hidden") else f".{strings[ename[e]]}"
        return "?"

    def path_of(i, hops=10):
        out = []
        while i > 0 and len(out) < hops:
            p = pred[i]
            out.append(f"{edge_to(p, i)} -> {label(i)}")
            i = p
        return " <- ".join(out)

    reached = depth >= 0
    print(f"# {path}\nnodes={N} edges={E} self total={size.sum()/MB:.0f}MB reached={size[reached].sum()/MB:.0f}MB")
    print("\n## self size by node type")
    for t in range(len(ntypes)):
        s = size[ntype == t].sum()
        if s > MB:
            print(f"{s/MB:9.1f}MB  {ntypes[t]}  n={(ntype == t).sum()}")
    # per (type, name) aggregate
    key = ntype.astype(np.int64) * (1 << 40) + nname
    isstr = np.isin(ntype, [ntypes.index(x) for x in ("string", "concatenated string", "sliced string") if x in ntypes])
    key = np.where(isstr | (ntype == ntypes.index("number")), ntype.astype(np.int64) * (1 << 40), key)
    uk, inv = np.unique(key, return_inverse=True)
    agg = np.bincount(inv, weights=size)
    cnt = np.bincount(inv)
    top = np.argsort(-agg)[:50]
    print("\n## top 50 self size by (type, constructor/name); strings lumped")
    totals = {}
    for j in np.argsort(-agg)[:2000]:
        t = int(uk[j] >> 40)
        nm = "*" if ntypes[t] in STRLIKE else strings[int(uk[j] & ((1 << 40) - 1))][:70]
        totals[f"{ntypes[t]}:{nm}"] = [float(agg[j] / MB), int(cnt[j])]
        if j in top:
            print(f"{agg[j]/MB:9.1f}MB  n={cnt[j]:<9} {ntypes[t]}:{nm}")
    print("\n## retained tree (BFS tree; children >= 15MB, max 10 per node)")
    cidx = np.argsort(pred, kind="stable")
    ps = pred[cidx]

    def children(i):
        lo, hi = np.searchsorted(ps, i), np.searchsorted(ps, i, side="right")
        c = cidx[lo:hi]
        return c[np.argsort(-ret[c])]

    def walk(i, ind):
        if ind > 30:
            return
        for c in children(i)[:10]:
            if ret[c] < 15 * MB:
                break
            print(f"{'  ' * ind}{ret[c]/MB:8.1f}MB {edge_to(i, c)} {label(c)}  (self {size[c]/MB:.1f}MB)")
            walk(c, ind + 1)
    walk(0, 0)
    print("\n## 20 biggest strings, with path to root")
    sidx = np.where(isstr)[0]
    for i in sidx[np.argsort(-size[sidx])][:20]:
        s = strings[nname[i]][:90].replace("\n", " ")
        print(f"{size[i]/MB:8.2f}MB {ntypes[ntype[i]]} {s!r}\n      {path_of(i)}")
    print("\n## string size by first 40 chars (top 25)")
    pre = {}
    for i in sidx[size[sidx] > 4096]:
        k = strings[nname[i]][:40].replace("\n", " ")
        a = pre.setdefault(k, [0.0, 0])
        a[0] += size[i]
        a[1] += 1
    for k, (s, c) in sorted(pre.items(), key=lambda kv: -kv[1][0])[:25]:
        print(f"{s/MB:8.1f}MB n={c:<6} {k!r}")
    print("\n## top 25 closures by retained, with path")
    clo = np.where(ntype == ntypes.index("closure"))[0]
    for i in clo[np.argsort(-ret[clo])][:25]:
        print(f"{ret[i]/MB:8.1f}MB {label(i)}\n      {path_of(i, 6)}")
    with open(out, "w") as f:
        json.dump(totals, f)


def diff(a, b):
    with open(a) as fa, open(b) as fb:
        A, B = json.load(fa), json.load(fb)
    rows = [(B.get(k, [0, 0])[0] - A.get(k, [0, 0])[0], k) for k in set(A) | set(B)]
    print(f"# growth {a} -> {b}")
    for d, k in sorted(rows, reverse=True)[:40]:
        print(f"{d:+9.1f}MB  {k}  ({A.get(k, [0, 0])[1]} -> {B.get(k, [0, 0])[1]} objects)")


if __name__ == "__main__":
    if sys.argv[1] == "--diff":
        diff(sys.argv[2], sys.argv[3])
    else:
        main(sys.argv[1], sys.argv[2])
