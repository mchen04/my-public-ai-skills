#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import subprocess
import sys

READ_WPS = 3.3
READ_LEAD = 0.8
MAX_WORDS = 36
MAX_TITLE_WORDS = 8
DEAD_AIR = 14.0
MAX_OFFSET = 6.0
MAX_STRETCH = 0.02


def die(msg, code=1):
    print(f'walkctl: {msg}', file=sys.stderr)
    sys.exit(code)


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        die(f'{cmd[0]} failed: {p.stderr.strip()[:400]}')
    return p.stdout


def probe(path):
    out = run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,codec_name,width,height,pix_fmt',
               '-of', 'json', path])
    d = json.loads(out)
    video = next((s for s in d.get('streams', []) if s.get('codec_type') == 'video'), None)
    if not video:
        die(f'{path} has no video stream')
    return float(d['format']['duration']), video, d.get('streams', [])


def load_log(path):
    try:
        d = json.load(open(path))
    except (OSError, ValueError) as e:
        die(f'cannot read caption log {path}: {e}')
    if 'captions' not in d or 'end' not in d:
        die(f'{path} is not a walkkit caption log (needs "captions" and "end")')
    return d


def spans(caps, end):
    out = []
    for i, c in enumerate(caps):
        if c['title']:
            stop = caps[i + 1]['t'] if i + 1 < len(caps) else end
            out.append((c['t'], stop, c))
    return out


def need(c):
    return READ_LEAD + len(f"{c['title']} {c['text']}".split()) / READ_WPS


def cmd_preflight(_):
    problems = []
    for tool, fix in [('agent-browser', 'install the agent-browser CLI (see the agent-browser skill)'),
                      ('ffmpeg', 'install ffmpeg built with libass and libx264 (macOS: brew install ffmpeg; Debian: apt install ffmpeg)'),
                      ('ffprobe', 'ffprobe ships with ffmpeg')]:
        where = shutil.which(tool)
        print(f'{tool:14}: {where or "MISSING"}')
        if not where:
            problems.append(f'{tool}: {fix}')
    if shutil.which('ffmpeg'):
        filters = run(['ffmpeg', '-hide_banner', '-filters'])
        encoders = run(['ffmpeg', '-hide_banner', '-encoders'])
        has_ass = any(line.split()[1:2] == ['ass'] for line in filters.splitlines() if line.strip())
        has_x264 = 'libx264' in encoders
        print(f'{"ass filter":14}: {"yes" if has_ass else "MISSING"}')
        print(f'{"libx264":14}: {"yes" if has_x264 else "MISSING"}')
        if not has_ass:
            problems.append('ffmpeg lacks the ass filter: use a build configured with --enable-libass')
        if not has_x264:
            problems.append('ffmpeg lacks libx264: use a build configured with --enable-libx264')
    fonts = run(['fc-list', ':family=DejaVu Sans', 'family']) if shutil.which('fc-list') else ''
    print(f'{"DejaVu Sans":14}: {"yes" if fonts.strip() else "missing (libass falls back to another font)"}')
    for p in problems:
        print(f'FIX: {p}')
    sys.exit(1 if problems else 0)


def cmd_lint(a):
    d = load_log(a.captions)
    fails, warns, seen = [], [], {}
    rows = spans(d['captions'], d['end'])
    if not rows:
        fails.append('no titled captions in the log')
    for start, stop, c in rows:
        label = f"{start:7.1f}s {c['title']!r}"
        words = len(f"{c['title']} {c['text']}".split())
        if words > MAX_WORDS:
            fails.append(f'{label}: {words} words; cut to {MAX_WORDS} or split the beat')
        if len(c['title'].split()) > MAX_TITLE_WORDS:
            fails.append(f'{label}: title over {MAX_TITLE_WORDS} words')
        if not c['text'].strip():
            fails.append(f'{label}: empty body; say what it is and where the number comes from')
        if stop - start < need(c):
            fails.append(f'{label}: on screen {stop - start:.1f}s, needs {need(c):.1f}s to read; raise its hold')
        if stop - start > DEAD_AIR:
            warns.append(f'{label}: on screen {stop - start:.1f}s; check for a stalled step')
        key = c['text'].strip().lower()
        if key and key in seen:
            fails.append(f'{label}: same body as {seen[key]!r}')
        seen[key] = c['title']
    for w in warns:
        print(f'WARN {w}')
    for f in fails:
        print(f'FAIL {f}')
    print(f'{len(rows)} captions, {d["end"]:.0f}s logged')
    print('VERDICT: ' + ('FAIL' if fails else 'PASS'))
    sys.exit(1 if fails else 0)


def ass_time(x):
    x = max(0.0, x)
    return f'{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}'


def ass_text(t):
    return t.replace('\\', '/').replace('{', '(').replace('}', ')').replace('\n', ' ')


def clock(x):
    return f'{int(x // 60)}:{int(x % 60):02d}'


def cmd_burn(a):
    d = load_log(a.captions)
    dur, video, _ = probe(a.raw)
    vw, vh = (d.get('viewport') or [0, 0])[:2]
    if vw and vh and abs(int(video['width']) / int(video['height']) / (vw / vh) - 1) > MAX_STRETCH:
        die(f"{a.raw} is {video['width']}x{video['height']} but the tour ran at {vw}x{vh}, so the app is stretched. "
            f'Something resized the viewport after `record start`; record again without resizing it.')
    if a.offset == 'auto':
        offset = dur - d['end']
        if not 0 <= offset <= MAX_OFFSET:
            die(f'auto offset is {offset:.2f}s (video {dur:.1f}s, log {d["end"]:.1f}s). This log does not belong '
                f'to this recording, or the run was cut short. Re-record, or pass --offset SECONDS after checking a frame.')
    else:
        offset = float(a.offset)
    w, h = int(video['width']) // 2 * 2, int(video['height']) // 2 * 2
    strip = a.strip // 2 * 2
    scale = w / 1280
    title_px, body_px, margin = round(23 * scale), round(21 * scale), round(44 * scale)
    rows = spans(d['captions'], d['end'])

    base = os.path.splitext(a.out)[0]
    ass_path, tl_path, ch_path = base + '.ass', base + '.timeline.json', base + '.chapters.md'
    lines = ['[Script Info]', 'ScriptType: v4.00+', f'PlayResX: {w}', f'PlayResY: {h + strip}', 'WrapStyle: 0', '',
             '[V4+ Styles]',
             'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, '
             'Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, '
             'MarginR, MarginV, Encoding',
             f'Style: Cap,DejaVu Sans,{body_px},&H00F1F5F9,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,'
             f'{margin},{margin},0,1', '',
             '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    timeline, chapters = [], []
    caps = d['captions']
    cards = [{'start': round(c['t'] + offset, 2),
              'end': round(min((caps[i + 1]['t'] if i + 1 < len(caps) else d['end']) + offset, dur), 2)}
             for i, c in enumerate(caps) if not c['title']]
    for start, stop, c in rows:
        s, e = start + offset, min(stop + offset, dur)
        text = ('{\\fad(250,150)}{\\b1\\fs%d\\c&H0B9EF5&}' % title_px) + ass_text(c['title']) + '{\\r}\\N' + ass_text(c['text'])
        lines.append(f'Dialogue: 0,{ass_time(s)},{ass_time(e)},Cap,,0,0,{h + round(18 * scale)},,{text}')
        timeline.append({'start': round(s, 2), 'end': round(e, 2), 'title': c['title'], 'text': c['text']})
        chapters.append(f'{len(chapters) + 1}. `{clock(s)}` **{c["title"]}** — {c["text"]}')
    with open(ass_path, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    vf = (f'scale={w}:{h},pad={w}:{h + strip}:0:0:color=0x0f172a,'
          f'drawbox=x=0:y={h}:w={w}:h=3:color=0xf59e0b@0.9:t=fill,ass={os.path.basename(ass_path)}')
    out_abs = os.path.abspath(a.out)
    p = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', os.path.abspath(a.raw), '-vf', vf,
                        '-r', '30', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
                        '-movflags', '+faststart', '-an', out_abs], cwd=os.path.dirname(os.path.abspath(ass_path)),
                       capture_output=True, text=True)
    if p.returncode:
        die(f'ffmpeg failed: {p.stderr.strip()[:600]}')
    with open(tl_path, 'w') as f:
        json.dump({'offset': round(offset, 2), 'height': h, 'strip': strip, 'captions': timeline, 'cards': cards}, f, indent=1)
    with open(ch_path, 'w') as f:
        f.write('\n'.join(chapters) + '\n')
    print(json.dumps({'video': out_abs, 'seconds': round(dur, 1), 'offset': round(offset, 2),
                      'captions': len(timeline), 'timeline': os.path.abspath(tl_path), 'chapters': os.path.abspath(ch_path)}))


def timeline_of(video_path):
    path = os.path.splitext(video_path)[0] + '.timeline.json'
    if not os.path.isfile(path):
        die(f'{path} not found; run `walkctl.py burn` first')
    return json.load(open(path))


def make_sheets(paths, out_dir, prefix):
    sheets = []
    for n in range(0, len(paths), 6):
        group = paths[n:n + 6]
        sheet = os.path.join(out_dir, f'{prefix}-{n // 6 + 1:02d}.png')
        inputs = sum((['-i', p] for p in group), [])
        tiles = ''.join(f'[{k}]scale=640:-2[t{k}];' for k in range(len(group)))
        layout = ''.join(f'[t{k}]' for k in range(len(group)))
        grid = '|'.join(f'{(k % 2) * 640}_{"+".join(["h0"] * (k // 2)) or 0}' for k in range(len(group)))
        fc = tiles + (f'{layout}xstack=inputs={len(group)}:layout={grid}:fill=black' if len(group) > 1 else f'{layout}null')
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *inputs, '-filter_complex', fc, '-frames:v', '1', sheet])
        sheets.append(sheet)
    return sheets


def cmd_frames(a):
    tl = timeline_of(a.video)
    os.makedirs(a.dir, exist_ok=True)
    points = [min(c['start'] + 2.5, (c['start'] + c['end']) / 2) for c in tl['captions']]
    points += [(c['start'] + c['end']) / 2 for c in tl.get('cards', [])]
    paths = []
    for i, at in enumerate(sorted(points), 1):
        p = os.path.join(a.dir, f'f{i:03d}.png')
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{at:.2f}', '-i', a.video,
             '-frames:v', '1', p])
        paths.append(p)
    sheets = make_sheets(paths, a.dir, 'sheet')
    print(json.dumps({'frames': len(paths), 'sheets': sheets}))
    print('Open every sheet. Each frame must show the thing its caption names, and nothing may cover it.')


def cmd_tile(a):
    paths = sorted(os.path.join(a.dir, f) for f in os.listdir(a.dir) if f.startswith('dry-') and f.endswith('.png'))
    if not paths:
        die(f'no dry-*.png in {a.dir}; run the tour with `dry` first')
    sheets = make_sheets(paths, a.dir, 'dry-sheet')
    print(json.dumps({'shots': len(paths), 'sheets': sheets}))


def cmd_check(a):
    dur, video, streams = probe(a.video)
    tl = timeline_of(a.video)
    fails, warns = [], []
    if video.get('codec_name') != 'h264':
        fails.append(f"codec is {video.get('codec_name')}, not h264")
    if video.get('pix_fmt') != 'yuv420p':
        fails.append(f"pixel format is {video.get('pix_fmt')}, not yuv420p")
    if int(video['width']) % 2 or int(video['height']) % 2:
        fails.append('odd frame dimensions')
    if int(video['height']) != tl['height'] + tl['strip']:
        fails.append('frame height is not app height + caption strip; the captions may overlap the app')
    caps = tl['captions']
    if not caps:
        fails.append('no captions in the timeline')
    for c in caps:
        shown = c['end'] - c['start']
        if c['end'] > dur + 0.5:
            fails.append(f"{c['title']!r} ends at {c['end']:.1f}s, after the video ends at {dur:.1f}s")
        if shown < need(c):
            fails.append(f"{c['title']!r} shows {shown:.1f}s, needs {need(c):.1f}s")
    for x, y in zip(caps, caps[1:]):
        if y['start'] < x['end'] - 0.05:
            fails.append(f"{x['title']!r} overlaps {y['title']!r}")
    if any(s.get('codec_type') == 'audio' for s in streams):
        warns.append('the file has an audio track; confirm it is intended')
    for w in warns:
        print(f'WARN {w}')
    for f in fails:
        print(f'FAIL {f}')
    print(f'{dur:.1f}s, {video["width"]}x{video["height"]}, {len(caps)} captions, '
          f'{os.path.getsize(a.video) / 1e6:.1f} MB')
    print('VERDICT: ' + ('FAIL' if fails else 'PASS'))
    sys.exit(1 if fails else 0)


def main():
    ap = argparse.ArgumentParser(description='Preflight, lint, burn, review frames and gate a walkthrough video. '
                                 '`lint` and `check` end in VERDICT: PASS or VERDICT: FAIL.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('preflight', help='check agent-browser, ffmpeg with libass and libx264, and the caption font')
    p = sub.add_parser('lint', help='gate caption length, reading time and repeats in a caption log')
    p.add_argument('captions')
    p = sub.add_parser('burn', help='add the caption strip below the recording and encode H.264')
    p.add_argument('raw'); p.add_argument('captions'); p.add_argument('out')
    p.add_argument('--offset', default='auto', help="seconds from video start to the caption clock, or 'auto'")
    p.add_argument('--strip', type=int, default=120, help='caption strip height in pixels (default 120)')
    p = sub.add_parser('frames', help='one frame per caption plus 2x3 contact sheets to look at')
    p.add_argument('video'); p.add_argument('dir')
    p = sub.add_parser('tile', help='tile the dry-run screenshots into contact sheets')
    p.add_argument('dir')
    p = sub.add_parser('check', help='gate the finished video')
    p.add_argument('video')
    a = ap.parse_args()
    for tool in ('ffmpeg', 'ffprobe'):
        if a.cmd not in ('preflight', 'lint') and not shutil.which(tool):
            die(f'{tool} not found; run `walkctl.py preflight` for the fix')
    {'preflight': cmd_preflight, 'lint': cmd_lint, 'burn': cmd_burn, 'frames': cmd_frames, 'tile': cmd_tile, 'check': cmd_check}[a.cmd](a)


if __name__ == '__main__':
    main()
