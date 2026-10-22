import subprocess, sys, re
names = subprocess.run(["git", "diff", "--name-only", "--", "puzzles"], capture_output=True, text=True).stdout.split()
ids = sorted({re.sub(r"\.json$", "", n.rsplit("/", 1)[-1]) for n in names if n.endswith(".json")})
print(len(ids), "puzzles", flush=True)
r = subprocess.run([sys.executable, "tools/validate_annotations.py", *ids], capture_output=True, text=True)
out = r.stdout + r.stderr
open("scratch/validate_out.txt", "w").write(out)
fails = [l for l in out.splitlines() if "ERROR" in l or re.search(r"— (?!OK)", l) and l[:1] not in " "]
print("exit", r.returncode)
for l in out.splitlines():
    if "ERROR" in l:
        print(l)
