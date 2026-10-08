"""Read-only audit of question seed files and, optionally, a test PostgreSQL bank."""
import argparse
import asyncio
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from storage.question_bank import PostgresQuestionBank, QuestionBank, question_content_hash


def question_key(value):
    if not isinstance(value, dict) or not isinstance(value.get('question'), str):
        return ''
    text = unicodedata.normalize('NFKC', value['question']).casefold()
    return ' '.join(re.sub(r'[^\w]+', ' ', text).split())


def audit_category(name, values, source):
    errors, duplicate_groups = [], defaultdict(list)
    if not isinstance(values, list):
        return {'name': name, 'source': source, 'count': 0, 'invalid': 1,
                'duplicates': [], 'errors': [{'index': None, 'reason': 'category is not an array'}]}
    for index, value in enumerate(values, 1):
        if not QuestionBank.is_valid(value):
            try:
                from storage.question_bank import normalized
                normalized(value)
                reason = 'invalid question'
            except (ValueError, TypeError) as error:
                issues = error.errors(include_url=False, include_context=False) if hasattr(error, 'errors') else []
                reason = '; '.join(
                    f"{'.'.join(map(str, issue['loc']))}: {issue['msg']}" for issue in issues
                ) or str(error)
            errors.append({'index': index, 'reason': reason})
            continue
        strings = [value.get('question', ''), value.get('correct', ''),
                   value.get('explanation', ''), value.get('solution', '')]
        strings.extend(value.get('options', []))
        if any(unicodedata.category(char) == 'Cc' for text in strings
               if isinstance(text, str) for char in text):
            errors.append({'index': index, 'reason': 'forbidden control character'})
            continue
        key = question_key(value)
        if key:
            duplicate_groups[key].append(index)
    duplicates = [
        {
            'question': values[indexes[0] - 1].get('question', ''),
            'indexes': indexes,
            'variants': [
                {'index': index,
                 'correct': values[index - 1].get('correct', ''),
                 'explanation': values[index - 1].get('explanation', '')}
                for index in indexes
            ],
        }
        for indexes in duplicate_groups.values() if len(indexes) > 1
    ]
    return {'name': name, 'source': source, 'count': len(values),
            'invalid': len(errors), 'duplicates': duplicates, 'errors': errors}


def audit_seed(root):
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f'Question directory does not exist: {root}')
    paths = sorted(root.glob('*.json'))
    if not paths:
        raise FileNotFoundError(f'No question JSON files found in: {root}')
    result = []
    for path in paths:
        try:
            values = json.loads(path.read_text(encoding='utf-8-sig'))
            category = audit_category(path.stem, values, 'json')
            category['content_hash'] = question_content_hash(values) if isinstance(values, list) else None
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            category = {'name': path.stem, 'source': 'json', 'count': 0, 'invalid': 1,
                        'duplicates': [], 'errors': [{'index': None, 'reason': str(error)}],
                        'content_hash': None}
        result.append(category)
    return result


def validate_test_database_url(url):
    parsed = urlsplit(url)
    in_dev_container = os.getenv('MQB_DEV_CONTAINER') == '1' and Path('/.dockerenv').is_file()
    expected = ('postgres', 5432) if in_dev_container else ('127.0.0.1', 55433)
    if ((parsed.hostname, parsed.port) != expected or parsed.path != '/morning_quiz_test'
            or parsed.username != 'mqb_dev'):
        raise SystemExit('PostgreSQL audit is restricted to the disposable local morning_quiz_test database')
    return url


async def audit_postgres(url, seed):
    from storage.database import Database, DatabaseSettings, normalize_database_url

    database = Database(DatabaseSettings(url=normalize_database_url(validate_test_database_url(url))))
    try:
        bank = PostgresQuestionBank(database)
        db_categories = await bank.categories()
        seed_by_name = {item['name']: item for item in seed}
        result = []
        for meta in db_categories:
            category = await bank.read(meta['name'])
            report = audit_category(meta['name'], category['questions'], 'postgres')
            report['revision'] = category['revision']
            report['content_hash'] = category['version']
            seed_row = seed_by_name.get(meta['name'])
            report['seed_comparison'] = (
                'missing_from_seed' if seed_row is None else
                'match' if seed_row.get('content_hash') == category['version'] else 'differs'
            )
            result.append(report)
        for name, seed_row in seed_by_name.items():
            if name not in {item['name'] for item in db_categories}:
                result.append({'name': name, 'source': 'postgres', 'count': 0, 'invalid': 0,
                               'duplicates': [], 'errors': [], 'revision': None,
                               'content_hash': None, 'seed_comparison': 'missing_from_postgres'})
        return result
    finally:
        await database.dispose()


def render_markdown(report):
    lines = [
        '# Question bank audit', '',
        f"- Source directory: `{report['seed_directory']}`",
        f"- JSON categories / records: {report['json_categories']} / {report['json_records']}",
        f"- PostgreSQL checked: {'yes (read-only)' if report['postgres_checked'] else 'no'}",
        '', '## JSON seed', '',
        '| Category | Records | Invalid | Duplicate groups |', '|---|---:|---:|---:|',
    ]
    for item in report['json']:
        lines.append(f"| {item['name']} | {item['count']} | {item['invalid']} | {len(item['duplicates'])} |")
    if report['postgres_checked']:
        lines += ['', '## Test PostgreSQL', '',
                  '| Category | Records | Invalid | Duplicate groups | Seed comparison |',
                  '|---|---:|---:|---:|---|']
        for item in report['postgres']:
            lines.append(f"| {item['name']} | {item['count']} | {item['invalid']} | "
                         f"{len(item['duplicates'])} | {item.get('seed_comparison', '')} |")
    lines += ['', '## Findings', '']
    findings = 0
    for source in ('json', 'postgres'):
        for item in report.get(source, []):
            for error in item['errors']:
                findings += 1
                lines.append(f"- **{source} / {item['name']} #{error['index'] or '?'}**: {error['reason']}")
            for duplicate in item['duplicates']:
                findings += 1
                indexes = ', '.join(map(str, duplicate['indexes']))
                variants = '; '.join(
                    f"#{variant['index']} → {variant['correct']}"
                    + (f" ({variant['explanation']})" if variant['explanation'] else '')
                    for variant in duplicate.get('variants', [])
                )
                lines.append(f"- **{source} / {item['name']} #{indexes}**: duplicate prompt “{duplicate['question']}”"
                             + (f"; answer/explanation variants: {variants}" if variants else ''))
            comparison = item.get('seed_comparison')
            if comparison and comparison != 'match':
                findings += 1
                lines.append(f"- **{source} / {item['name']}**: seed comparison is `{comparison}`")
    if not findings:
        lines.append('No findings.')
    lines += ['', 'This report is diagnostic only. It does not edit or import question data.', '']
    return '\n'.join(lines)


async def run(args):
    seed = audit_seed(args.seed_directory)
    pg = []
    if args.postgres:
        url = os.environ.get('TEST_DATABASE_URL', '').strip()
        if not url:
            raise SystemExit('--postgres requires an explicit TEST_DATABASE_URL; DATABASE_URL is never used')
        validate_test_database_url(url)
        pg = await audit_postgres(url, seed)
    report = {
        'seed_directory': str(Path(args.seed_directory).resolve()),
        'json_categories': len(seed),
        'json_records': sum(item['count'] for item in seed),
        'postgres_checked': args.postgres,
        'json': seed,
        'postgres': pg,
    }
    markdown = render_markdown(report)
    for path, contents in (
        (args.json_output, json.dumps(report, ensure_ascii=False, indent=2) + '\n'),
        (args.markdown_output, markdown),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding='utf-8')
    errors = sum(item['invalid'] for item in seed + pg)
    mismatches = sum(item.get('seed_comparison') not in {None, 'match'} for item in pg)
    return 1 if errors or mismatches else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed-directory', type=Path, default=ROOT / 'data' / 'questions')
    parser.add_argument('--postgres', action='store_true', help='Read-only audit against TEST_DATABASE_URL')
    output = ROOT / '.local' / 'acceptance'
    parser.add_argument('--json-output', type=Path, default=output / 'question-bank-audit.json')
    parser.add_argument('--markdown-output', type=Path, default=output / 'question-bank-audit.md')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == '__main__':
    main()
