"""Recover one reviewed quarantined Night Case; never resets a database."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import secrets
import sys
from uuid import UUID

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from application.night_case import NightCaseError, NightCaseRegistry, OperatorPrincipal
from application.night_case_recovery import NightCaseRecoveryService
from application.night_case_runtime import utc_now
from storage.database import Database, DatabaseSettings, normalize_database_url


def parser():
    result=argparse.ArgumentParser(description=__doc__)
    result.add_argument('--database-url',required=True,help='Explicit reviewed PostgreSQL target; no .env/default database')
    result.add_argument('--game-id',required=True)
    result.add_argument('--snapshot-hash',required=True)
    result.add_argument('--review-ref',required=True)
    result.add_argument('--operator-id',required=True,help='Verified operator namespace from the authorized operator session')
    result.add_argument('--operator-account',type=UUID)
    result.add_argument('--request-id',required=True)
    return result


async def run(args):
    database=Database(DatabaseSettings(url=normalize_database_url(args.database_url)))
    # No cursor endpoint is exposed by this process. Case/build checks still use
    # the normal service codec; no current content file replaces the pinned row.
    registry=NightCaseRegistry(frozenset(),frozenset(),secrets.token_bytes(32))
    try:
        async with database.transaction() as session:
            audit=await NightCaseRecoveryService(session,utc_now,registry).recover_quarantine(
                operator=OperatorPrincipal(args.operator_id,args.operator_account),game_id=args.game_id,
                request_id=args.request_id,expected_snapshot_hash=args.snapshot_hash,review_ref=args.review_ref)
        return {'game_id':audit['game_id'],'snapshot_hash':audit['final_snapshot_hash'],
                'recovery_intervals':len(audit['intervals']),'review_ref':audit['review_ref']}
    finally:
        await database.dispose()


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        result=asyncio.run(run(args))
    except NightCaseError as error:
        print(json.dumps({'error':error.code,'status':error.status}),file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({'error':'recovery_failed'}),file=sys.stderr)
        return 1
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
