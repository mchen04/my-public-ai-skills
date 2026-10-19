# Storyboard and captions

How to plan a walkthrough and write captions a viewer can trust. Read this before you edit the
`storyboard()` function of the tour script.

## Contents

- Shape of a tour
- One section
- Writing a caption
- Pace and length
- Coverage
- Review checklist

## Shape of a tour

| Part | Holds | Why |
|---|---|---|
| Intro card | What the area is for, where its data comes from, what it never does | The viewer needs the purpose before any screen makes sense |
| Sections | One per screen or tab, in the order a user works | Workflow order lets each screen build on the last |
| Closing card | How the parts fit together, plus wins with no screen (speed, safety, tests) | Some important work has nothing to click on |

Cards cover the app and the caption strip stays empty under them. Put card text on the card.

## One section

Start each section with one caption that says what the screen answers. Then show depth with one
to three beats. Good beats change something on screen:

- open a row and show its detail panel;
- switch a view or toggle a chart, then switch it back;
- apply a filter or pick a tab tile;
- hover a help icon that states a rule.

Close what you opened before you move on, so the next frame starts clean. Point at controls that
write data instead of clicking them, and say in the caption what they do.

Pick rows during exploration that have something to show. An empty chart or a "No data" panel
teaches nothing, and the first row is often the least interesting one.

## Writing a caption

A caption has a title and a body.

- **Title:** one to four words naming what is on screen. Use the app's own label, so the viewer
  can find it.
- **Body:** about 25 words at most. Say what the viewer is looking at, then where it comes from
  or how it is calculated. Add why it matters only when that is not obvious.

Take every formula and rule from the code or the PR body, with the names the app uses. Describe
the rule, not today's value, unless you read the value from the frame: data changes between the
dry run and the recording.

Write each caption against the dry-run screenshot of its beat.
These invented task-board examples show why captions must match the current frame:

| Assumed caption | Caption supported by the sample frame |
|---|---|
| Every task is late. | Two tasks have due dates before today. Completed tasks are excluded. |
| Work is split evenly. | The chart groups open tasks by owner. It does not estimate effort. |
| This button finishes the project. | This button opens a confirmation dialog for archiving the project. |

Plain words, present tense, no sales language. Use `->` or `=` for formulas; the caption font
renders them cleanly.

## Pace and length

`walkkit` holds each caption for at least `words / 3 + 1` seconds, and `walkctl.py lint` fails a
caption that leaves the screen sooner than a viewer can read it. Plan five to eight seconds per
beat. A full product area runs five to eight minutes. If the plan passes ten minutes, split it
into one video per area: viewers stop watching long before they stop scrolling.

When the tour feels slow, cut beats rather than shortening holds. Speeding up makes every
caption unreadable; cutting removes only what mattered least.

## Coverage

Before recording, compare the storyboard with the fact list you gathered first. Every capability
on it is either shown in a beat or named on a card. Write down anything you left out on purpose,
and say so in the delivery report: an unstated gap reads as a claim of full coverage.

## Review checklist

For each frame from `walkctl.py frames`:

1. The frame shows the thing its caption names.
2. Nothing covers it: no open tooltip, menu, card, or toast.
3. The caption matches what is on screen, including numbers and labels.
4. The cursor and ring point at the right element.

Fix wrong caption text in the caption log and burn again. Record again only when the picture is
wrong.
