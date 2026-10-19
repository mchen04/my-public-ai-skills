# Stuck signals

`loopctl.py status` owns mechanical tripwires: repeated findings, reverts, flat/churning counts, diff growth, cap and stale receipts. Supply baseline/current diff sizes when needed. Separately fingerprint file+symbol across three cycles so paraphrased repeats are visible.

On a tripwire, dispatch one blind `fresh-eyes` audit of the observer and recent findings. If the observer measures the wrong thing, repair fidelity and reset the streak; never loosen the bar or remove a real failing check. Otherwise halt with a written ledger report naming the blocker. One supervisor repair per trigger; another stall halts. Bar changes require the logged human decision in the root workflow.
