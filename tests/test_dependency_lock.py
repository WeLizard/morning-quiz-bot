"""Keep the checked-in dev/test lock aligned with its direct requirements."""
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]


def requirements(path):
    result = {}
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.partition('#')[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        versions = list(requirement.specifier)
        assert len(versions) == 1 and versions[0].operator == '==', (
            f'{path.name} must pin direct dependency {requirement.name}'
        )
        result[canonicalize_name(requirement.name)] = versions[0].version
    return result


def test_local_lock_matches_every_direct_test_dependency_and_has_hashes():
    source = requirements(ROOT / 'requirements-local-test.txt')
    lock_path = ROOT / 'requirements-local-lock.txt'
    lock_lines = lock_path.read_text(encoding='utf-8').splitlines()
    lock = {}
    current = None
    for line in lock_lines:
        if line and not line[0].isspace() and not line.startswith('#'):
            current = Requirement(line.rstrip(' \\'))
            lock[canonicalize_name(current.name)] = current
        elif current is not None and line.strip().startswith('# via'):
            current = None
    assert all(name in lock and str(lock[name].specifier) == f'=={version}'
               for name, version in source.items())
    for index, line in enumerate(lock_lines):
        if line and not line[0].isspace() and not line.startswith('#'):
            block = []
            for next_line in lock_lines[index:]:
                if next_line.strip().startswith('# via'):
                    break
                block.append(next_line)
            assert any('--hash=sha256:' in item for item in block), line
