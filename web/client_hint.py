"""Short, human-readable device label from a User-Agent. Never returns the raw string."""
import re

MAX_LENGTH = 60

# Order matters: Chromium forks and iOS wrappers also contain "Chrome"/"Safari".
_BROWSERS = (
    ('Edge', re.compile(r'\b(?:Edg|EdgA|EdgiOS|Edge)/')),
    ('Opera', re.compile(r'\b(?:OPR|OPT|Opera)/')),
    ('Яндекс Браузер', re.compile(r'\bYaBrowser/')),
    ('Samsung Internet', re.compile(r'\bSamsungBrowser/')),
    ('Firefox', re.compile(r'\b(?:Firefox|FxiOS)/')),
    ('Chrome', re.compile(r'\b(?:Chrome|CriOS|Chromium)/')),
    ('Safari', re.compile(r'\bVersion/[\d.]+.*\bSafari/')),
)
_SYSTEMS = (
    ('iPhone', re.compile(r'\biPhone\b')),
    ('iPad', re.compile(r'\biPad\b')),
    ('Android', re.compile(r'\bAndroid\b')),
    ('Windows', re.compile(r'\bWindows\b')),
    ('Chrome OS', re.compile(r'\bCrOS\b')),
    ('macOS', re.compile(r'\bMacintosh\b|\bMac OS X\b')),
    ('Linux', re.compile(r'\bLinux\b|\bX11\b')),
)


def client_hint(user_agent):
    """'Chrome · Windows' style label (<= 60 chars); 'Неизвестное устройство' when nothing is recognised."""
    if not isinstance(user_agent, str) or not user_agent.strip():
        return 'Неизвестное устройство'
    text = user_agent[:512]
    browser = next((name for name, pattern in _BROWSERS if pattern.search(text)), None)
    system = next((name for name, pattern in _SYSTEMS if pattern.search(text)), None)
    if browser is None and system is None:
        return 'Неизвестное устройство'
    return f'{browser or "Браузер"} · {system or "устройство"}'[:MAX_LENGTH]
