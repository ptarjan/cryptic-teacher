"""Failing puzzles in scratch/validate_out.txt; with --base, whether each also fails at HEAD."""
import re, subprocess, sys, shutil
cur, bad = None, []
for line in open("scratch/validate_out.txt"):
    m = re.match(r"^(\S+-\d+) ", line)
    if m:
        cur = m.group(1)
    elif "ERROR" in line and cur and cur not in bad:
        bad.append(cur)
bad = [l.split(":")[0].split(" ")[0] for l in open("scratch/validate_out.txt") if "— FAIL" in l]
print(bad)
if "--base" in sys.argv:
    for pid in bad:
        path = subprocess.run([sys.executable, "-c", f"import sys;sys.path.insert(0,'tools');from puzzle_paths import resolve_puzzle;print(resolve_puzzle('{pid}'))"],
                              capture_output=True, text=True).stdout.strip()
        shutil.copy(path, "/tmp/mine.json")
        subprocess.run(["git", "checkout", "--", path], check=True)
        base = subprocess.run([sys.executable, "tools/validate_annotations.py", pid], capture_output=True, text=True)
        shutil.copy("/tmp/mine.json", path)
        mine = subprocess.run([sys.executable, "tools/validate_annotations.py", pid], capture_output=True, text=True)
        be = [l for l in base.stdout.splitlines() if "ERROR" in l]
        me = [l for l in mine.stdout.splitlines() if "ERROR" in l]
        new = [l for l in me if l not in be]
        print(pid, "base-fails" if be else "base-ok", "NEW:" if new else "", *[n[:300] for n in new], sep="\n  ")
        if new:
            for l in mine.stdout.splitlines():
                if "warn" in l and any(k in l for k in ("move", "role", "trade", "shared", "inside its leaf", "block note")):
                    print("   >", l[:400])
