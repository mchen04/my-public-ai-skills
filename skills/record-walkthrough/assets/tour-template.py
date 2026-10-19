import os
import sys

SKILL_SCRIPTS = os.environ.get('WALKKIT_DIR', '')
if not SKILL_SCRIPTS:
    sys.exit('walkkit.py not found: set WALKKIT_DIR to the record-walkthrough scripts folder')
sys.path.insert(0, SKILL_SCRIPTS)
from walkkit import Tour, by_text, css, nth  # noqa: E402

MODE = sys.argv[1] if len(sys.argv) > 1 else 'dry'
OUT = os.path.dirname(os.path.abspath(__file__))

BASE = 'http://localhost:3000'
FIRST_PAGE = '/'
SESSION = 'walk-<project>'
KICKER = '<PRODUCT · AREA>'
READY = 'document.readyState === "complete" && !document.querySelector("[aria-busy=true]")'


def go(t, label):
    t.click(by_text('nav a, aside a', label), after=0.3)
    t.settle(READY)
    t.wait(1.2)


def storyboard(t):
    t.card('<Product area>', [
        'What it is for, in one sentence.',
        'Where its data comes from.',
        'Which actions only inspect the sample project data.'], hold=9)

    t.caption('<Section>', '<What this screen answers, and where its numbers come from.>', 5)
    t.click(nth('main table tbody tr') + '.querySelector("button")', after=1.5)
    t.caption('<Row detail>', '<What the opened panel adds. Name the formula when there is one.>', 6)
    t.click(nth('main table tbody tr') + '.querySelector("button")', after=0.6)
    t.hover(css('[aria-label="<help icon>"]'), after=0.8)
    t.caption('<Rule tooltip>', '<The exact rule the tooltip shows.>', 5)
    t.unring()

    go(t, '<Next section>')
    t.caption('<Next section>', '<...>', 5)

    t.card('How it fits together', [
        '1. <Source>: ...',
        '2. <Compute>: ...',
        '3. <Act>: ...'], hold=10)


if __name__ == '__main__':
    pace = float(os.environ.get('PACE', '1')) if MODE == 'dry' else 1.0
    with Tour(OUT, SESSION, MODE, pace=pace, kicker=KICKER) as tour:
        tour.start(BASE + FIRST_PAGE, READY)
        storyboard(tour)
