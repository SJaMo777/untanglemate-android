# UnTangleMate Android

Placeholder for the Android port of UnTangleMate. Not started yet — this
repo exists so planning/todos/notes have somewhere of their own to live,
separate from the Windows app.

## Relationship to the Windows app

The Windows app lives at https://github.com/SJaMo777/syntheticmindmap
(local checkout: `untanglemate-windows`). Its `synmind/core/` layer is
Qt-free by design specifically so its model, file format, layout math,
and command/undo logic could be ported here rather than rewritten from
scratch — see that repo's `CLAUDE.md` for what's actually in `core/`
versus what's Windows-UI-only and won't apply here.

Windows-side todos tagged `core-logic` are the running list of changes
that need a matching change here once this project is underway.

## Status

- Tech stack: **not decided yet** (native Kotlin, Flutter, Python via
  Chaquopy/Kivy reusing `synmind/core/` directly, or something else).
- No code yet.
