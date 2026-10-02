#!/usr/bin/env python3
"""Fine-tune Tesseract's English LSTM on Times clue lines, for the archive.org filer.

    python3 tools/train_archive_org_tesseract.py lines      # render + crop training lines
    python3 tools/train_archive_org_tesseract.py lstmf      # Tesseract's training files for them
    python3 tools/train_archive_org_tesseract.py train --minutes 30
    python3 tools/train_archive_org_tesseract.py finish --to-int  # write MODEL

Training lines are of two kinds, both in WORK (default ~/.cache/archive_org_tess):
- synthetic: clues from puzzles/** (leaving out any puzzle that shares 3+
  clues with tools/data/archive_org_ocr_gold.json) set as the Times prints
  them ("12 Clue text (2,5).", wrapped, continuation lines indented) in
  Liberation Serif, then degraded the way the 200dpi scans are (shrunk to
  scan size, blurred, ink bleed, noise, JPEG, slight skew) and enlarged 2x as
  file_archive_org_puzzles.rapid_lines enlarges a crop before reading it;
- real: Tesseract's line boxes on the "tune" gold editions' clue columns,
  each line's text taken from the hand transcription (its clue number and
  count kept only where the read ones are well formed). "heldout" editions
  are never cropped.
Training starts from tessdata_best eng (a float model; the fast integer one
cannot be fine-tuned) and needs lstmtraining, which the conda-forge
tesseract package does not ship: build it from the tesseract sources with
BUILD_TRAINING_TOOLS=ON (LSTMTRAINING below).
"""
import argparse
import difflib
import glob
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

WORK = Path(os.path.expanduser("~/.cache/archive_org_tess"))
GOLD = TOOLS / "data" / "archive_org_ocr_gold.json"
BEST_URL = "https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata"
#: The integer model the filer reads with (file_archive_org_puzzles.TESS_MODELS).
MODEL = TOOLS / "data" / "archive_org_tess.traineddata"
LSTMTRAINING = Path(os.path.expanduser("~/.local/tesstrain/bin/lstmtraining"))
COMBINE = Path(os.path.expanduser("~/.local/tesstrain/bin/combine_tessdata"))
FONTS = {"/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf": 0.7,
         "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf": 0.3}
#: The clue column at 2x: ~690px of text, ~38px a line.
COLUMN = 690
COUNT = re.compile(r"^\(\d+(?:[,-]\d+)*\)[.?!]?$")
ASCII = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "..."})


def words(text):
    return re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower().replace("’", "'"))


def corpus_clues(root=ROOT, gold=GOLD):
    """[(clue text, enumeration)] from puzzles/**, gold-sharing puzzles left out."""
    held = {" ".join(words(t)) for ed in json.loads(gold.read_text())
            for t in ed["clues"].values() if t}
    out = []
    for path in glob.glob(str(root / "puzzles" / "*" / "*" / "*.json")):
        try:
            entries = json.loads(Path(path).read_text()).get("entries", ())
        except (OSError, ValueError):
            continue
        clues = [(e.get("clue") or {}) for e in entries]
        if sum(" ".join(words(c.get("text") or "")) in held for c in clues
               if len(words(c.get("text") or "")) > 2) >= 3:
            continue
        for c in clues:
            text, enum = (c.get("text") or "").translate(ASCII).strip(), c.get("enumeration") or ""
            enum = re.sub(r"\s", "", str(enum)).strip("()")
            if text and re.fullmatch(r"\d+(?:[,-]\d+)*", enum) and text.isascii() and len(text) < 120:
                out.append((text, enum))
    return out


def wrap(font, number, text, width, rng):
    """The printed lines of one clue: [(indent px, line text)]."""
    toks = text.split()
    lead = f"{number} "
    indent = font.getlength(f"{max(number, 10)} ")
    lines, cur = [], []
    for t in toks:
        if cur and font.getlength(" ".join(cur + [t])) > width - indent:
            lines.append(cur)
            cur = []
        cur.append(t)
    lines.append(cur)
    out = []
    for i, ws in enumerate(lines):
        if i == 0:
            out.append((indent - font.getlength(lead), lead + " ".join(ws), i < len(lines) - 1))
        else:
            out.append((indent, " ".join(ws), i < len(lines) - 1))
    return out


def render(font, indent, text, justify, width, rng):
    """A clean 2x line image (PIL "L"): justified lines spread their spaces."""
    from PIL import Image, ImageDraw
    asc, desc = font.getmetrics()
    h = asc + desc + rng.randint(4, 10)
    img = Image.new("L", (COLUMN + 60, h), 255)
    d = ImageDraw.Draw(img)
    x, y = 20 + indent, rng.randint(1, 4)
    toks = text.split(" ")
    gap = font.getlength(" ")
    if justify and len(toks) > 1:
        used = sum(font.getlength(t) for t in toks)
        gap = max(gap, min(gap * 4, (width - indent - used) / (len(toks) - 1)))
    for t in toks:
        d.text((x, y), t, font=font, fill=0)
        x += font.getlength(t) + gap
    return img.crop((0, 0, int(min(img.width, x + 20)), h))


def degrade(img, rng):
    """The scan's look: 200dpi, blurred, bled, noisy, JPEG'd, then 2x again."""
    import io
    import numpy as np
    from PIL import Image, ImageFilter
    for _ in range(rng.choices((0, 1, 2), (0.25, 0.6, 0.15))[0]):
        img = img.filter(ImageFilter.MinFilter(3))
    img = img.rotate(rng.uniform(-0.6, 0.6), resample=Image.BILINEAR, expand=True, fillcolor=255)
    small = img.resize((max(1, img.width // 2), max(1, img.height // 2)), Image.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(rng.uniform(0.2, 0.8)))
    a = np.asarray(small, dtype=np.float32)
    paper, ink = rng.uniform(200, 255), rng.uniform(0, 70)
    a = ink + (paper - ink) * (a / 255.0)
    a += np.random.default_rng(rng.randint(0, 1 << 30)).normal(0, rng.uniform(3, 14), a.shape)
    small = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=rng.randint(20, 60))
    small = Image.open(io.BytesIO(buf.getvalue())).convert("L")
    big = np.asarray(small.resize((small.width * 2, small.height * 2)), dtype=np.float32)
    # Many scans are near black-and-white: stretch the contrast about mid-grey.
    k = rng.choice((1.0, rng.uniform(1.5, 4.0)))
    big = 128 + (big - 128) * k
    return Image.fromarray(np.clip(big, 0, 255).astype(np.uint8))


def synthetic(n, out, seed=1):
    from PIL import ImageFont
    rng = random.Random(seed)
    clues = corpus_clues()
    rng.shuffle(clues)
    made = []
    for text, enum in clues:
        if len(made) >= n:
            break
        path = rng.choices(list(FONTS), weights=list(FONTS.values()))[0]
        font = ImageFont.truetype(path, rng.randint(33, 39))
        width = rng.randint(COLUMN - 80, COLUMN)
        number = rng.choice([rng.randint(1, 9), rng.randint(10, 30)])
        clue = f"{text} ({enum})."
        for indent, line, justify in wrap(font, number, clue, width, rng):
            img = degrade(render(font, indent, line, justify, width, rng), rng)
            base = out / f"syn{len(made):05d}"
            img.save(f"{base}.png")
            Path(f"{base}.gt.txt").write_text(line + "\n")
            made.append(base)
    return made


def tess_lines(crop):
    """[(box, text)] for each line Tesseract finds in a PIL image."""
    import tempfile

    import ocr_clues
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "c.png"
        crop.save(p)
        res = subprocess.run([ocr_clues.tesseract(), str(p), "-", "--psm", "4", "-l", "eng", "tsv"],
                             capture_output=True, text=True, timeout=300, check=True)
    lines = {}
    for row in res.stdout.splitlines()[1:]:
        f = row.split("\t")
        if len(f) == 12 and f[0] == "5" and f[11].strip():
            key = tuple(f[1:5])
            x, y, w, h = map(int, f[6:10])
            lines.setdefault(key, []).append((x, y, x + w, y + h, f[11].strip()))
    return [((min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws),
              max(w[3] for w in ws)), [w[4] for w in ws]) for ws in lines.values()]


def norm(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())


def real(out, split="tune"):
    """Line crops from the gold editions of `split`, texts from the transcription."""
    import file_archive_org_puzzles as fa
    import ocr_clues
    assert split == "tune", "held-out editions are never trained on"
    made = []
    for ed in json.loads(GOLD.read_text()):
        if ed["split"] != split:
            continue
        d = fa.CACHE / ed["edition"]
        hit = next((h for h in fa.scan(d)["puzzles"] if h["number"] == ed["number"]), None)
        if hit is None:
            continue
        img = fa.page(d, hit["leaf"])
        gx0, gy0, gx1, gy1 = fa.grid_box(img, hit["box"])
        gw = gx1 - gx0
        box = (max(0, gx0 - 40), gy1, min(img.width, gx1 + 30), min(img.height, int(gy1 + 1.8 * gw)))
        crop = img.crop(box).convert("RGB")
        crop = crop.resize((crop.width * ocr_clues.UPSCALE, crop.height * ocr_clues.UPSCALE)).convert("L")
        # The gold stream: clue number then clue words, across then down.
        gold = []
        for lid, text in ed["clues"].items():
            num = lid.split("-")[0]
            gold.append((num, "num"))
            gold += [(t, "word") for t in text.split()]
        lines = tess_lines(crop)
        flat = [(norm(t), li, t) for li, (_, ts) in enumerate(lines) for t in ts]
        sm = difflib.SequenceMatcher(None, [norm(g) for g, _ in gold], [f[0] for f in flat],
                                     autojunk=False)
        match = {}
        for a, b, size in sm.get_matching_blocks():
            for k in range(size):
                match[b + k] = a + k
        at = 0
        for li, ((x0, y0, x1, y1), toks) in enumerate(lines):
            idx = list(range(at, at + len(toks)))
            at += len(toks)
            body = [i for i in idx if not (i == idx[0] and toks[0].isdigit())
                    and not (i == idx[-1] and COUNT.match(toks[-1]))]
            got = [match[i] for i in body if i in match]
            if not body or len(got) < 0.75 * len(body) or len(got) < 2:
                continue
            lo, hi = min(got), max(got)
            span = gold[lo:hi + 1]
            if any(kind == "num" for _, kind in span) or hi - lo + 1 > len(body) + 1:
                continue
            text = " ".join(g for g, _ in span)
            if toks[0].isdigit() and lo > 0 and gold[lo - 1] == (toks[0], "num"):
                text = f"{toks[0]} {text}"
            elif toks[0].isdigit():
                continue
            if COUNT.match(toks[-1]):
                text = f"{text} {toks[-1]}"
            pad = 8
            line = crop.crop((max(0, x0 - pad), max(0, y0 - pad), x1 + pad, y1 + pad))
            base = out / f"real{len(made):04d}"
            line.save(f"{base}.png")
            Path(f"{base}.gt.txt").write_text(text.translate(ASCII) + "\n")
            made.append(base)
    return made


def box_file(base):
    """Tesseract's line-box file for a line image: every char spans the line."""
    from PIL import Image
    w, h = Image.open(f"{base}.png").size
    bbox = f"0 0 {w} {h} 0"
    line = Path(f"{base}.gt.txt").read_text().strip()
    rows = [f"{c} {bbox}" for c in line] + [f"\t {bbox}"]
    Path(f"{base}.box").write_text("\n".join(rows) + "\n")


def best_model(work=WORK):
    path = work / "tessdata" / "eng.traineddata"
    if not path.exists():
        import urllib.request
        path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(BEST_URL, headers={"User-Agent": "cryptic-teacher"})
        path.write_bytes(urllib.request.urlopen(req, timeout=300).read())
    configs = path.parent / "configs"
    configs.mkdir(exist_ok=True)
    import ocr_clues
    shipped = Path(ocr_clues.tesseract()).resolve().parent.parent / "share" / "tessdata" / "configs" / "lstm.train"
    (configs / "lstm.train").write_text(shipped.read_text())
    return path


def lines_cmd(args):
    out = WORK / "lines"
    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob("*"):
        p.unlink()
    syn = synthetic(args.synthetic, out)
    rl = real(out)
    print(f"{len(syn)} synthetic, {len(rl)} real lines")


def lstmf_one(base, tessdata):
    import ocr_clues
    if not Path(f"{base}.lstmf").exists():
        box_file(base)
        subprocess.run([ocr_clues.tesseract(), f"{base}.png", str(base), "--tessdata-dir", str(tessdata),
                        "-l", "eng", "--psm", "13", "lstm.train"], capture_output=True, timeout=120)
    return Path(f"{base}.lstmf").exists()


def lstmf_cmd(args):
    """Each line's .lstmf (skipping those made), then the train and eval lists."""
    from concurrent.futures import ThreadPoolExecutor
    tessdata = best_model().parent
    bases = sorted(Path(p[:-len(".gt.txt")]) for p in glob.glob(str(WORK / "lines" / "*.gt.txt")))
    with ThreadPoolExecutor(args.jobs) as pool:
        ok = [b for b, good in zip(bases, pool.map(lambda b: lstmf_one(b, tessdata), bases)) if good]
    rng = random.Random(2)
    syn_ok = [b for b in ok if b.name.startswith("syn")]
    real_ok = [b for b in ok if b.name.startswith("real")]
    rng.shuffle(syn_ok)
    rng.shuffle(real_ok)
    ev = syn_ok[:100] + real_ok[:10]
    train = syn_ok[100:] + real_ok[10:] * args.real_weight
    rng.shuffle(train)
    (WORK / "list.train").write_text("".join(f"{b}.lstmf\n" for b in train))
    (WORK / "list.eval").write_text("".join(f"{b}.lstmf\n" for b in ev))
    print(f"{len(bases)} lines, {len(ok)} lstmf; train {len(train)}, eval {len(ev)}")


def train_cmd(args):
    model = best_model()
    lstm = WORK / "eng.lstm"
    if not lstm.exists():
        subprocess.run([str(COMBINE), "-e", str(model), str(lstm)], check=True)
    (WORK / "out").mkdir(exist_ok=True)
    env = dict(os.environ, OMP_THREAD_LIMIT=str(args.threads), OMP_NUM_THREADS=str(args.threads))
    cmd = ["nice", "-n", "19", "timeout", str(int(args.minutes * 60)), str(LSTMTRAINING),
           "--continue_from", str(lstm), "--traineddata", str(model),
           "--model_output", str(WORK / "out" / "times"),
           "--train_listfile", str(WORK / "list.train"), "--eval_listfile", str(WORK / "list.eval"),
           "--max_iterations", str(args.iterations), "--learning_rate", str(args.learning_rate)]
    t = time.time()
    res = subprocess.run(cmd, env=env)
    print(f"lstmtraining exit {res.returncode} after {time.time() - t:.0f}s")


def finish_cmd(args):
    model = best_model()
    ck = WORK / "out" / "times_checkpoint"
    out = WORK / "times.traineddata"
    subprocess.run([str(LSTMTRAINING), "--stop_training", "--continue_from", str(ck),
                    "--traineddata", str(model), "--model_output", str(out)], check=True)
    if args.to_int:
        fast = MODEL
        subprocess.run([str(LSTMTRAINING), "--stop_training", "--convert_to_int", "--continue_from",
                        str(ck), "--traineddata", str(model), "--model_output", str(fast)], check=True)
    print(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lines")
    p.add_argument("--synthetic", type=int, default=1500)
    p = sub.add_parser("lstmf")
    p.add_argument("--jobs", type=int, default=2)
    p.add_argument("--real-weight", type=int, default=3)
    p = sub.add_parser("train")
    p.add_argument("--minutes", type=float, default=30)
    p.add_argument("--threads", type=int, default=2)
    p.add_argument("--iterations", type=int, default=100000)
    p.add_argument("--learning-rate", type=float, default=0.0001)
    p = sub.add_parser("finish")
    p.add_argument("--to-int", action="store_true")
    args = ap.parse_args(argv)
    {"lines": lines_cmd, "lstmf": lstmf_cmd, "train": train_cmd, "finish": finish_cmd}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
