"""README/UI numbers must match eval/ files (scripts/readme_results.py --check)."""
import os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "readme_results.py")


def check(cwd):
    return subprocess.run([sys.executable, SCRIPT, "--check"], cwd=cwd, capture_output=True, text=True)


def test_readme_and_ui_match_eval_files():
    r = check(ROOT)
    assert r.returncode == 0, r.stdout + r.stderr


def test_check_catches_a_changed_number(tmp_path):
    shutil.copytree(os.path.join(ROOT, "eval"), tmp_path / "eval")
    (tmp_path / "web").mkdir(); shutil.copy(os.path.join(ROOT, "web", "index.html"), tmp_path / "web")
    readme = open(os.path.join(ROOT, "README.md")).read()
    assert "0.1369 (" in readme
    (tmp_path / "README.md").write_text(readme.replace("0.1369 (", "0.1500 (", 1))
    r = check(tmp_path)
    assert r.returncode == 1 and "out of date" in r.stdout
