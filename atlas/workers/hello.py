"""HelloWatcher — the reference Persistent Worker (Phase A · §A.4/A.8).

A trivial heartbeat: each tick increments a counter in its checkpoint state and emits a short
note. It is the Phase-A acceptance vehicle (survives kill -9 + reboot resuming mid-count,
pausable/resumable, consumes live operator input, honours its versioned config) and the
copy-me template for real Phase-D workers.
"""

from __future__ import annotations

from atlas.workers.base import PersistentWorker, TickContext, TickResult


class HelloWatcher(PersistentWorker):
    type = "hello_watcher"
    VERSION = 1

    def do_tick(self, ctx: TickContext) -> TickResult:
        count = int(ctx.state.get("count", 0)) + 1
        greeting = ctx.config.get("greeting", "hello")

        # Live operator input can override the greeting mid-run (Q4): "give it a constraint
        # while it runs". Later inputs win.
        for item in ctx.inputs:
            if "greeting" in item:
                greeting = item["greeting"]

        state = {"count": count, "greeting": greeting, "last": f"{greeting} #{count}"}

        # Honour the versioned config: stop when a positive tick_limit is reached.
        tick_limit = int(ctx.config.get("tick_limit", 0) or 0)
        done = tick_limit > 0 and count >= tick_limit

        note = f"{greeting} #{count}" + (" (limit reached)" if done else "")
        return TickResult(state=state, done=done, note=note)
