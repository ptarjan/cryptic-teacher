# tools/data

What is committed here, and what is fetched.

## Committed

| file | what |
| --- | --- |
| `abbreviations.json` | Hand-built table of standard British-cryptic abbreviations (H = hard, R = river…). A starter set, meant to grow — see the `_comment` inside it. |
| `unclueable.json` | Words a setter rejected as answers, with the reason. `tools/grid_fill.py` vetoes them. |
| `sample_fill_11.json` | The worked 11x11 fill (see `tools/AUTHORING.md`). |

## Fetched, never committed

`bash tools/fetch_lexicon.sh` downloads about 26 MB of JavaScript and derives
the word list from it. All of it is gitignored.

| file | source | licence |
| --- | --- | --- |
| `lufz-en-lexicon.js`, `lufz-en-lexicon-stems.js` | [viresh-ratnakar/lufz](https://github.com/viresh-ratnakar/lufz) | MIT |
| `exet-lexicon.js` | [viresh-ratnakar/exet](https://github.com/viresh-ratnakar/exet) | MIT |
| `lexicon.tsv` | derived by `tools/build_lexicon.js` | derived from the above |
| `clueability.tsv` | derived by `tools/clueability.py --build` | derived from the above |

The Lufz lexicon is UKACD18 — J Ross Beresford's UK Advanced Cryptics
Dictionary, the classic British cryptic word list — cleaned up and augmented
with Wikipedia-derived importance ordering, CMUdict pronunciations and Porter2
stems. That combination (British vocabulary + a real score column + a clear
licence) is why it is used here rather than `/usr/share/dict/words`, which has
no scores and so cannot support a fairness floor at all.

The derived files are gitignored on purpose: they are reproducible in under a
minute, and a stale committed copy that disagreed with the scorer would be worse
than no copy. The filler rebuilds `clueability.tsv` automatically when its
`CACHE_VERSION` changes.
