# UnTangleMate Android

Early-stage Android port of UnTangleMate: native Kotlin/Jetpack Compose UI,
with the shared map logic running as embedded Python via Chaquopy rather
than being rewritten. See `README-ANDROID.md` for build setup, gotchas,
and what's copied in versus not yet.

## Relationship to the Windows app

The Windows app lives at https://github.com/SJaMo777/syntheticmindmap
(local checkout: `untanglemate-windows`). Its `synmind/core/` layer is
Qt-free by design specifically so its model, file format, layout math,
and command/undo logic could be ported here rather than rewritten from
scratch — see that repo's `CLAUDE.md` for what's actually in `core/`
versus what's Windows-UI-only and won't apply here. That's exactly what
this project does: `app/src/main/python/synmind/` holds the same
`core/` files, copied unmodified, imported straight into Kotlin.

Windows-side todos tagged `core-logic` are the running list of changes
that need a matching change here.

## Status

- Tech stack: **decided** — Kotlin + Jetpack Compose UI, Chaquopy
  (MIT-licensed, no commercial fee) embedding Python 3.12 for the shared
  `synmind/core/` logic.
- `./gradlew :app:assembleDebug` builds a real, working debug APK — the
  Chaquopy bridge is proven end to end (loads the actual `synmind.core`
  code on-device), but there's no real UI yet, just a proof-of-bridge
  screen. Not yet run on a device/emulator.
