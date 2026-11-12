"""Small browser contract check: approved roaming pose and unchanged construction crew.

Run: python scripts/art/village/test_pooh_roaming.py
Writes review SVGs only to .local/village-generator/pooh-contract.
"""
import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import harness

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
APPROVED_SHA256 = "680bf9f482ff79a45c6df1b55cd5bc5f1dbc19d1d84146ef1449a8c3c54e517f"


def test_pooh_roaming_contract():
    out = ROOT / ".local" / "village-generator" / "pooh-contract"
    out.mkdir(parents=True, exist_ok=True)
    (out / "probe.js").write_text(
        "import {crewSvgs,poohRoamingSvg} from '/shared/crew.js';"
        "export function render(){return {crew:crewSvgs(),roaming:poohRoamingSvg()};}", encoding="utf-8")
    original_gen = harness.GEN
    try:
        harness.GEN = out
        a = harness.run("probe.js", {}, mounts={"/shared/": HERE})
        b = harness.run("probe.js", {}, mounts={"/shared/": HERE})
    finally:
        harness.GEN = original_gen
    assert a == b, "figure generation is not deterministic"
    app = (ROOT / "qw_farm/static/app.js").read_text(encoding="utf-8")
    for name, svg in a["crew"].items():
        assert svg in app, f"construction {name} changed from installed VILLAGE_CREW"
    roaming = a["roaming"]
    assert hashlib.sha256(roaming.encode()).hexdigest() == APPROVED_SHA256, "approved pose changed"
    assert re.sub(r'<g class="roaming-arm">.*?</g>', '', roaming) == re.sub(
        r'<g class="bc-hammer">.*?</g>', '', a["crew"]["pooh"]), "body or palette changed"
    doc = ET.fromstring(roaming)
    assert doc.attrib["viewBox"] == "-18 -50 36 54"
    assert not doc.findall('.//{http://www.w3.org/2000/svg}image')
    arm = doc.find('.//{http://www.w3.org/2000/svg}g[@class="roaming-arm"]')
    assert arm is not None and len(arm) == 1, "empty paw must contain just its arm stroke"
    assert 'bc-hammer' not in roaming
    (out / "pooh-roaming.svg").write_text(roaming, encoding="utf-8", newline="")


if __name__ == "__main__":
    test_pooh_roaming_contract()
    print("ok: approved pose, unchanged crew, deterministic SVG and empty paw")
