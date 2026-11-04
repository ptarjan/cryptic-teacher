"""_module_version hashes the whole import closure under tools/, so a fix in a
module reached only transitively moves the version (cycles are safe)."""
import _path  # puts tools/ on sys.path
import failed_inputs


def _version(tmp_path, monkeypatch, files):
    for name, body in files.items():
        (tmp_path / f"{name}.py").write_text(body)
    monkeypatch.setattr(failed_inputs, "TOOLS", tmp_path)
    failed_inputs._module_source.cache_clear()
    failed_inputs._module_version.cache_clear()
    try:
        return failed_inputs._module_version("a")
    finally:
        failed_inputs._module_source.cache_clear()
        failed_inputs._module_version.cache_clear()


def test_deep_change_moves_version(tmp_path, monkeypatch):
    base = {"a": "import b\n", "b": "import c\n", "c": "X = 1\n"}
    v1 = _version(tmp_path, monkeypatch, base)
    v2 = _version(tmp_path, monkeypatch, {**base, "c": "X = 2\n"})
    assert v1 != v2


def test_cycle_terminates(tmp_path, monkeypatch):
    files = {"a": "import b\n", "b": "import a\nimport os\n"}
    v1 = _version(tmp_path, monkeypatch, files)
    v2 = _version(tmp_path, monkeypatch, {**files, "b": "import a\nimport os\n# x\n"})
    assert v1 != v2


def test_unrelated_module_ignored(tmp_path, monkeypatch):
    files = {"a": "import b\n", "b": "", "z": "1\n"}
    v1 = _version(tmp_path, monkeypatch, files)
    assert v1 == _version(tmp_path, monkeypatch, {**files, "z": "2\n"})
