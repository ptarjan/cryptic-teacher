#!/usr/bin/env python3
# Does the OCR queue's human log say, line by line, what each unit did, in plain words?
#
#     python3 tests/test_ocr_log.py
#
# Raw queue lines in, human lines out (tools/ocr_log.py); noise out.
import datetime
import os
import subprocess
import sys
import tempfile

HOME = tempfile.mkdtemp(prefix="ocr_log_home_")   # a fake HOME: nothing here may read the real one
os.environ["HOME"] = HOME
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _path  # puts tools/ on sys.path
import ocr_log as O

fails = 0
def check(got, want, what):
    global fails
    ok = got == want
    print(f"  {'ok' if ok else 'FAIL'}: {what}" + ("" if ok else f"\n    got {got!r}, wanted {want!r}"))
    fails += not ok

DAY = datetime.date(2026, 10, 30)
def run(lines, repo=None, flush=True):
    log = O.Log(repo, day=DAY)
    out = []
    for line in lines:
        out += log.feed(line)
    return out + (log.flush() if flush else [])
def bare(lines):  # without the HH:MM stamp
    return [x.split(" ", 1)[1] for x in lines]

UNIT = "GaleTimes1947UKEnglish/1947-05-10"
check(bare(run([f"09:41:02 read {UNIT}: 5355 wrote times-5355 (vlm 11 cached)"])),
      ["✓ Times 1947-05-10: puzzle No 5355 filed"], "a filed puzzle is one line with its paper, date and number")
check(run([f"09:41:02 read {UNIT}: 5355 wrote times-5355 (vlm 0)"])[0][:5], "09:41", "every line starts with the clock")
check(bare(run([f"09:41:02 read {UNIT}: 5355 wrote times-5355 (vlm 0)",
                f"read {UNIT}: 5355 wrote times-5355 (vlm 0)"])),
      ["✓ Times 1947-05-10: puzzle No 5355 filed"], "the same result printed twice is one line")
check(bare(run([f"09:41:02 read {UNIT}: 5324 wrote times-5324 (incomplete: 4 blank, unfiled) (vlm 8 cached)"])),
      ["✗ Times 1947-05-10: No 5324 read, but 4 answers are still blank, so it was not filed (still missing)"],
      "an incomplete read says what was lost")
check(bare(run(["09:41:02 read FinancialTimes1987UKEnglish/1987-01-31_30148: 6241 wrote ftcryptic-6241 (vlm 5 cached)"])),
      ["✓ Financial Times 1987-01-31: puzzle No 6241 filed"], "an archive edition is named by paper and date")

# repeats collapse into one line with a count
busy = [f"09:50:{i:02d} read GaleTimes2006UKEnglish/2006-06-{i + 1:02d}: deferred: VLM spool full" for i in range(14)]
check(bare(run(busy)), ["✗ 14 pages: image reader busy, each page waits its turn (nothing lost)"],
      "fourteen busy pages in a minute are one line")
check(bare(run(busy[:1])), ["✗ Times 2006-06-01: image reader busy, page waits its turn (nothing lost)"],
      "a single busy page is named")
check(bare(run([f"09:50:01 read {UNIT}: deferred, 3 VLM asks spooled"])),
      ["✗ Times 1947-05-10: partly read, 3 questions sent to the image reader, it finishes when the reader answers (nothing lost)"],
      "asks to the image reader are questions")
two_minutes = run(["09:50:01 read GaleTimes2006UKEnglish/2006-06-01: deferred: VLM spool full",
                   "09:51:01 read GaleTimes2006UKEnglish/2006-06-02: deferred: VLM spool full"])
check(len(two_minutes), 2, "a new minute is a new line")

# refusals say what is missing, in plain words
check(bare(run([f"09:41:02 read {UNIT}: 5455 no reading parses"])),
      ["✗ Times 1947-05-10: none of its clues could be read, so it was not filed (still missing)"], "no reading parses")
check(bare(run([f"09:41:02 read {UNIT}: 5456 No 5456 is not near the 5174 the date 1947-05-10 implies: t (vlm 0)"])),
      ["✗ Times 1947-05-10: its number does not fit its date, so it was not filed (still missing)"], "number off its date")
check(bare(run([f"09:41:02 read {UNIT}: 5456 crashed: ONNXRuntimeError: Traceback (most recent call last)"])),
      ["✗ Times 1947-05-10: the reader crashed on it, so it was not filed (still missing) (it will be tried again)"],
      "a crash will be tried again")
check(bare(run([f"09:41:02 read {UNIT}: 18969 already held: the reading votes in cross_validate.py (vlm 0)"])),
      ["✓ Times 1947-05-10: puzzle already on file, nothing new"], "already held is nothing new")
check(bare(run([f"09:41:02 read {UNIT}: 20229 wrote times-20229; 3450 No 3450 is not near the 20227 the date x implies: t"])),
      ["✓ Times 1947-05-10: puzzle No 20229 filed",
       "✗ Times 1947-05-10: its number does not fit its date, so it was not filed (still missing)"],
      "two puzzles on a page get one line each")
check(bare(run(["09:41:02 failed GaleTimes2005UKEnglish/2005-12-29: NameError: name 'fa' is not defined"])),
      ["✗ Times 2005-12-29: the program hit an error (NameError), page will be tried again (nothing lost)"],
      "a program error is named by its type and loses nothing")
check(bare(run(["09:41:02 end scan GaleTimes1985UKEnglish/1985-05-16: failed (rc=1) in 4s"])),
      ["✗ Times 1985-05-16: stopped unexpectedly, will be tried again (nothing lost)"], "a failed unit will be tried again")
check(bare(run(["09:41:02 scanned GaleTimes1945UKEnglish/1945-02-06: 1 puzzle(s)"])),
      ["✓ Times 1945-02-06 checked, 1 puzzle found on it"], "a scanned page")
check(bare(run(["09:41:02 answers-only cpu 1982-01-21 No 15735: 127.3s taken; {}; unit 141.4s"])),
      ["✓ Times 1982-01-21 No 15735 re-checked"], "the answers-only run is a re-check")
check(bare(run(["GALE_GM2500075819.pdf: No 366 (PDF citation title), 27/35 clues read"] , flush=True)), [],
      "a line with no clock before any stamp says nothing")
check(bare(run(["09:41:02 vlm stage: 3 asks spooled, 5 reads waiting",
                "09:41:03 GALE_GM2500075819.pdf: No 366 (PDF citation title), 27/35 clues read"])),
      ["✗ Gale file 075819 (No 366): only 27 of 35 clues could be read, the rest are missing"], "a partly read pdf")

# noise says nothing, and no internal names reach the log
noise = ["vlm_reader: no ask for column 0: lines with no clue count or number, the page's prose",
         "09:41:02 unit ceiling: 10 unit children running; no read or scan starts until one exits",
         "09:41:02 whole read GaleTimes1945UKEnglish/1945-11-30: no desktop (OCR_REMOTE unset)",
         "09:41:02 vlm feed: start read gale GaleTimes1977UKEnglish/1977-05-27 (never read; 0 asks spooled, target 4)",
         "Traceback (most recent call last):", "  File \"x.py\", line 3, in <module>", "     1  refused: crashed",
         "09:41:03 push_puzzle_commit: batched 1 commit(s); pushing in 281s"]
check(run(noise), [], "noise is not here")
text = " ".join(run(busy + [f"09:51:02 read {UNIT}: deferred, 3 VLM asks spooled",
                           "09:51:03 answers-only cpu 1982-01-21 No 15735: 1s",
                           f"09:51:04 read {UNIT}: 5455 no reading parses"])).lower()
check([w for w in ("vlm", "spool", "answers-only", "cross_validate", "reason") if w in text], [],
      "no internal names in the words")

# the status line: units at once, filed/h, asks per 10 minutes, reads queued, a game, idle
log = O.Log(None, day=DAY)
out = []
for line in ["09:00:00 start read GaleTimes1947UKEnglish/1947-05-10 (never read)",
             "09:00:01 start scan GaleTimes1947UKEnglish/1947-05-11 (never scanned)",
             "09:00:02 vlm stage: 3 asks spooled, 5 reads waiting",
             "09:00:03 read GaleTimes1947UKEnglish/1947-05-10: deferred, 4 VLM asks spooled",
             "09:00:04 read GaleTimes1947UKEnglish/1947-05-12: 5357 wrote times-5357 (vlm 0)",
             "09:04:00 scanned GaleTimes1947UKEnglish/1947-05-11: 0 puzzle(s)"]:
    out += log.feed(line)
check([x for x in out if "units at once" in x], [], "no status in the first five minutes")
out = log.feed("09:05:10 scanned GaleTimes1947UKEnglish/1947-05-13: 0 puzzle(s)")
check(bare([x for x in out if "at once" in x]),
      ["── 2 units at once · 1 Times filed/h · – puzzles updated/h · 4 image-reader asks/10 min · 5 reads queued"],
      "five minutes on: the status line")
check([x for x in log.feed("09:07:00 scanned GaleTimes1947UKEnglish/1947-05-14: 0 puzzle(s)") if "at once" in x], [],
      "and the next one waits five minutes")
out = log.feed("09:10:19 end scan GaleTimes1947UKEnglish/1947-05-11: done in 67s")
check(bare([x for x in out if "at once" in x]),
      ["── 1 unit at once · 1 Times filed/h · – puzzles updated/h · 0 image-reader asks/10 min · 5 reads queued"],
      "five minutes on: one unit left, the old asks aged out")
out = log.feed("09:10:30 desktop [551]: yielding: game: playing Wow; desktop OCR and VLM wait until it is idle")
check(bare(out), ["── paused: a game is running, image work waits until it ends"], "a game pause is said once")
check(log.feed("09:10:31 desktop-bound: desktop yielding (game: playing Wow); only fetches start until it is idle"), [],
      "and not again")
out = log.feed("09:16:00 vlm stage: 0 asks spooled, 0 reads waiting")
check(bare(out)[0].endswith("0 reads queued · paused for a game"), True, "the status says paused for a game")
check(bare(log.feed("09:20:00 desktop [551]: resuming: idle (3D 0%, no game or video)"))[0],
      "── resumed: the game is over, image work goes on", "a game ending is said")
log.running.clear()
out = log.feed("09:30:00 planned: 1 scans, 1 reads, 0 fetches due in 2s; running 0")
check(bare(out)[0].endswith("0 reads queued · idle"), True, "nothing running for five minutes is idle")

# reload lines
check(bare(run(["09:41:02 code changed (edition_queue.py); re-exec, 12 running unit(s) kept"])),
      ["── queue restarting on new code, 12 units carried on"], "a reload says how many units go on")
check(bare(run(["09:41:02 reload: origin/master changed tools/wordplay.py; no unit starts, 12 running are handed to the next run"])),
      ["── queue reloading on new code, 12 units handed on"], "a handed-over reload")

# filed/h and updated/h come from the repo's commit history
repo = os.path.join(HOME, "repo")
os.makedirs(repo)
env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.com")
def git(*args, when=None):
    e = dict(env, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when) if when else env
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=e)
def local_iso(h, m):   # the log's clock is local time, so give git the same moment with an explicit offset
    return datetime.datetime(2026, 10, 30, h, m).astimezone().isoformat()
git("init", "-q")
git("config", "commit.gpgsign", "false")
for i, subject in enumerate(["File times-5355", "File times-5356", "Update 3 puzzles", "Update 4 puzzles", "Something else"]):
    git("commit", "-q", "--allow-empty", "-m", subject, when=local_iso(8, 20 + i))
git("commit", "-q", "--allow-empty", "-m", "File times-1", when=local_iso(6, 0))   # outside the hour
log = O.Log(repo, day=DAY)
log.feed("09:00:00 vlm stage: 0 asks spooled, 2 reads waiting")
check(log.git_counts(log.t), (2, 7), "two filed commits and 3+4 puzzles updated in the last hour")
check(log.feed("09:05:01 vlm stage: 0 asks spooled, 2 reads waiting")[0].split(" · ")[1:3],
      ["2 Times filed/h", "7 puzzles updated/h"], "the status line reads them")
check(O.Log(os.path.join(HOME, "nowhere"), day=DAY).git_counts(1_800_000_000), None, "a missing repo is unknown, not zero")
git("commit", "-q", "--allow-empty", "-m", "Update times-727", when=local_iso(8, 30))
log = O.Log(repo, day=DAY)
log.feed("09:00:00 vlm stage: 0 asks spooled, 2 reads waiting")
check(log.git_counts(log.t), (2, 8), "a single 'Update times-N' commit in the hour adds 1 puzzle updated")

# live, the ask count is the image reader's own call log (UTC clock), not the queue's "N asks spooled"
asks_path = os.path.join(HOME, "vlm_asks.log")
log = O.Log(None, day=DAY, ask_log=asks_path)
log.feed("09:00:00 vlm stage: 0 asks spooled, 2 reads waiting", 1000.0)
utc = lambda secs_ago: datetime.datetime.fromtimestamp(log.t - secs_ago, datetime.timezone.utc).strftime("%H:%M:%S")
with open(asks_path, "w") as fh:
    for ago in (700, 590, 300, 90, 3):
        fh.write(f"{utc(ago)} vlm ask gale/GaleTimes1932UKEnglish/1932-02-18 pick 358b451a27e9 why=pick:1a(blank)\n")
    fh.write(f"{utc(300)} vlm something else\n")
log.feed("09:00:01 read GaleTimes1947UKEnglish/1947-05-10: deferred, 7 VLM asks spooled", 1001.0)
check(log.ask_count(), 4, "four asks in the last ten minutes (an older one aged out, other lines are not asks)")
log.feed("09:04:00 vlm stage: 0 asks spooled, 2 reads waiting", 1240.0)
out = log.feed("09:05:10 vlm stage: 0 asks spooled, 2 reads waiting", 1310.0)
check([x for x in out if "at once" in x][0].split(" · ")[3], "2 image-reader asks/10 min",
      "the status line counts the reader's real calls, not the 7 spooled on one read")
check(O.Log(None, day=DAY, ask_log=os.path.join(HOME, "no_asks.log")).ask_count(), 0, "a missing call log counts none")

# a day change moves the clock on
log = O.Log(None, day=DAY)
log.feed("23:59:30 start read x (never read)")
t = log.t
log.feed("00:00:10 start read y (never read)")
check(round(log.t - t), 40, "midnight does not send the clock back")

# replay rebuilds the readable log from the raw one, and a follow's seed matches it
raw = os.path.join(HOME, "full_pass.log")
with open(raw, "w") as fh:
    fh.write("=== slice from 2026-10-30 09:40:00 ===\n")
    fh.write("vlm_reader: no ask for column 0: lines with no clue count or number, the page's prose\n")
    fh.write(f"09:41:02 read {UNIT}: 5355 wrote times-5355 (vlm 0)\n")
    fh.write("09:41:03 unit ceiling: 10 unit children running; no read or scan starts until one exits\n")
    fh.write("09:46:03 vlm stage: 0 asks spooled, 7 reads waiting\n")
replayed = os.path.join(HOME, "readable.log")
check(O.replay(raw, replayed), 0, "replay finishes")
with open(replayed) as fh:
    lines = fh.read().splitlines()
check(len(lines), 3, "a header, the filed line and the five-minute status")
check(lines[1].split(" ", 1)[1], "✓ Times 1947-05-10: puzzle No 5355 filed", "the replay has the filed line")
check(lines[2].split(" ", 1)[1].endswith("7 reads queued · idle"), True, "and the status")
check(os.path.exists(replayed + ".tmp"), False, "no half-written file is left")

# the module holds no absolute machine path and no lint-silencing comment
src = open("tools/ocr_log.py").read()
check([p for p in ("/" + "home/", "/" + "data/", "/" + "Users/", "/" + "Volumes/") if p in src], [],
      "no machine path in the tool")
check("no" + "qa" in src, False, "no lint-silencing comment in the tool")

print("FAIL" if fails else "all ok")
sys.exit(1 if fails else 0)
