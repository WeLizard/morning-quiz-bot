"""Telegram delivery of player problem reports (outbox kinds problem_report.text / .images).

The bot runs with Defaults(parse_mode=MarkdownV2), so every call here sets parse_mode='HTML'
explicitly and escapes everything that came from the player or the browser.
"""
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from telegram import InputMediaPhoto, LinkPreviewOptions

from storage.models import ProblemReport, ProblemReportImage

KIND_TEXT = 'problem_report.text'
KIND_IMAGES = 'problem_report.images'
KINDS = {KIND_TEXT, KIND_IMAGES}
LIMIT = 4000  # Telegram allows 4096 UTF-16 code units; keep a margin
MOSCOW = ZoneInfo('Europe/Moscow')


def _u16(text):
    return len(text.encode('utf-16-le', 'surrogatepass')) // 2


def _num(value):
    return '?' if value is None else str(value)


def _dpr(value):
    try:
        return str(Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP).normalize())
    except Exception:
        return '?'


def _pair(group, first, second):
    if not isinstance(group, dict):
        return None
    return f'{_num(group.get(first))}×{_num(group.get(second))}'


def _insets(label, group):
    if not isinstance(group, dict):
        return None
    return f'{label} ↑{_num(group.get("top"))} ↓{_num(group.get("bottom"))}'


def render_report(report, images_count: int) -> str:
    """Return the HTML message; the plain (unescaped) length never exceeds 4096 characters."""
    context = report.context if isinstance(report.context, dict) else {}
    who = report.display_name or 'Без имени'
    channel = report.channel + (f', tg {report.telegram_user_id}' if report.telegram_user_id else '')
    created = report.created_at
    when = ''
    if created is not None:
        when = (created if created.tzinfo else created.replace(tzinfo=timezone.utc)
                ).astimezone(MOSCOW).strftime('%d.%m %H:%M МСК')

    screen = ' '.join(part for part in (
        context.get('title'), f'({context["screen"]})' if context.get('screen') else None) if part)
    path = context.get('path')
    screen_line = 'Экран: ' + (screen or '—') + (f' · {path}' if path else '')
    tg = ['Telegram' + (f' {context["tg_version"]}' if context.get('tg_version') else '')
          if context.get('telegram') else 'Браузер']
    for part in (context.get('tg_platform') or context.get('platform'),):
        if part:
            tg.append(part)
    if 'fullscreen' in context:
        tg.append('полный экран: ' + ('да' if context['fullscreen'] else 'нет'))
    screens = [f'Окно {_pair(context.get("viewport"), "width", "height")}'] if context.get('viewport') else []
    if context.get('screen_size'):
        screens.append(f'экран {_pair(context["screen_size"], "width", "height")}')
    if context.get('dpr') is not None:
        screens.append(f'dpr {_dpr(context["dpr"])}')
    safe = [value for value in (_insets('tg', context.get('safe_area')),
                                _insets('content', context.get('content_safe_area')),
                                _insets('css', context.get('css_safe'))) if value]
    if safe:
        fallback = context.get('inset_fallback') if isinstance(context.get('inset_fallback'), dict) else {}
        extra = [name for key, name in (('top', 'запасной верх'), ('bottom', 'запасной низ')) if fallback.get(key)]
        safe_line = 'Safe-area: ' + ' · '.join(safe) + (f' ({", ".join(extra)})' if extra else '')
    else:
        safe_line = None

    error = context.get('error') if isinstance(context.get('error'), dict) else {}
    crumbs = context.get('breadcrumbs') if isinstance(context.get('breadcrumbs'), list) else []
    auto = getattr(report, 'kind', 'manual') == 'auto_error'
    last = context.get('last_error') if isinstance(context.get('last_error'), dict) else None
    last_error_line = None
    if last and last.get('message'):
        place = ':'.join(str(part) for part in (last.get('source'), last.get('line') or None) if part)
        last_error_line = ('Последняя ошибка: ' + last['message'] + (f' ({place})' if place else '')
                           + (f' (автоошибка №{last["report_id"]})' if last.get('report_id') else ''))

    def build(user_agent, body):
        # (plain, markup) pairs so the 4096 limit can be checked on text after tag parsing.
        if auto:
            where = screen or context.get('path') or '—'
            rows = [(f'⚠️ Автоошибка №{report.id} · {where}', f'⚠️ <b>Автоошибка №{report.id}</b> · {escape(where)}'),
                    (report.text, escape(report.text))]
            location = ':'.join(str(part) for part in (error.get('source') or '—', error.get('line') or None,
                                                       error.get('column') or None) if part is not None)
            rows.append((location, escape(location)))
            if body:
                rows.append((body, f'<pre>{escape(body)}</pre>'))
            if crumbs:
                line = 'Шаги: ' + ' → '.join(f'{item.get("kind")}:{item.get("target")}' for item in crumbs
                                             if isinstance(item, dict))
                rows.append((line, escape(line)))
            rows.extend((('', ''), ('Контекст', '<b>Контекст</b>')))
        else:
            rows = [(f'🐞 Отчёт №{report.id} · {who} ({channel})',
                     f'🐞 <b>Отчёт №{report.id}</b> · {escape(who)} ({escape(channel)})'),
                    (body, escape(body))]
            rows.extend(((last_error_line, escape(last_error_line)),) if last_error_line else ())
            rows.extend((('', ''), ('Контекст', '<b>Контекст</b>')))
        lines = [screen_line, f'Версия: {report.build}', ' · '.join(tg)]
        if screens:
            lines.append(' · '.join(screens))
        if safe_line:
            lines.append(safe_line)
        if user_agent:
            lines.append('UA: ' + user_agent)
        lines.append(f'Аккаунт: {report.account_id or "—"}' + (f' · время: {when}' if when else ''))
        if auto:
            lines.append(f'Повторов: {report.occurrences} · аккаунтов: {report.affected_accounts}')
            lines.append('Повторы видны в админке.')
        else:
            lines.append(f'Картинок: {images_count}')
        rows.extend((line, escape(line)) for line in lines)
        return rows

    body = '\n'.join(str(error.get('stack') or '').splitlines()[:12])[:1500] if auto else report.text
    user_agent = context.get('user_agent') or ''
    for user_agent_limit in (len(user_agent), 120, 0):
        rows = build(user_agent[:user_agent_limit], body)
        if sum(_u16(plain) + 1 for plain, _ in rows) <= LIMIT:
            break
    else:
        while True:
            rows = build('', body + '…')
            over = sum(_u16(plain) + 1 for plain, _ in rows) - LIMIT
            if over <= 0 or not body:
                break
            body = body[:-max(1, over // 2)]
    return '\n'.join(markup for _, markup in rows)


def render_event(report, variant: str, count, accounts) -> str:
    """Short follow-up about an already announced automatic error."""
    message = (report.text or '')[:300]
    if variant == 'returned':
        head = (f'🔁 Ошибка №{report.id} вернулась (повторов: {count})',
                f'🔁 <b>Ошибка №{report.id} вернулась</b> (повторов: {escape(str(count))})')
    else:
        head = (f'📈 Ошибка №{report.id}: уже {count} повторов у {accounts} аккаунтов',
                f'📈 <b>Ошибка №{report.id}</b>: уже {escape(str(count))} повторов у {escape(str(accounts))} аккаунтов')
    return head[1] + '\n' + escape(message) + '\nПовторы видны в админке.'


async def _load(database, report_id, with_images):
    async with database.transaction() as session:
        report = await session.get(ProblemReport, int(report_id))
        if report is None:
            raise LookupError('problem report is gone')
        if with_images:
            rows = (await session.execute(
                select(ProblemReportImage.data).where(ProblemReportImage.report_id == report.id)
                .order_by(ProblemReportImage.position))).scalars().all()
            return report, [bytes(row) for row in rows]
        count = await session.scalar(select(func.count()).select_from(ProblemReportImage)
                                     .where(ProblemReportImage.report_id == report.id))
        return report, count or 0


async def deliver(context, database, item):
    """Send one outbox item. Telegram errors propagate to the dispatcher (retry_after / uncertain)."""
    chat_id = item['chat_id']
    if item['kind'] == KIND_TEXT and item['payload'].get('variant') == 'digest':
        since = datetime.fromisoformat(item['payload']['since'])
        async with database.transaction() as session:
            unannounced = await session.scalar(select(func.count()).select_from(ProblemReport).where(
                ProblemReport.kind == 'auto_error', ProblemReport.notified_at.is_(None),
                ProblemReport.created_at >= since, ProblemReport.created_at < since + timedelta(hours=1)))
        if unannounced:  # counted at delivery time; nothing new means nothing to say
            await context.bot.send_message(
                chat_id, f'📊 +{unannounced} новых автоошибок за час — см. админку', parse_mode='HTML',
                link_preview_options=LinkPreviewOptions(is_disabled=True))
        return
    report_id = item['payload']['report_id']
    if item['kind'] == KIND_TEXT:
        report, count = await _load(database, report_id, with_images=False)
        variant = item['payload'].get('variant')
        text = (render_event(report, variant, item['payload'].get('count'), item['payload'].get('accounts'))
                if variant in ('returned', 'milestone') else render_report(report, count))
        await context.bot.send_message(chat_id, text, parse_mode='HTML',
                                       link_preview_options=LinkPreviewOptions(is_disabled=True))
        return
    report, images = await _load(database, report_id, with_images=True)
    if not images:
        return
    caption = escape(f'Отчёт №{report.id}')
    if len(images) == 1:
        await context.bot.send_photo(chat_id, photo=images[0], caption=caption, parse_mode='HTML')
        return
    media = [InputMediaPhoto(media=data, caption=caption if index == 0 else None,
                             parse_mode='HTML' if index == 0 else None)
             for index, data in enumerate(images)]
    await context.bot.send_media_group(chat_id, media=media)
