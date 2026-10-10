#!/usr/bin/env python3
"""A cache key for the code a cached result depends on, and no more.

    key(module, roots)   # hash of the code `roots` (names in `module`) reach
    python3 tools/code_reach.py MODULE ROOT ...   # what they reach, each by its first user; the key

A result cached under a hash of a whole file goes stale on any edit to it,
so one changed helper made ~11k archive.org scans be made again. key()
hashes only the module-level definitions the roots reach, followed name by
name and across this repo's own modules:

  - a function, class or assignment reaches every name it uses; a name
    imported from another module of tools/ (`import ocr_clues`,
    `from trove_grid import read_grid`) reaches that module's definition,
    `ocr_clues.suspect` reaching `suspect` there;
  - a class reaches its own body but its methods only by name: a method is
    in when some reached code uses an attribute of its name (`.headings`),
    or it is a dunder (`__init__`), so an edit to a method nothing reached
    calls leaves the key alone. Matching by attribute name alone keeps in
    every method that might be called, never fewer.

Each definition is hashed as its syntax tree (ast.dump) with docstrings
dropped, so comments, docstrings and line moves change nothing; any change
to the code itself does. Modules outside tools/ (the standard library,
numpy, PIL) are not followed.

modules() and key() keep each answer in STORE under a hash of every
tools/*.py file's name and bytes, so a process started on code that was
read before (every unit of a queue between two tree moves) reads the files
but parses none of them.
"""
import ast
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
#: Where modules() and key() answers are kept: <tree hash>.json, one per
#: version of tools/; a file unused for PRUNE_DAYS is removed.
STORE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "cryptic-teacher" / "code_reach"
PRUNE_DAYS = 7
#: Modules not followed by default: the desktop transport (ocr_remote runs
#: the same code there) and its busy probe change how a result travels,
#: never what it is.
TRANSPORT = ("ocr_remote", "desktop_busy")


def _source(name):
    """tools/<name>.py's path, or None for a module from elsewhere."""
    path = TOOLS / f"{name}.py"
    return path if path.exists() else None


class _Module:
    def __init__(self, path, text=None):
        self.tree = ast.parse(text if text is not None else path.read_text(encoding="utf-8"))
        self.defs = {}     # name: [module-level node]
        self.methods = {}  # class name: {method name: node}
        self.imports = {}  # local name: (module name, attribute or None)
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.defs.setdefault(node.name, []).append(node)
                if isinstance(node, ast.ClassDef):
                    self.methods[node.name] = {n.name: n for n in node.body
                                               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                    for n in ast.walk(t):
                        if isinstance(n, ast.Name):
                            self.defs.setdefault(n.id, []).append(node)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.imports[(a.asname or a.name).split(".")[0]] = (a.name, None)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                for a in node.names:
                    self.imports[a.asname or a.name] = (node.module, a.name)


def _tree():
    """A hash of every tools/*.py file's name and bytes."""
    h = hashlib.sha1()
    for path in sorted(TOOLS.glob("*.py")):
        h.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def _kept(question, answer):
    """The answer to `question` (a JSON-able list) kept in STORE for this
    tree, else answer() kept there; it is kept only when the tree is the
    same after answer() read it as before."""
    tree = _tree()
    path, q = STORE / f"{tree}.json", json.dumps(question)
    try:
        kept = json.loads(path.read_text())
    except (OSError, ValueError):
        kept = {}
    if q in kept:
        try:
            os.utime(path)
        except OSError:
            pass
        return kept[q]
    out = answer()
    if _tree() != tree:
        return out
    kept[q] = out
    try:
        STORE.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=STORE, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(kept, f)
        os.replace(tmp, path)
        for old in STORE.iterdir():
            if old.stat().st_mtime < time.time() - PRUNE_DAYS * 86400:
                old.unlink(missing_ok=True)
    except OSError as e:
        print(f"code_reach: {path} not written: {e}", file=sys.stderr)
    return out


def modules(name):
    """Every tools/ module `name` may load: those it imports anywhere in its
    code (a function's lazy import too), and theirs, `name` among them."""
    return set(_kept(["modules", name], lambda: sorted(_modules(name))))


def _modules(name):
    seen, todo = set(), [name]
    while todo:
        m = todo.pop()
        path = _source(m)
        if m in seen or path is None:
            continue
        seen.add(m)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                todo += [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                todo.append(node.module.split(".")[0])
    return seen


def _stripped(node):
    """`node` as ast.dump, every docstring dropped."""
    node = ast.parse(ast.unparse(node)).body[0]
    for n in ast.walk(node):
        body = getattr(n, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            n.body = body[1:] or [ast.Pass()]
    return ast.dump(node)


def _class_shell(node):
    """A class without its methods: its bases, decorators and class body."""
    shell = ast.ClassDef(name=node.name, bases=node.bases, keywords=node.keywords, decorator_list=node.decorator_list,
                         body=[n for n in node.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                         or [ast.Pass()], type_params=getattr(node, "type_params", []))
    return ast.fix_missing_locations(shell)


def reach(module_name, roots, texts=None, why=None, opaque=TRANSPORT):
    """{(module, definition): its hashed form} of everything `roots` (names
    in tools/<module_name>.py) reach, the `opaque` modules' code left out
    (a transport that does not change what is computed). `texts` ({module:
    source}) stands in for files (tests); `why` ({}) gets each
    definition's first user."""
    texts = texts or {}
    mods = {}

    def mod(name):
        if name in opaque:
            return None
        if name not in mods:
            path = _source(name)
            mods[name] = (_Module(path, texts.get(name)) if path or name in texts else None)
        return mods[name]

    out, attrs, classes = {}, set(), set()
    todo = [(module_name, r, None) for r in roots]
    why = {} if why is None else why
    while todo:
        name, what, by = todo.pop()
        m = mod(name)
        if m is None:
            continue
        if what in m.imports and what not in m.defs:
            other, attr = m.imports[what]
            if attr is not None:
                todo.append((other, attr, by))
            continue
        nodes = m.defs.get(what)
        if not nodes or (name, what) in out:
            continue
        found = []
        for node in nodes:
            if isinstance(node, ast.ClassDef):
                classes.add((name, what))
                found.append(_class_shell(node))
            else:
                found.append(node)
        out[(name, what)] = "\n".join(_stripped(n) for n in found)
        why.setdefault((name, what), by)
        for node in found:
            todo += [(*u, (name, what)) for u in _uses(m, name, node, attrs)]
        # A method of a reached class is in once its name is used anywhere.
        for cname, cwhat in list(classes):
            for meth, node in mod(cname).methods[cwhat].items():
                key = (cname, f"{cwhat}.{meth}")
                if key not in out and (meth in attrs or (meth.startswith("__") and meth.endswith("__"))):
                    out[key] = _stripped(node)
                    why.setdefault(key, (cname, cwhat))
                    todo += [(*u, key) for u in _uses(mod(cname), cname, node, attrs)]
    return out


def _locals(node):
    """The names a function binds itself (its parameters, assignments, loop
    and `with` targets, nested definitions), which name no module-level
    definition inside it; none for anything but a function."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return set()
    out, glob = set(), set()
    for n in ast.walk(node):
        if isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not node:
            out.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            glob.update(n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
    return out - glob


def _uses(m, name, node, attrs):
    """The (module, name) pairs `node` uses; its attribute names go to `attrs`."""
    out = []
    local = _locals(node)
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            if n.id not in local:
                out.append((name, n.id))
        elif isinstance(n, ast.Attribute):
            attrs.add(n.attr)
            if isinstance(n.value, ast.Name) and n.value.id in m.imports and n.value.id not in m.defs:
                other, attr = m.imports[n.value.id]
                out.append((other, n.attr) if attr is None else (name, n.value.id))
    return out


def key(module, roots, texts=None, opaque=TRANSPORT):
    """A 16-hex-digit hash of the code `roots` reach from `module` (a module
    object or a tools/ module's name), past no `opaque` module."""
    name = module if isinstance(module, str) else Path(module.__file__).stem

    def answer():
        h = hashlib.sha256()
        for k, v in sorted(reach(name, roots, texts, opaque=opaque).items()):
            h.update(f"{k}\n{v}\n".encode())
        return h.hexdigest()[:16]
    return answer() if texts else _kept(["key", name, sorted(roots), sorted(opaque)], answer)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: code_reach.py MODULE ROOT [ROOT ...]   # the definitions the roots reach, and the key")
        sys.exit(2)
    why = {}
    for (m, d) in sorted(reach(sys.argv[1], sys.argv[2:], why=why)):
        chain, k = [], why.get((m, d))
        while k:
            chain.append(".".join(k))
            k = why.get(k)
        print(f"{m}.{d}" + (f"  <- {' <- '.join(chain)}" if chain else ""))
    print(key(sys.argv[1], sys.argv[2:]))
