# Free sources for the missing puzzles

Research of 2026-11-17, ranked by how many missing puzzles each source fills.
It names sources only; no fetcher was written. Scan sources (Gale, archive.org,
Trove) belong to #cryptic-desktop and appear here only as notes.

## The holes, measured

Measured as missing numbers between held neighbours in `puzzles/<series>/`
(gaps that span a year boundary are split between the two years). The
measuring script is `/tmp/mps/gaps.py`, not committed.

| Series | Hole | Missing | Source today |
|---|---|---:|---|
| telegraph | 2001-2008 (none held) | ~2,620 | none: Gale ends 2000, bigdave44 starts 2009 |
| ftcryptic | 2000-2009 | ~2,250 | Gale FTHA (to 2010), desktop |
| independent | 2004-2013 | ~2,000 | Gale INDA (to 2015), desktop |
| sundaytel | 2001-2008 | ~440 | none |
| sundaytimes | 2007-2014 | ~410 | none: Gale STHA ends 2006 |
| times | 2015-2016 | 109 (142 for 2015-2026) | Times feed, partly |
| mephisto | 2007-2016 | ~610 | none |
| timesjumbo | 1997-2016 | ~1,000 | Gale Jumbo solutions only |
| azed | 1975-2004 | ~1,600 | andlit slips, partial |

The 2015-2016 Times gap is mostly weekday runs of five (26095-26099,
26101-26105, 26131-26135, ...): whole weekly batches the feed walk missed.

## Ranked sources

### 1. Cryptonite dataset (Times + Telegraph clues, 2000-2020): ~3,065 puzzles

- **What it holds:** one row per clue: `publisher` (Times/Telegraph),
  `sub_publisher` (e.g. "The Times"), print `date` (epoch ms, UTC midnight),
  clue `number`, `orientation` (across/down), `clue`, `answer`, `enumeration`,
  `quick`. 523k clues. It has no grid and no puzzle number, and clue and
  answer text are **lowercased**.
- **Years:** Telegraph late 2001-2020 (weekdays and Sundays); Times 2000-2020,
  with Sunday Times.
- **Free/legal:** free download, no login. The Hugging Face card says
  **CC BY-NC 4.0**; the GitHub repo has no licence file. The authors scraped
  the papers' subscription sites for an EMNLP 2021 research benchmark, so the
  clue text is still the papers' copyright. Non-commercial use fits the
  card's licence; whether to republish it on the site is Paul's call.
- **Checked URL:** https://github.com/aviaefrat/cryptonite/raw/main/data/cryptonite-official-split.zip
  (19 MB, three jsonl files). Card:
  https://huggingface.co/datasets/aviaefrat/cryptonite
- **Spot check:** for held 2012 puzzles the answers match ours on the same
  date (telegraph-26756 30/30, 26758 32/32; sundaytel-2627 30/30; times-25055
  30/30). Some dates carry a second puzzle (a 51- or 87-answer date), so
  split on `sub_publisher` and clue numbers. 2015-05-11 (Times 26095, which
  we lack) is present.
- **Fill**, counted as Cryptonite dates with 20+ clues that we hold no
  puzzle for:

  | Gap | Dates |
  |---|---:|
  | Telegraph weekday 2001-2008 | 2,215 |
  | Sunday Telegraph 2001-2008 | 345 |
  | Sunday Times 2007-2014 | 395 |
  | Times 2015-2016 | 110 |
  | Telegraph 2009-2020 strays | 88 |
  | Times 2000-2014 (upper bound) | 290 |
  | Sunday Times 2001-2006 (upper bound) | 71 |

  The core total is **3,065**. The upper-bound rows may partly be date
  mismatches against our blog-dated files.
- **Filing:** clue numbers plus answers rebuild the grid (times_grids
  backsolve, 99.3% invertible from clue numbers per
  cryptic-grid-reconstruction). Puzzle numbers come from held neighbours by
  date, and case has to be restored (proper nouns). Where both exist, the
  Times feed or the National Post PDFs (below) give proper case.

### 2. The Times feed, wider id search (existing source): ~110 Times 2015-2016

- **What it holds:** feeds.thetimes.co.uk `data.json`: clues as printed
  (proper case), grid, answers.
- **Free/legal:** free; it is the paper's own web player feed, already used
  by tools/fetch_times_feed.py.
- **Checked:** https://feeds.thetimes.co.uk/puzzles/crossword/20150511/4497/data.json
  is "Times Cryptic No 26095". That is Quick id 4336 + 161, just past the
  walk's `WIDE = 150`, which is why the week was missed. The cache holds only
  the Quicks for 11-15 May 2015.
- **Fill:** likely most of the 109 numbers missing in 2015-2016, with better
  text than Cryptonite. It is a reach fix in fetch_times_feed.py
  (`--daily-missing 2015-01-01 2016-12-31` with a wider WIDE), not a new
  source. The feed also serves "Concise"; untested for Sunday Times, Jumbo or
  Mephisto from 2014 on, so worth probing a Sunday.

### 3. National Post Cryptic Crossword Forum (Telegraph reprints, 2009-2022): cross-check only

- **What it holds:** daily reviews of the Telegraph cryptic the National Post
  reprinted months late, headed "DT nnnnn", quoting clues, with links to PDF
  or JPG copies of the puzzle.
- **Free/legal:** free blog; quoted clues as review.
- **Checked:** https://natpostcryptic.blogspot.com/2015/11/wednesday-november-11-2015-dt-27818.html
- **Fill:** about 0 new: we already hold Telegraph 2009+. Useful to restore
  case in Cryptonite rows and to check the 88 Telegraph strays.

### 4. Ottawa Citizen Cryptic Crossword Forum (Sunday Times reprints, 2009-2014): partial clues

- **What it holds:** about 258 reviews headed "ST nnnn" (May 2009 - June
  2014), each quoting the clues it discusses (about 17 of 30) with answers.
- **Free/legal:** free blog.
- **Checked:** https://citizencryptic.blogspot.com/2012/10 (ST 4505)
- **Fill:** about 250 of the ~410 missing Sunday Times numbers, but only about
  55% of the clues each, so no puzzle files from it alone. Use it to restore
  case and cross-check Cryptonite's Sunday Times rows.

### 5. Gale, for #cryptic-desktop (scans; not ours to build)

Independent 2004-2013 (~2,000, INDA runs to 2015) and FT 2000-2009 (~2,250,
FTHA runs to 2010) are inside Gale's range and in the desktop's queue. No free
web source beats them. Telegraph (TGRH) and Sunday Times (STHA) stop at
2000 and 2006, so source 1 is the only route for those holes.

## Checked and empty (2026-11-17)

- Wayback `feeds.thetimes.co.uk/puzzles/crossword/2015-16`: a handful of 302s,
  no data.
- The Australian and New York Post are said to reprint the Times cryptic, but
  neither has a free archive; their CDX prefixes 503'd or were empty.
- Wayback `nationalpost.com` puzzle paths 2000-2009: empty. telegraph.co.uk
  `/crossword` 2001-2007: about 15 landing pages, no puzzles.
- anagrammer.com Telegraph pages are the General Knowledge puzzle, not the
  cryptic (and 403 to scripts).
- Mephisto 2007-2016, Times Jumbo, TLS: no free source beyond TftT. Lucian
  Poll's Goodreads blog covers only ~2019-2023 Jumbos.
- Datasets: eigenfoo/cryptics (georgeho) is already used; mdda/cryptic-wordplay
  is mostly FT clues. No Mephisto, Azed or Sunday-only dataset exists.
- The 2015 TftT posts for the missing Times numbers (e.g.
  timesforthetimes.co.uk/times-26097-middle-of-the-road) give answers and
  wordplay with no clue text, so they can only key a Cryptonite or feed
  puzzle.
