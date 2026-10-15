"""Additive icon compositions for the Pathways content pack.

Executed once by build_art.py after detail_art.py. Existing artwork is never
replaced. All referenced motifs/gradients belong to the existing local atlas.
This is a content-build extension, not browser/gameplay code.
"""
from pathlib import Path as _PathwaysPath
import json as _pathways_json


def _pathways_apply(illustrations, root):
    specs = _pathways_json.loads((_PathwaysPath(root) / 'pathways_art.json').read_text(encoding='utf-8'))
    if not isinstance(specs, dict):
        raise ValueError('Pathways art manifest must be an object')
    pending = dict(specs)
    completed = set()
    for _ in range(len(pending) + 1):
        if not pending:
            return
        progress = False
        for identifier, spec in list(pending.items()):
            base_id, badge_id = spec['base'], spec['badge']
            # Referenced additions must first be built; no circular placeholders.
            if (base_id in pending and base_id not in completed) or (badge_id in pending and badge_id not in completed):
                continue
            if base_id not in illustrations or badge_id not in illustrations:
                continue
            body = (
                '<g transform="translate(2 0) scale(.79)">' + illustrations[base_id] + '</g>'
                '<circle cx="88" cy="88" r="26" fill="#1e3c32" fill-opacity=".16"/>'
                '<circle cx="87" cy="86" r="24" fill="#e9dfbb" stroke="#a48c62" stroke-width="1.5"/>'
                '<g transform="translate(65 63) scale(.37)">' + illustrations[badge_id] + '</g>'
            )
            if identifier in illustrations and illustrations[identifier] != body:
                raise ValueError('Refusing to replace existing art: ' + identifier)
            illustrations[identifier] = body
            completed.add(identifier)
            del pending[identifier]
            progress = True
        if not progress:
            missing = {k: [v[x] for x in ('base', 'badge') if v[x] not in illustrations]
                       for k, v in pending.items()}
            raise ValueError('Missing or circular Pathways art references: ' + repr(missing))
    raise ValueError('Pathways art dependency pass did not converge')


if 'A' in globals() and 'ROOT' in globals():
    _pathways_apply(A, ROOT)
