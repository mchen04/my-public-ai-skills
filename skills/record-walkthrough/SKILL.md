---
name: record-walkthrough
description: >
  Record a captioned MP4 video tour of a whole app area at human speed. Use for "product tour",
  "walkthrough video", "film every page with captions". Not for screenshots, even of a whole flow,
  or a UI check (agent-browser).
---
# Record Walkthrough

A walkthrough shows a viewer every important part of an app area at a pace they can follow. A
caption under the picture says what each thing is and how its numbers are obtained. The audience
is a stakeholder, a teammate, or a reviewer who wants the whole picture. A screenshot or a quick
check of one change needs no walkthrough; use `agent-browser` alone.

The finished work is three things:

- an MP4 with the app at full size and a caption strip below it, so captions never cover the app;
- a chapter list in text, which `walkctl.py burn` writes beside the video;
- a short report: where the file is, how long it runs, what it covers, what you checked, and what
  you left out.

## Workflow

`<skill-dir>` below is the folder that holds this file.

1. **Gather the facts.** List what the viewer should learn before you plan a single shot: every
   user-facing capability, and for each number its rule and its source. Take these from the PR
   body, the diff, and the code. A caption is a claim, so a formula you remember is not good
   enough; quote the one in the code.
2. **Preflight.** Run `python3 <skill-dir>/scripts/walkctl.py preflight`. It names the fix for
   anything missing.
3. **Explore.** Pick an unused session name (`agent-browser session list`) and sign in once if the
   app needs it; [agent-browser](../agent-browser/SKILL.md) owns session isolation. Screenshot
   every section and try each control you plan to use. For each step, note a stable finder
   (visible text, `aria-label`, role), whether the action writes data, and a row that has
   something to show.
4. **Storyboard.** Copy [assets/tour-template.py](assets/tour-template.py) to `tour.py` in a new
   output folder outside the repository. Edit its settings constants (`BASE`, `FIRST_PAGE`,
   `SESSION`, `KICKER`, `READY`) and its `storyboard()` function. Navigate with the app's own
   links through `go()` where it has them, and with `t.goto(BASE + '/path', READY)` where it does
   not. [references/storyboard.md](references/storyboard.md) holds the tour shape, caption rules,
   pace, and the review checklist.
5. **Dry run.** `PACE=0.3 WALKKIT_DIR=<skill-dir>/scripts python3 tour.py dry` saves one
   screenshot per caption and card in a third of the time. `walkctl.py tile <folder>` tiles them;
   look at every one. Fix finders, covered targets, and wrong claims now, while each try is cheap.
6. **Record.** `WALKKIT_DIR=<skill-dir>/scripts python3 tour.py record` plays the tour in real
   time. Run a long tour in the background and wait for its final log line rather than polling.
7. **Burn the captions.** Run `walkctl.py lint captions-record.json`, then
   `walkctl.py burn raw.webm captions-record.json <name>.mp4`.
8. **Watch it.** `walkctl.py frames <name>.mp4 review/` writes one frame per caption and card,
   plus contact sheets. Open every sheet and apply the checklist in the storyboard reference.
   Captions are a separate layer: fix wrong text in `captions-record.json` and burn again. Record
   again only when the picture is wrong.
9. **Gate.** `walkctl.py check <name>.mp4` must end in `VERDICT: PASS`.
10. **Deliver.** Put the MP4 where the user asked and report as above. Say that the video shows
    real names and data when it does. Ask before you upload or post it anywhere: publishing is
    hard to take back.

## Safety while touring

Treat the app as someone else's working data. Open panels, filter, sort, toggle, and copy to the
clipboard freely. State kept only in the browser, such as a saved filter, is fine, but reset it
before you record: the dry run leaves it behind and the recording would start from it. Do not
click anything that saves, accepts, deletes, sends, or syncs; point at it and let the caption say
what it does. A tour is not a test, and on a shared database another person sees every write.

Close your browser session when you finish, and stop any server you started.

## Traps

Each of these happened during a real tour.

- **An open tooltip covers the next target.** The browser then refuses to hover or click it.
  `walkkit` parks the mouse and drops focus before every move, so route custom steps through
  `point()`, `click()`, or `hover()`.
- **`record start` opens a fresh browser context at its own fixed size.** Cookies survive. The
  video keeps that first size, so resizing the viewport afterwards squashes the app. `Tour`
  records in that context in both modes and never resizes it; `burn` refuses a stretched video.
- **The first button in a row is not always its expander.** One table led with a Copy button.
  Confirm in exploration which control opens the panel.
- **The recording starts before the caption clock.** `burn` sets the offset to the video length
  minus the logged length. When it refuses, the log and the video come from different runs.
- **The old caption stays briefly after a section change.** Caption soon after each navigation
  settles, or the viewer reads the last screen's caption over the new one.
- **The capture runs at about 10 fps with no audio.** That suits app screens. It cannot show
  smooth motion or carry narration.
- **Native `<select>` popups do not render in the capture.** Point at the control and name the
  options in the caption.

## Bundled resources

- `scripts/walkkit.py` is EXECUTED through the tour script, which imports it. It drives
  `agent-browser`, draws the cursor and ring, shows cards, and logs caption times. Use it rather
  than reimplementing these steps.
- `scripts/walkctl.py` is EXECUTED: `preflight`, `lint`, `burn`, `tile`, `frames`, `check`. `lint`
  and `check` end in `VERDICT: PASS` or `VERDICT: FAIL`.
- `assets/tour-template.py` is READ and copied. Edit its settings constants and `storyboard()`.
- `references/storyboard.md` is READ while planning and reviewing.

## Composes with

- `agent-browser` — browser session isolation and cleanup.
- `open-pr` — the PR body that links the walkthrough and carries its chapter list.
