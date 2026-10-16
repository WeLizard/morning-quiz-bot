"""Local admin routes for player problem reports (behind the admin auth middleware)."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from storage.models import ProblemReport, ProblemReportImage

ReportId = Annotated[int, Path(ge=1, le=2**63 - 1)]


class StatusPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['new', 'in_progress', 'done']


def _iso(value):
    return value.isoformat() if value else None


def make_problem_reports_router():
    router = APIRouter()

    @router.get('/api/admin/problem-reports')
    async def list_reports(request: Request, status: Literal['new', 'in_progress', 'done'] | None = None,
                           kind: Literal['manual', 'auto_error'] | None = None,
                           limit: Annotated[int, Query(ge=1, le=200)] = 50):
        async with request.app.state.admin_database.transaction() as session:
            order = ((ProblemReport.last_seen_at.desc(), ProblemReport.id.desc()) if kind == 'auto_error'
                     else (ProblemReport.created_at.desc(), ProblemReport.id.desc()))
            query = select(ProblemReport).order_by(*order).limit(limit)
            if status:
                query = query.where(ProblemReport.status == status)
            if kind:
                query = query.where(ProblemReport.kind == kind)
            reports = (await session.execute(query)).scalars().all()
            counts = dict((await session.execute(
                select(ProblemReportImage.report_id, func.count()).where(
                    ProblemReportImage.report_id.in_([row.id for row in reports]))
                .group_by(ProblemReportImage.report_id))).all()) if reports else {}
            return {'items': [{
                'id': row.id, 'created_at': _iso(row.created_at), 'status': row.status,
                'display_name': row.display_name, 'channel': row.channel, 'kind': row.kind,
                'screen': (row.context or {}).get('screen'), 'text': row.text[:200],
                'images': counts.get(row.id, 0), 'occurrences': row.occurrences,
                'affected_accounts': row.affected_accounts, 'last_seen_at': _iso(row.last_seen_at),
                'fingerprint': (row.fingerprint or '')[:8] or None} for row in reports]}

    @router.get('/api/admin/problem-reports/{report_id}')
    async def read_report(report_id: ReportId, request: Request):
        async with request.app.state.admin_database.transaction() as session:
            row = await session.get(ProblemReport, report_id)
            if row is None:
                raise HTTPException(404, 'Отчёт не найден.')
            images = (await session.execute(
                select(ProblemReportImage.position, ProblemReportImage.width, ProblemReportImage.height)
                .where(ProblemReportImage.report_id == report_id)
                .order_by(ProblemReportImage.position))).all()
            return {
                'id': row.id, 'created_at': _iso(row.created_at), 'updated_at': _iso(row.updated_at),
                'status': row.status, 'display_name': row.display_name, 'channel': row.channel,
                'telegram_user_id': row.telegram_user_id,
                'account_id': str(row.account_id) if row.account_id else None,
                'request_id': str(row.request_id), 'build': row.build, 'text': row.text, 'kind': row.kind,
                'occurrences': row.occurrences, 'affected_accounts': row.affected_accounts,
                'last_seen_at': _iso(row.last_seen_at), 'notified_at': _iso(row.notified_at),
                'fingerprint': row.fingerprint,
                'context': row.context or {},
                'images': [{'position': p, 'width': w, 'height': h} for p, w, h in images]}

    @router.get('/api/admin/problem-reports/{report_id}/images/{position}')
    async def read_image(report_id: ReportId, position: Annotated[int, Path(ge=0, le=2)], request: Request):
        async with request.app.state.admin_database.transaction() as session:
            image = await session.scalar(select(ProblemReportImage).where(
                ProblemReportImage.report_id == report_id, ProblemReportImage.position == position))
            if image is None:
                raise HTTPException(404, 'Картинка не найдена.')
            return Response(bytes(image.data), media_type='image/jpeg', headers={
                'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-store'})

    @router.patch('/api/admin/problem-reports/{report_id}')
    async def change_status(report_id: ReportId, patch: StatusPatch, request: Request):
        async with request.app.state.admin_database.transaction() as session:
            row = await session.get(ProblemReport, report_id, with_for_update=True)
            if row is None:
                raise HTTPException(404, 'Отчёт не найден.')
            row.status = patch.status
            row.updated_at = datetime.now(timezone.utc)
            return {'id': row.id, 'status': row.status, 'updated_at': _iso(row.updated_at)}

    return router
