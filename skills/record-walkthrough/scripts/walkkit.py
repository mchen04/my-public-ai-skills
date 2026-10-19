import json
import os
import subprocess
import time

CURSOR_JS = r'''
if (!document.getElementById('walk-cursor')) {
  const c = document.createElement('div'); c.id = 'walk-cursor';
  c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2l16 9-7 2-3 7z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  Object.assign(c.style, {position:'fixed', left:(window.__walkX ?? innerWidth/2)+'px', top:(window.__walkY ?? innerHeight/2)+'px',
    zIndex:2147483646, pointerEvents:'none', transition:'left .75s cubic-bezier(.4,0,.2,1), top .75s cubic-bezier(.4,0,.2,1)',
    filter:'drop-shadow(0 1px 2px rgba(0,0,0,.4))'});
  document.body.appendChild(c);
  const r = document.createElement('div'); r.id = 'walk-ring';
  Object.assign(r.style, {position:'fixed', zIndex:2147483645, pointerEvents:'none', border:'2px solid #f59e0b', borderRadius:'6px',
    boxShadow:'0 0 0 4px rgba(245,158,11,.18)', opacity:0, transition:'all .35s ease'});
  document.body.appendChild(r);
}
'''

TARGET = '[data-walk-target]'


def by_text(selector, text):
    return (f'[...document.querySelectorAll({json.dumps(selector)})].filter(e => e.getBoundingClientRect().width)'
            f'.find(e => e.textContent.trim().startsWith({json.dumps(text)}))')


def nth(selector, i=0):
    return f'[...document.querySelectorAll({json.dumps(selector)})].filter(e => e.getBoundingClientRect().height)[{int(i)}]'


def css(selector):
    return f'document.querySelector({json.dumps(selector)})'


class Tour:
    def __init__(self, out_dir, session, mode='dry', pace=1.0, kicker=''):
        if mode not in ('dry', 'record'):
            raise SystemExit(f"mode must be 'dry' or 'record', not {mode!r}")
        self.out, self.session, self.mode = os.path.abspath(out_dir), session, mode
        self.pace, self.kicker = pace, kicker
        self.video = os.path.join(self.out, 'raw.webm' if mode == 'record' else 'dry-probe.webm')
        self.viewport, self.recording = None, False
        self.captions, self.t0, self.shots = [], None, 0
        os.makedirs(self.out, exist_ok=True)

    def ab(self, *cmd, check=True, timeout=90):
        p = subprocess.run(['agent-browser', '--session', self.session, '--json', *cmd],
                           capture_output=True, text=True, timeout=timeout)
        try:
            v = json.loads(p.stdout)
        except ValueError:
            raise RuntimeError(f'agent-browser {cmd[0]}: {p.stdout[:300]} {p.stderr[:300]}')
        if check and not v.get('success'):
            raise RuntimeError(f'agent-browser {cmd}: {str(v)[:400]}')
        return v.get('data')

    def js(self, body):
        return self.ab('eval', '(() => {' + body + '})()')['result']

    def wait(self, sec):
        time.sleep(sec * self.pace)

    def settle(self, condition, timeout=40):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.js('return Boolean(' + condition + ')'):
                    return
            except RuntimeError:
                pass
            time.sleep(0.25)
        raise RuntimeError('timeout waiting for: ' + condition)

    def start(self, url, ready='document.readyState === "complete"'):
        self.ab('open', url)
        self.settle(ready)
        self.ab('record', 'start', self.video, url)
        self.recording = True
        self.settle(ready)
        self.viewport = tuple(self.js('return [innerWidth, innerHeight]'))
        self.wait(0.5)
        self.t0 = time.time()

    def goto(self, url, ready='document.readyState === "complete"', after=1.2):
        self.ab('open', url)
        self.settle(ready)
        self.wait(after)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if self.recording:
            self.ab('record', 'stop', check=False, timeout=180)
            if self.mode == 'dry' and os.path.exists(self.video):
                os.remove(self.video)
        end = round(time.time() - self.t0, 2) if self.t0 else 0
        path = os.path.join(self.out, f'captions-{self.mode}.json')
        with open(path, 'w') as f:
            json.dump({'captions': self.captions, 'end': end, 'viewport': list(self.viewport or ())}, f, indent=1)
        print(json.dumps({'mode': self.mode, 'captions': sum(1 for c in self.captions if c['title']),
                          'seconds': end, 'viewport': list(self.viewport or ()), 'log': path}))
        return False

    def leave(self):
        self.ab('mouse', 'move', '8', str(self.viewport[1] - 8), check=False)
        self.js('document.activeElement?.blur?.(); return 1')

    def point(self, finder, ring=True):
        self.leave()
        ok = self.js(CURSOR_JS + f'''
          const el = ({finder}); if (!el) return false;
          el.scrollIntoView({{block:'nearest', inline:'nearest'}});
          document.querySelectorAll('[data-walk-target]').forEach(e => e.removeAttribute('data-walk-target'));
          el.setAttribute('data-walk-target', '1');
          const b = el.getBoundingClientRect(); const x = b.left + Math.min(b.width / 2, 40), y = b.top + b.height / 2;
          window.__walkX = x; window.__walkY = y;
          const c = document.getElementById('walk-cursor'); c.style.left = x + 'px'; c.style.top = y + 'px';
          const r = document.getElementById('walk-ring');
          if ({str(ring).lower()}) Object.assign(r.style, {{left:(b.left-4)+'px', top:(b.top-3)+'px',
            width:(b.width+8)+'px', height:(b.height+6)+'px', opacity:1}});
          else r.style.opacity = 0;
          return true''')
        if not ok:
            raise RuntimeError('finder matched nothing: ' + finder)
        time.sleep(0.9)

    def unring(self):
        self.js("const r = document.getElementById('walk-ring'); if (r) r.style.opacity = 0; return 1")

    def click(self, finder, after=1.2):
        self.point(finder)
        self.ab('click', TARGET)
        self.wait(0.3)
        self.unring()
        self.wait(after)

    def hover(self, finder, after=0.6):
        self.point(finder, ring=False)
        self.ab('hover', TARGET)
        self.wait(after)

    def type(self, finder, text, after=0.6):
        self.click(finder, after=0.2)
        self.ab('keyboard', 'type', text)
        self.wait(after)

    def scroll(self, selector, px, steps=12):
        for _ in range(steps):
            self.js(f'const s = document.querySelector({json.dumps(selector)}); if (s) s.scrollTop += {px // steps}; return 1')
            time.sleep(0.08)

    def caption(self, title, text, hold=0.0, shot=None):
        words = len(f'{title} {text}'.split())
        self.captions.append({'t': round(time.time() - self.t0, 2), 'title': title, 'text': text})
        if self.mode == 'dry':
            self.shots += 1
            name = shot or ''.join(ch if ch.isalnum() else '-' for ch in title.lower())[:24]
            self.ab('screenshot', os.path.join(self.out, f'dry-{self.shots:02d}-{name}.png'))
        self.wait(max(hold, words / 3.0 + 1.0))

    def card(self, title, lines, hold=8.0):
        if self.t0 is not None:
            self.captions.append({'t': round(time.time() - self.t0, 2), 'title': '', 'text': ''})
        self.js(CURSOR_JS + f'''
          const d = document.createElement('div'); d.id = 'walk-card';
          d.innerHTML = '<div style="max-width:880px">'
            + ({json.dumps(self.kicker)} ? '<div style="font:600 13px/1 system-ui;letter-spacing:.18em;color:#f59e0b;margin-bottom:18px">'
               + {json.dumps(self.kicker)} + '</div>' : '')
            + '<div style="font:700 44px/1.15 system-ui;margin-bottom:22px"></div>'
            + {json.dumps(lines)}.map(() => '<div style="font:400 21px/1.45 system-ui;color:#cbd5e1;margin:8px 0"></div>').join('')
            + '</div>';
          const rows = d.firstChild.children, off = {json.dumps(self.kicker)} ? 1 : 0;
          rows[off].textContent = {json.dumps(title)};
          {json.dumps(lines)}.forEach((l, i) => rows[off + 1 + i].textContent = l);
          Object.assign(d.style, {{position:'fixed', inset:0, zIndex:2147483647, background:'#0f172a', color:'#fff',
            display:'flex', alignItems:'center', justifyContent:'center', padding:'40px', opacity:0, transition:'opacity .6s'}});
          document.body.appendChild(d); requestAnimationFrame(() => d.style.opacity = 1); return 1''')
        if self.mode == 'dry':
            time.sleep(0.8)
            self.shots += 1
            self.ab('screenshot', os.path.join(self.out, f'dry-{self.shots:02d}-card.png'))
        self.wait(hold)
        self.js("const d = document.getElementById('walk-card'); if (d) { d.style.opacity = 0; setTimeout(() => d.remove(), 650); } return 1")
        time.sleep(0.8)
