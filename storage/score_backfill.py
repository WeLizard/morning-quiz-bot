"""One-time import of the pre-journal scores into ``score_events`` (migration 0034, JSON importer).

Idempotent: every event has a fixed key and ``ON CONFLICT DO NOTHING``; the cache and totals are
recomputed from the journal. Legacy rows carry ``2000-01-01`` as ``created_at`` so they never
fall into a week/month window.

Per Telegram profile (with an account):
  legacy:chat:<chat_id>  chat_members.score, with chat_id (the chat slice is rebuilt from the journal)
  legacy:residual        users.global_score - sum(chat_members.score) - Alchemy credit
                         (admin edits, imports, anything the per-chat rows do not explain). The credit is
                         LEAST(points_total, GREATEST(global_score - sum(chats), 0)): Alchemy points reached
                         global_score only on top of the chat scores, and an old recompute/reset may have erased them.
Per Alchemy progress:    legacy:alchemy  points_total   (source alchemy, own slice)
Per room Classic answer: room:<game>:<round>  points_delta (never counted before; now common)
"""
LEGACY_AT = "TIMESTAMPTZ '2000-01-01 00:00:00+00'"

# A profile whose Telegram identity is active but whose users.account_id was never set follows that identity.
LINK_FROM_IDENTITY = """
UPDATE users u SET account_id = i.account_id
FROM account_identities i
WHERE u.account_id IS NULL AND i.provider = 'telegram' AND i.provider_subject = u.id::text
  AND i.revoked_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM users o WHERE o.account_id = i.account_id)
"""

PROVISION_ACCOUNTS = """
INSERT INTO accounts (id, display_name, archived, bot_blocked, moderation_revision, moderation_reason)
SELECT md5('mqb-telegram-account:' || u.id::text)::uuid, LEFT(COALESCE(NULLIF(u.display_name, ''), 'Игрок'), 255),
       u.archived, u.bot_blocked, u.moderation_revision, u.moderation_reason
FROM users u
WHERE u.account_id IS NULL
  AND NOT EXISTS (SELECT 1 FROM account_identities i
                  WHERE i.provider = 'telegram' AND i.provider_subject = u.id::text AND i.revoked_at IS NULL)
ON CONFLICT (id) DO NOTHING
"""

LINK_ACCOUNTS = """
UPDATE users u SET account_id = md5('mqb-telegram-account:' || u.id::text)::uuid
WHERE u.account_id IS NULL
  AND EXISTS (SELECT 1 FROM accounts a WHERE a.id = md5('mqb-telegram-account:' || u.id::text)::uuid)
"""

LEGACY_CHAT_EVENTS = f"""
INSERT INTO score_events (account_id, source, key, amount, chat_id, created_at)
SELECT u.account_id, 'legacy_import', 'legacy:chat:' || m.chat_id::text, m.score, m.chat_id, {LEGACY_AT}
FROM chat_members m JOIN users u ON u.id = m.user_id
WHERE u.account_id IS NOT NULL AND m.score <> 0
ON CONFLICT (account_id, source, key) DO NOTHING
"""

LEGACY_ALCHEMY_EVENTS = f"""
INSERT INTO score_events (account_id, source, key, amount, created_at)
SELECT ap.account_id, 'alchemy', 'legacy:alchemy', ap.points_total, {LEGACY_AT}
FROM alchemy_progress ap WHERE ap.points_total <> 0
ON CONFLICT (account_id, source, key) DO NOTHING
"""

LEGACY_RESIDUAL_EVENTS = f"""
INSERT INTO score_events (account_id, source, key, amount, created_at)
SELECT u.account_id, 'legacy_import', 'legacy:residual',
       u.global_score - COALESCE(m.total, 0)
         - LEAST(COALESCE(ap.points_total, 0), GREATEST(u.global_score - COALESCE(m.total, 0), 0)), {LEGACY_AT}
FROM users u
LEFT JOIN (SELECT user_id, SUM(score) AS total FROM chat_members GROUP BY user_id) m ON m.user_id = u.id
LEFT JOIN alchemy_progress ap ON ap.user_id = u.id
WHERE u.account_id IS NOT NULL
  AND u.global_score - COALESCE(m.total, 0)
        - LEAST(COALESCE(ap.points_total, 0), GREATEST(u.global_score - COALESCE(m.total, 0), 0)) <> 0
ON CONFLICT (account_id, source, key) DO NOTHING
"""

ROOM_CLASSIC_EVENTS = """
INSERT INTO score_events (account_id, source, key, amount, game_id, room_id, created_at)
SELECT a.account_id, 'classic', 'room:' || a.game_id || ':' || a.round_id, ROUND(a.points_delta, 3),
       a.game_id, g.room_id, a.answered_at
FROM classic_account_answers a JOIN games g ON g.id = a.game_id
WHERE ROUND(a.points_delta, 3) <> 0
ON CONFLICT (account_id, source, key) DO NOTHING
"""

REBUILD_TOTALS = """
INSERT INTO score_totals (account_id, source, total, events, updated_at)
SELECT account_id, source, SUM(amount), COUNT(*), now() FROM score_events GROUP BY account_id, source
ON CONFLICT (account_id, source) DO UPDATE SET total = EXCLUDED.total, events = EXCLUDED.events, updated_at = now()
"""

REBUILD_CACHE = """
UPDATE users u SET global_score = COALESCE((
    SELECT SUM(e.amount) FROM score_events e WHERE e.account_id = u.account_id
      AND e.source IN ('classic', 'photo', 'mafia', 'admin', 'legacy_import')), 0)
WHERE u.account_id IS NOT NULL
"""

STATEMENTS = (LINK_FROM_IDENTITY, PROVISION_ACCOUNTS, LINK_ACCOUNTS, LEGACY_CHAT_EVENTS, LEGACY_ALCHEMY_EVENTS,
              LEGACY_RESIDUAL_EVENTS, ROOM_CLASSIC_EVENTS, REBUILD_TOTALS, REBUILD_CACHE)


async def backfill(session) -> None:
    """Run the backfill inside the caller's async transaction."""
    from sqlalchemy import text
    for statement in STATEMENTS:
        await session.execute(text(statement))
