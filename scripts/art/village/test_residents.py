"""Approved resident SVG contract; renders only figures, never installs village art."""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import harness

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def test_resident_contract():
    expected = json.loads((HERE / 'residents-approved.json').read_text(encoding='utf-8'))
    out = ROOT / '.local/village-generator/resident-contract'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'probe.js').write_text(
        "import {residentSvgs} from '/shared/residents.js';"
        "export function render(){return residentSvgs();}", encoding='utf-8')
    previous = harness.GEN
    try:
        harness.GEN = out
        a = harness.run('probe.js', {}, mounts={'/shared/': HERE})
        b = harness.run('probe.js', {}, mounts={'/shared/': HERE})
    finally:
        harness.GEN = previous
    assert a == b, 'resident generation must be deterministic'
    assert set(a) == set(expected) and len(a) == 10
    assert 'Медведь Пух' not in a, 'Pooh remains its separately approved runtime figure'
    for name, svg in a.items():
        assert hashlib.sha256(svg.encode()).hexdigest() == expected[name], f'{name}: approved SVG changed'
        doc = ET.fromstring(svg)
        assert doc.attrib['viewBox'] == '-18 -50 36 54', name
        assert not doc.findall('.//{http://www.w3.org/2000/svg}image'), name
        assert not doc.findall('.//{http://www.w3.org/2000/svg}filter'), name
    (out / 'resident-figures.json').write_text(json.dumps(a, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


if __name__ == '__main__':
    test_resident_contract()
    print('ok: 10 approved SVGs, deterministic generation, viewBox, vector only')
