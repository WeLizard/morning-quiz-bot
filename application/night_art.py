"""Night Case art packs on disk, found by the game itself (no hand-made bindings).

The asset builder publishes, next to the sealed pictures (web/mini_client/night/sealed/):
  case-<content_hash>.json  which public pack a newly registered case binds to
  pack-<manifest_sha256>-case-<content_hash>.json
                            the sealed pictures of that pack for that case {asset_id: sha256 of the WebP}
Neither file is served; from sealed/ the web app serves only <sha256>.webp whose bytes match.
Registration freezes the found pack into the case's art binding, so a later rebuild never
rebinds a registered case; the sealed index of every pack is kept for games bound to it.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SEALED_DIR = Path(__file__).resolve().parents[1] / 'web' / 'mini_client' / 'night' / 'sealed'
_HEX = re.compile('[0-9a-f]{64}')
_ID = re.compile('[a-z][a-z0-9_]{1,95}')
_SEALED_CACHE: dict[tuple[str, str, str], dict[str, str]] = {}


def _read(path: Path):
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    return value if type(value) is dict else None


def binding_for_case(meta, content_hash: str, root: Path | None = None):
    """The art binding of a case being registered, or None when no pack was built for it."""
    root = SEALED_DIR if root is None else root
    if type(content_hash) is not str or not _HEX.fullmatch(content_hash):
        return None
    pointer = _read(root / f'case-{content_hash}.json')
    if (pointer is None or pointer.get('schema') != 'nc-case-art/1' or pointer.get('case_content_hash') != content_hash
            or pointer.get('world') != meta.get('world') or pointer.get('style_pack') != meta.get('style_pack')
            or type(pointer.get('manifest_sha256')) is not str or not _HEX.fullmatch(pointer['manifest_sha256'])):
        return None
    return {'schema': 'night-art-binding/1', 'world': pointer['world'], 'style_pack': pointer['style_pack'],
            'manifest_sha256': pointer['manifest_sha256']}


def sealed_pictures(manifest_sha256: str, content_hash: str, root: Path | None = None) -> dict[str, str]:
    """{asset_id: sha256} of the pictures a pack keeps out of public view (e.g. finales)."""
    root = SEALED_DIR if root is None else root
    key = (str(root), str(manifest_sha256), str(content_hash))
    if key in _SEALED_CACHE:
        return dict(_SEALED_CACHE[key])
    result: dict[str, str] = {}
    valid = all(type(v) is str and _HEX.fullmatch(v) for v in (manifest_sha256, content_hash))
    index = _read(root / f'pack-{manifest_sha256}-case-{content_hash}.json') if valid else None
    sealed = index.get('sealed') if index else None
    if (index and index.get('schema') == 'nc-pack-index/1' and index.get('manifest_sha256') == manifest_sha256
            and index.get('case_content_hash') == content_hash and type(sealed) is dict):
        for asset_id, digest in sealed.items():
            if type(asset_id) is str and _ID.fullmatch(asset_id) and type(digest) is str and _HEX.fullmatch(digest):
                try:
                    if hashlib.sha256((root / f'{digest}.webp').read_bytes()).hexdigest() == digest:
                        result[asset_id] = digest
                except OSError:
                    continue
    if result:  # a missing index may appear after a deploy; only found ones are cached
        _SEALED_CACHE[key] = result
    return dict(result)
