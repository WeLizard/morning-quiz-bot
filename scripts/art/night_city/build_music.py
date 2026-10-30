"""Encode the Night City music (WAV from docs/tasks/night_city/music_invoce) into AAC .m4a files for the packs.

File names: `<Title> - <world_id> - <day|night|finale>.wav` and `<Title> - shell_theme.wav` (stray spaces before `.wav`
or doubled spaces are tolerated). Per track: silence is trimmed at both ends, loudness is normalised with two-pass
loudnorm (about -18 LUFS for day / night / shell, -16 LUFS for finale), then AAC-LC ~96 kbit/s stereo 48 kHz in an
.m4a (plays everywhere, including Telegram on iOS).

Output (not in git, like the art):
    .local/night-city-packs/worlds/<world_id>/music_<slot>.m4a
    .local/night-city-packs/shell/music_shell_<n>.m4a          (n = 1, 2 ... by track title)
    .local/night-city-packs/music.json                         durations and sizes; build_world_pack.py / build_shell.py read it

    python -I scripts/art/night_city/build_music.py [--src DIR] [--packs DIR] [--only world_id ...] [--jobs 4]
ffmpeg: C:/ffmpeg/bin, then PATH. Temporary files go to F:\\Temp.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SRC = ROOT / 'docs/tasks/night_city/music_invoce'
PACKS = ROOT / '.local/night-city-packs'
TEMP = Path('F:/Temp')
TARGET = {'day': -18.0, 'night': -18.0, 'shell': -18.0, 'finale': -16.0}
TRUE_PEAK, LRA, BITRATE = -1.5, 11, '96k'

NAME = re.compile(r'^(?P<title>.+?)\s*-\s*(?:(?P<world>[a-z][a-z0-9_]*)\s*-\s*(?P<slot>day|night|finale)|(?P<shell>shell_theme))\s*$')
TRIM = ('silenceremove=start_periods=1:start_threshold=-55dB:start_silence=0.03,areverse,'
        'silenceremove=start_periods=1:start_threshold=-55dB:start_silence=0.03,areverse')


def tool(name):
    for suffix in ('.exe', ''):
        path = Path('C:/ffmpeg/bin', name + suffix)
        if path.exists():
            return str(path)
    found = shutil.which(name)
    if not found:
        sys.exit(f'{name} not found')
    return found


FFMPEG, FFPROBE = tool('ffmpeg'), tool('ffprobe')


def parse(path):
    """-> dict(world, slot, title, src) or None."""
    m = NAME.match(re.sub(r'\s+', ' ', path.stem).strip())
    if not m:
        return None
    if m['shell']:
        return {'world': None, 'slot': 'shell', 'title': m['title'].strip(), 'src': path}
    return {'world': m['world'], 'slot': m['slot'], 'title': m['title'].strip(), 'src': path}


def run(args):
    proc = subprocess.run([FFMPEG, '-hide_banner', '-nostdin', '-y', *args], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if proc.returncode:
        raise RuntimeError(proc.stderr[-1500:])
    return proc.stderr


def loudness(path):
    """Measured loudnorm statistics (input_i, input_tp, input_lra, input_thresh, target_offset)."""
    log = run(['-i', str(path), '-af', f'loudnorm=I=-18:TP={TRUE_PEAK}:LRA={LRA}:print_format=json', '-f', 'null', '-'])
    return json.loads(log[log.rindex('{'):log.rindex('}') + 1])


def duration(path):
    out = subprocess.run([FFPROBE, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out)


def encode(item, work):
    dest = item['dest']
    target = TARGET[item['slot']]
    trimmed = work / f'{dest.parent.name}_{dest.stem}_trim.wav'
    run(['-i', str(item['src']), '-af', TRIM, '-c:a', 'pcm_s16le', str(trimmed)])
    before = loudness(trimmed)
    af = (f'loudnorm=I={target}:TP={TRUE_PEAK}:LRA={LRA}:measured_I={before["input_i"]}:measured_TP={before["input_tp"]}:'
          f'measured_LRA={before["input_lra"]}:measured_thresh={before["input_thresh"]}:offset={before["target_offset"]}:linear=true')
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = work / f'{dest.parent.name}_{dest.stem}_out.m4a'
    run(['-i', str(trimmed), '-af', af, '-ar', '48000', '-ac', '2', '-c:a', 'aac', '-b:a', BITRATE, '-movflags', '+faststart', str(tmp_out)])
    shutil.copyfile(tmp_out, dest)
    after = loudness(dest)
    return {'file': dest.name, 'duration': round(duration(dest), 2), 'bytes': dest.stat().st_size, 'title': item['title'],
            'lufs_before': float(before['input_i']), 'lufs_after': float(after['input_i'])}


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--src', default=str(SRC))
    parser.add_argument('--packs', default=str(PACKS))
    parser.add_argument('--only', nargs='*', default=[], help='world ids (and "shell") to encode; default all')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    src, packs = Path(args.src), Path(args.packs)
    items, skipped = [], []
    for path in sorted(src.glob('*.wav')):
        item = parse(path)
        if item:
            items.append(item)
        else:
            skipped.append(path.name)
    if skipped:
        print('not recognised:', skipped)
    seen = {}
    for it in items:
        if it['slot'] == 'shell':
            continue
        key = (it['world'], it['slot'])
        if key in seen:
            sys.exit(f'duplicate track for {key}: {seen[key]} / {it["src"].name}')
        seen[key] = it['src'].name
    shells = sorted((it for it in items if it['slot'] == 'shell'), key=lambda it: it['title'])
    for n, it in enumerate(shells, 1):
        it['dest'] = packs / 'shell' / f'music_shell_{n}.m4a'
    for it in items:
        if it['slot'] != 'shell':
            it['dest'] = packs / 'worlds' / it['world'] / f'music_{it["slot"]}.m4a'
    if args.only:
        items = [it for it in items if (it['world'] or 'shell') in args.only]
    TEMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TEMP, prefix='nc_music_') as tmp:
        work = Path(tmp)
        with ThreadPoolExecutor(args.jobs) as pool:
            results = list(pool.map(lambda it: encode(it, work), items))
    index_path = packs / 'music.json'
    index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {'worlds': {}, 'shell': []}
    index['schema'] = 'nc-music/1'
    keys = ('file', 'duration', 'bytes', 'title')
    shell_entries = []
    totals = {}
    print(f'{"track":30s} {"title":22s} {"sec":>6s} {"KB":>6s} {"LUFS in":>8s} {"LUFS out":>8s}')
    for it, res in zip(items, results):
        if it['slot'] == 'shell':
            shell_entries.append({k: res[k] for k in keys})
            label = it['dest'].stem
        else:
            index['worlds'].setdefault(it['world'], {})[it['slot']] = {k: res[k] for k in keys}
            label = f'{it["world"]}/{it["slot"]}'
            totals[it['world']] = totals.get(it['world'], 0) + res['bytes']
        print(f'{label:30s} {res["title"][:22]:22s} {res["duration"]:6.1f} {res["bytes"] / 1024:6.0f} {res["lufs_before"]:8.1f} {res["lufs_after"]:8.1f}')
    if shell_entries:
        index['shell'] = shell_entries
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('\nper world, KB:', {w: round(b / 1024) for w, b in sorted(totals.items())})
    print('total KB:', round(sum(r['bytes'] for r in results) / 1024))


if __name__ == '__main__':
    main()
