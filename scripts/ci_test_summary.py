"""Turn a pytest JUnit report into public CI output: annotations and a job summary.

Run as the last step of the test job. Failed tests then show up in the check-run
annotations (readable through the public check-runs API) and in $GITHUB_STEP_SUMMARY,
so nobody needs access to the raw logs or artifacts to see what failed.
"""
import os
import re
import sys
from xml.etree import ElementTree

MAX_ANNOTATIONS = 10  # GitHub shows at most 10 error annotations per step.
LOCATION = re.compile(r'(?<![\w/.\-])((?:tests|scripts|[a-z_]+)/[\w./-]+\.py):(\d+)')


def escape(value, prop=False):
    value = str(value).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    return value.replace(':', '%3A').replace(',', '%2C') if prop else value


def failures(report):
    for case in ElementTree.parse(report).getroot().iter('testcase'):
        problem = next((child for child in case if child.tag in ('failure', 'error')), None)
        if problem is None:
            continue
        message = (problem.get('message') or problem.text or '').strip().splitlines()
        text = (problem.text or '').strip()
        found = LOCATION.findall(text) + LOCATION.findall(problem.get('message') or '')
        location = next(((f, n) for f, n in found if f.startswith('tests/')), found[0] if found else None)
        classname = case.get('classname') or ''
        dotted = classname or (case.get('name') or '')  # collection errors carry the module in `name`
        parts = dotted.split('.')
        cut = next((i for i, part in enumerate(parts) if part.startswith('test_')), len(parts) - 1)
        yield {
            'kind': problem.tag,
            'name': '::'.join(part for part in (classname, case.get('name')) if part),
            'file': '/'.join(parts[:cut + 1]) + '.py',
            'line': location[1] if location else '1',
            'message': (message[0] if message else '')[:300],
        }


def main(report):
    if not os.path.isfile(report):
        print(f'::warning::no JUnit report at {report}; pytest did not get as far as writing one')
        return 0
    failed = list(failures(report))
    for item in failed[:MAX_ANNOTATIONS]:
        print(f"::error file={escape(item['file'], True)},line={item['line']},"
              f"title={escape('FAILED ' + item['name'], True)}::{escape(item['message'])}")
    if failed:
        print(f'::error title=pytest::{len(failed)} test(s) failed or errored; '
              'the first annotations list them, the job summary has the full list')
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    lines = [f'### pytest: {len(failed)} failed or errored', ''] + [
        f"- `{item['name']}` ({item['kind']}) {item['message']}" for item in failed] if failed \
        else ['### pytest: no failed tests in the JUnit report']
    text = '\n'.join(lines) + '\n'
    if summary:
        with open(summary, 'a', encoding='utf-8') as handle:
            handle.write(text)
    else:
        print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else '.local/acceptance/tests.xml'))
