"""Verify Alchemy's committed single-file artifacts are reproducible from source."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'minigames' / 'alchemia-1.0'
ARTIFACTS = ('art.svg', 'index.html', 'CONTENT_REPORT.json')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check():
    with tempfile.TemporaryDirectory(prefix='mqb-alchemy-build-') as temporary:
        copy = Path(temporary) / 'alchemia-1.0'
        shutil.copytree(SOURCE, copy)
        subprocess.run([sys.executable, str(copy / 'build.py')], check=True,
                       cwd=copy, timeout=120)
        mismatches = [name for name in ARTIFACTS
                      if digest(copy / name) != digest(SOURCE / name)]
    if mismatches:
        raise SystemExit('Alchemy artifacts differ from a clean build: ' + ', '.join(mismatches))
    print('Alchemy artifacts match a clean deterministic build:', ', '.join(ARTIFACTS))


if __name__ == '__main__':
    check()
