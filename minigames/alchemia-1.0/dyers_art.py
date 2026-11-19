"""Illustrations for the dyers' riddles: mordant, indigo, madder, saffron.

Executed by build_art.py with its globals (path, ellipse, leaf, gem, ...). Gradients
`indigo`, `madder` and `saffron` are declared in build_art.py next to the others.
"""


def _skein(x, y, sc=1, c='url(#madder)', edge='#e9b9a4'):
    """A twisted hank of dyed yarn."""
    v = ellipse(0, 0, 17, 11, c, edge, 1.2)
    v += line('M-14 -4Q0 6 14 -4M-15 3Q0 12 15 3M-9 -9Q2 -1 10 -9', edge, 1.2)
    v += path('M13 2Q22 6 20 15', 'none', edge, 2)
    return group(v, f'translate({x} {y}) scale({sc})')


def _mordant():
    jar = path('M33 50C24 63 25 90 38 102H82C95 90 96 63 87 50Z', 'url(#ochre)', '#e0c9a0', 1.3)
    jar += path('M36 64Q60 72 84 64', 'none', '#8d7152', 2.2) + path('M33 80Q60 88 87 80', 'none', '#8d7152', 1.4)
    jar += path('M40 56C35 68 35 84 41 96', 'none', '#f0dcae', 3)
    rim = ellipse(60, 50, 29, 8, '#b6956f', '#ead6ad', 1.2) + ellipse(60, 49, 23, 5, '#5e4a37')
    alum = (group(gem('url(#glass)'), 'translate(30 10) scale(.4)')
            + group(gem('url(#cream)'), 'translate(45 -2) scale(.48)')
            + group(gem('url(#glass)'), 'translate(62 12) scale(.36)'))
    # a test strip of cloth draped over the rim: red above, blue below
    ribbon = path('M78 44C88 40 96 44 98 52L100 98L90 92L88 56C86 52 82 50 78 50Z', 'url(#madder)', '#e8c0a8', 1)
    ribbon += path('M89 74L99 76L100 98L90 92Z', 'url(#indigo)') + line('M89 74L99 76', '#f1e6c8', 1.4)
    return jar + rim + alum + ribbon + star(22, 30, 5) + star(98, 36, 4)


def _indigo():
    vat = path('M20 64H100L93 104Q60 113 27 104Z', 'url(#wood)', '#c6b589', 1.3)
    vat += line('M23 78H97M26 94H94', '#756146', 3) + line('M40 66L36 104M80 66L84 104', '#8b7350', 1)
    dye = ellipse(60, 64, 40, 9, 'url(#indigo)', '#c9d3ea', 1.2) + ellipse(48, 63, 12, 2.5, '#9fb2d8')
    # cloth lifted from the vat: yellow-green at the top, turning blue in the air
    cloth = path('M54 64C48 46 56 30 70 18L88 26C76 36 70 50 72 64Z', 'url(#indigo)', '#c9d3ea', 1)
    cloth += path('M70 18L88 26C83 30 79 35 76 40L61 32Z', '#cdd08a', opacity='.9')
    cloth += path('M61 32L76 40C74 44 72 48 71 52L57 45Z', '#8fae9a', opacity='.75')
    cloth += line('M62 60C58 48 63 38 72 30', '#b7c6e6', 1.5)
    drips = circle(57, 74, 2.5, '#9fb2d8') + circle(66, 80, 2, '#9fb2d8')
    woad = leaf(30, 60, .62, -38, '#8ea66a') + leaf(36, 62, .48, 12)
    return vat + dye + cloth + drips + woad + star(100, 22, 5)


def _madder():
    soil = ellipse(58, 54, 30, 8, 'url(#earth)', '#b5aa71', 1)
    roots = ''.join(path(d, 'none', c, w) for d, c, w in [
        ('M58 56C54 72 44 80 40 100', 'url(#madder)', 7),
        ('M60 56C62 74 70 84 66 104', 'url(#madder)', 6),
        ('M56 58C48 66 34 70 26 84', '#c4705e', 4.5),
        ('M62 58C72 66 84 70 88 86', '#c4705e', 4),
        ('M47 82C42 86 40 92 33 94', '#d8907a', 2.5),
        ('M66 88C72 90 76 96 80 98', '#d8907a', 2.5)])
    roots += line('M57 62C54 74 47 84 43 96', '#f0b7a0', 1.6)
    stem = line('M59 52V20', '#6f9152', 3.5)
    whorl = ''.join(leaf(59, y, sc, r) for y, sc, r in [
        (40, .46, -70), (40, .46, 70), (40, .38, -20), (28, .38, -60), (28, .38, 60), (28, .3, 10)])
    return soil + roots + stem + whorl + _skein(94, 98, .78)


def _saffron():
    leaves = line('M52 104Q48 84 36 66M66 104Q72 84 86 64M58 106Q58 88 56 74', '#7a9d58', 3)
    stem = line('M60 104V66', '#7a9d58', 5) + line('M59 100V72', '#a9c487', 1.5)
    petals = ''.join(group(path('M0 0C-10 -14 -9 -36 0 -46C9 -36 10 -14 0 0Z', 'url(#violet)', '#ddd2ec', 1.1),
                           f'translate(60 68) rotate({r})') for r in (-38, 38, -14, 14))
    petals += path('M48 62C50 50 70 50 72 62C68 70 52 70 48 62Z', '#8a7fae')
    threads = ''.join(path(d, 'none', '#d9643f', 3) for d in (
        'M60 62C58 46 52 34 46 24', 'M60 62C61 44 62 32 62 18', 'M60 62C63 46 70 34 77 25'))
    threads += circle(46, 23, 3, '#ec8a4e') + circle(62, 17, 3, '#ec8a4e') + circle(77, 24, 3, '#ec8a4e')
    dish = ellipse(94, 98, 16, 6, 'url(#cream)', '#efe5c0', 1) + line('M86 96L96 94M89 99L101 97M92 95L100 99', '#d9643f', 1.6)
    return leaves + stem + petals + threads + dish + group(circle(0, 0, 9, 'url(#saffron)'), 'translate(22 26)') + star(22, 26, 12, '#f8e3a6', 8)


A['mordant'] = _mordant()
A['indigo'] = _indigo()
A['madder'] = _madder()
A['saffron'] = _saffron()
