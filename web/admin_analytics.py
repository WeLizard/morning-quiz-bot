"""Local admin report and complete selected-scope exports."""
import csv
import io
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from storage.admin_analytics import report
from web.question_bank_admin import bank


def csv_cell(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


def make_analytics_router():
    router = APIRouter()

    @router.get('/api/analytics/report')
    async def analytics(request: Request, chat_id: int | None = Query(None, ge=-(2**63), le=2**63-1), days: int = Query(30, ge=1, le=366),
                        download: Literal['json', 'csv'] | None = None):
        try:
            categories = await bank(request).categories()
            result = await report(request.app.state.admin_database, chat_id=chat_id, days=days,
                                  category_names=[c['name'] for c in categories if not c.get('error')])
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        if download == 'csv':
            output = io.StringIO(newline='')
            writer = csv.writer(output)
            writer.writerow(['rank', 'user_id', 'name', 'score', 'classic_answers'])
            for row in result['leaderboard']:
                writer.writerow([csv_cell(row[key]) for key in ('rank', 'user_id', 'name', 'score', 'classic_answers')])
            return Response('\ufeff' + output.getvalue(), media_type='text/csv', headers={
                'Content-Disposition': 'attachment; filename="quiz-leaderboard.csv"', 'Cache-Control': 'no-store'})
        headers = {'Cache-Control': 'no-store'}
        if download:
            headers['Content-Disposition'] = 'attachment; filename="quiz-statistics.json"'
        return JSONResponse(result, headers=headers)

    return router
