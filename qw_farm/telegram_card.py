"""Farm card for the Telegram widget (Bot API 10.4): a pure projection, no I/O.

The card shows only the owner's own farm: coins, ready plots/trees, the times of the next
harvests and the resident orders on the board. It never carries other players' data.
State keys (compact, at most 1024 bytes):
  r  farm revision (the widget ignores older states)   n  farm name     c  coins
  k  plots and trees ready at build time             t  sorted future ready times (unix s)
  o  [[slot, resident, "Товар ×2, …", can_deliver 0/1, coins], …]
Plot readiness is recomputed by the widget from ``t`` on the device clock, so the card stays
correct between requests without editing the message.
"""
from pathlib import Path

from .catalog import ITEMS
from . import market, orchard

HTML_TEMPLATE = Path(__file__).with_name('widget') / 'farm_card.html'
MAX_TIMES = 24
MAX_TEXT = 48


def _short(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _needs_text(needs):
    return _short(', '.join(f"{ITEMS[item]['name']} ×{qty}" for item, qty in needs.items()), MAX_TEXT)


def ready_now(farm, now):
    """The same predicate as the ``collect_all`` command: what one tap would harvest."""
    return [p for p in farm['objects']
            if (p['type'] == 'plot' and p.get('crop') and p['crop']['ready_at'] <= now) or orchard.ripe(p, now)]


def card_state(farm, now):
    """Build the card state from the owner's farm (the ``farm`` of FarmService.view())."""
    future = sorted(
        [p['crop']['ready_at'] for p in farm['objects']
         if p['type'] == 'plot' and p.get('crop') and p['crop']['ready_at'] > now]
        + [p['fruit']['ready_at'] for p in farm['objects']
           if orchard.is_tree(p) and p.get('fruit') and p['fruit']['ready_at'] > now])
    stock = farm.get('inventory', {})
    orders = []
    for order in sorted(farm.get('orders', []), key=lambda o: o['slot']):
        can = all(stock.get(item, 0) >= qty for item, qty in order['needs'].items())
        coins, _ = market.order_reward(farm, order)
        orders.append([order['slot'], _short(order['npc'], 24), _needs_text(order['needs']), int(can), coins])
    return dict(r=farm['revision'], n=_short(farm['name'], 28), c=farm['coins'],
                k=len(ready_now(farm, now)), t=future[:MAX_TIMES], o=orders)


def ready_count(state, now):
    return state['k'] + sum(1 for at in state['t'] if at <= now)


def caption(state, now):
    """Message caption: chat lists, notifications and apps without widgets show only this."""
    ready = ready_count(state, now)
    head = f"🌾 {state['n']}: " + (f'готово к сбору — {ready}' if ready else 'урожай растёт')
    return head + '\nЕсли карточка не видна, обнови Telegram или открой ферму в приложении.'


def render_html(open_url):
    """The widget code with the Mini App link baked in (the code of a sent widget never changes)."""
    html = HTML_TEMPLATE.read_text(encoding='utf-8')
    if open_url is not None and (not isinstance(open_url, str) or '"' in open_url or '\\' in open_url
                                 or not open_url.startswith('https://t.me/') or len(open_url) > 256):
        raise ValueError('Farm link must be a short https://t.me/ link')
    return html.replace('__OPEN_URL__', open_url or '')
