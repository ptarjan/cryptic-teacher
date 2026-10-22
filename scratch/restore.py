"""Restore the given puzzle files (or every changed one except those named with --keep) to HEAD."""
import subprocess, sys
keep = [a[len("--keep="):] for a in sys.argv[1:] if a.startswith("--keep=")]
only = [a for a in sys.argv[1:] if not a.startswith("--")]
names = only or subprocess.run(["git", "diff", "--name-only", "--", "puzzles"],
                               capture_output=True, text=True).stdout.split()
names = [n for n in names if not any(k in n for k in keep)]
for i in range(0, len(names), 200):
    subprocess.run(["git", "checkout", "--", *names[i:i + 200]], check=True)
print("restored", len(names))
