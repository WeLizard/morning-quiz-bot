"""How the product addresses a player: one account-level setting for every game and channel.

Telegram does not report gender, so nothing here guesses it: an account stays on
``NEUTRAL`` until the player chooses. ``g`` is mirrored by ``web/mini_client/address.js``
(and its copy for Farm); ``tests/test_address_form.py`` pins both to the same table.
"""
MASCULINE, FEMININE, NEUTRAL = 'm', 'f', 'n'
ADDRESS_FORMS = (MASCULINE, FEMININE, NEUTRAL)
DEFAULT_ADDRESS_FORM = NEUTRAL
ADDRESS_FORM_LABELS = {MASCULINE: 'он', FEMININE: 'она', NEUTRAL: 'не указывать'}


def parse_address_form(value):
    """Strict input check for API/bot writes: only the three codes are accepted."""
    if value in ADDRESS_FORMS:
        return value
    raise ValueError('address_form')


def effective_address_form(value):
    """Stored NULL ("never asked") and any unknown legacy value read as neutral."""
    return value if value in ADDRESS_FORMS else DEFAULT_ADDRESS_FORM


def g(form, masculine, feminine, neutral):
    """Pick the wording for ``form``: ``g(form, 'собрал', 'собрала', 'собрано')``.

    Neutral wording must be a real neutral phrase, never a "собрал(а)" hybrid.
    """
    form = effective_address_form(form)
    return masculine if form == MASCULINE else feminine if form == FEMININE else neutral
