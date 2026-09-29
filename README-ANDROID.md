# Android dev setup notes

Working notes for whoever (human or AI) next opens this project. Not
user-facing — see `README.md` for that.

## What this is, currently

A minimal but genuinely working scaffold: Android Studio project, Kotlin +
Jetpack Compose UI, Chaquopy embedding a full Python 3.12 interpreter,
`app/src/main/python/synmind/` containing the **exact same** `synmind/core/`
files copied unmodified from the Windows repo (`untanglemate-windows`).

`MainActivity` shows a real visual canvas of the current map — nodes as
boxes positioned by the exact same `core.layout.apply_layout()` Windows
uses (root at `(0,0)`, branches fanning to both `+x`/`-x` for the default
"tidy_branched" style, not a top-down tree), connector lines between
parent and child, pan (drag), pinch-zoom (wired up, not yet interactively
verified — see below), tap-to-expand/collapse a node with children
(UI-only state — doesn't touch the model's own `collapsed` field), and
now real editing: **long-press a node → rename it**. This goes through
`core.commands.EditTextCommand` via `core.history.History` (kept as
module state in `android_bridge._history`) — a real, undo-capable edit
exactly like Windows's own rename, not a raw `node.text = ...`
mutation — then re-measures/re-lays-out the same way as a fresh load,
since the new text likely changed that node's own box size.

**Save** writes through `core.document.save()` (the same Fernet-encrypted
format, `write_history=False` since there's nowhere for Windows's
node-history sidecar file to go from a single `content://` write) to
whichever of these is set: the URI from "Open .smmap…", the fixed debug
path from "Load test map", or — if neither (a never-opened default
map) — falls back to `ActivityResultContracts.CreateDocument` for a real
Save As. Verified end to end on-device: renamed a node, saved, pulled the
resulting file, and loaded it back through the UNMODIFIED Windows
`document.load()` — the new text round-tripped correctly through real
Fernet encryption.

Getting a map's layout right needed a TWO-STEP handshake with
`android_bridge.py`, not one call — see that module's own comment for
the full reasoning:
1. `new_map_structure()` / `open_map_structure(path)` loads/creates the
   map and returns text + children only, positions not set yet.
2. Kotlin measures each node's REAL on-screen box size via Compose's
   `TextMeasurer` and calls `apply_measured_layout(sizes_json)`, which
   feeds those into `mind_map._layout_measured_sizes` — the exact
   mechanism Windows's own canvas uses for real font-metric sizes — then
   runs the real `layout.apply_layout` and returns the laid-out tree.

Trusting `layout.py`'s bare Qt-free size estimate instead (skipping step
2) was the FIRST thing tried, and it visibly overlapped boxes on a wider
real map — the estimate runs low for ordinary Latin text by design (see
`layout.py`'s own comment on it). Two ways to get a map into it:
- **"Open .smmap…"** — the real feature. Uses Android's Storage Access
  Framework (`ActivityResultContracts.OpenDocument`) to pick a file, copies
  it into the app's cache dir (Chaquopy/`core.document.load()` needs a real
  filesystem path, not a `content://` URI), then runs the two-step load
  above through `synmind.android_bridge` — which calls the exact same
  `core.document.load()` / `core.file_format` Windows uses, Fernet
  decryption included.
- **"Load test map"** — debug-only (`BuildConfig.DEBUG`), reads a fixed
  path from the app's own external files dir. Exists purely so this could
  be verified end to end via `adb` without scripting the system file
  picker's UI.

**Correction to an earlier version of this note**: an apparent root/child
overlap here was first (wrongly) diagnosed as a `layout.py` bug and even
filed as a `core-logic` todo — retracted once traced properly. The real
cause: `node.x`/`node.y` are each node's TOP-LEFT corner (per
`_layout_h_children`'s own docstring — `root.x = 0` means the root's box
spans `[0, width]`, not `[-width/2, +width/2]`), and `computeVisible` in
`MainActivity.kt` was drawing every box as if `x, y` were its CENTER.
That silently shifted every box by half its own size — close enough to
still look like a plausible fan-out tree, which is how it got as far as
being misattributed to the shared layout algorithm instead. Fixed by
computing each rect as `[x, x+w] x [y, y+h]` and deriving connector-line
endpoints from each node's own rect center (an id-keyed lookup) instead
of treating raw `x, y` as a center. `layout.py` itself needed no changes.

Verified on a real emulator (not just compiled): loaded an actual
encrypted `.smmap` (root + 2 children + 1 grandchild), title and full tree
displayed correctly, expand/collapse tested interactively via `adb shell
input tap`, screenshotted at each step. Confirmed working on both a
phone-sized (`medium_phone`) and tablet-sized (`medium_tablet`) AVD.

`./gradlew :app:assembleDebug` builds a real installable APK.

## The core/ subset that's copied in

`model`, `document`, `file_format`, `commands`, `layout`, `colors`,
`theme`, `attachments`, `importers`, `maplink`, `history`, plus
`core/__init__.py` and `synmind/__init__.py` — copied as-is, unmodified,
specifically so `core/__init__.py`'s own imports resolve without editing
it. Checked to be stdlib-only except `file_format.py`'s
`cryptography.fernet` dependency (installed via Chaquopy's pip, see
below) — confirmed there are no `synmind.ui` (Qt) imports anywhere in
this subset.

**Deliberately NOT copied yet**: `updater.py`, `no_console.py`,
`window_trace.py`, `ocr_sidecar.py` (all genuinely Windows/PyInstaller-
specific), `book_export.py` / `pptx_export.py` / `office_preview.py`
(desktop document libs, unchecked), `webpage_import.py`, `html_export.py`,
`phone_site.py`, `first_run.py`, `user_dirs.py`, `backup.py`, the `ocr*.py`
family. Evaluate each on its own before adding — being in `core/` only
means "Qt-free", not "already verified Android-portable".

**When you copy a file from Windows `synmind/core/` here, copy it
unmodified.** If Windows fixes something in one of these files later,
the fix should be a straight file copy over the top of this one, not a
hand-merge — that's the entire point of keeping them byte-identical.

## `.smmap` file compatibility — read this before touching `file_format.py`

`file_format.py` encrypts every `.smmap` with a **hard-coded, app-wide**
Fernet key (same key baked into every install, Windows or Android — see
the comment in that file). This is why it was copied unmodified rather
than reimplemented: if the key or the encrypt/decrypt framing drifts
even slightly from the Windows copy, this app silently can't open real
`.smmap` files a user already has, or writes ones Windows can't open.
Never regenerate or "improve" this file independently on either side.

## Prerequisites (this machine, confirmed installed 2026-09-28)

- Android Studio (bundles its own JDK — a JetBrains Runtime, "JBR" — and
  you should always build through IT, not some other java.exe)
- Android SDK: platform `android-37.0`, build-tools `36.0.0`
- Python 3.12 at `C:\Users\sjmin\AppData\Local\Programs\Python\Python312`
  — this is `buildPython` (see below), NOT the Python that runs on the
  phone. That one is bundled by Chaquopy itself, version set in
  `app/build.gradle.kts`.

## Gotcha #1: Norton breaks EVERY Java/Gradle HTTPS download on this machine

Norton Antivirus intercepts HTTPS system-wide with its own root CA. Windows
(and therefore curl, browsers) trusts it via the OS certificate store. The
JBR Android Studio bundles ships its own SEPARATE `cacerts` truststore that
does NOT have Norton's CA — so any Gradle/Java HTTPS download (plugin
resolution, the Gradle wrapper's own first download, Chaquopy's pip
installs) fails with:

```
PKIX path building failed: ... unable to find valid certification path
```

even though curl/browsers work fine on the same machine. **Fix already
applied**: `C:\Users\sjmin\.android-dev-truststore\cacerts` is a copy of
the JBR's cacerts with Norton's CA imported via `keytool -importcert`
(source cert: `C:\ProgramData\Norton\Antivirus\wscert.pem`). It's wired
in two places:

1. `gradle.properties` → `org.gradle.jvmargs` (covers the actual Gradle
   daemon — this is what Android Studio's own Gradle Sync will use too,
   since it reads the project's `gradle.properties`).
2. **NOT covered by #1**: the Gradle *wrapper's* own bootstrap JVM (the
   one-time download of the Gradle distribution itself, before the real
   daemon starts) doesn't read `gradle.properties`. If you ever see this
   exact SSL error coming from `org.gradle.wrapper.Install`/
   `GradleWrapperMain` specifically (not a normal build task), set:
   ```
   set JAVA_OPTS=-Djavax.net.ssl.trustStore=C:\Users\sjmin\.android-dev-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit
   ```
   before running `gradlew` — only needed once per new Gradle version,
   since after that first download it's cached in
   `~/.gradle/wrapper/dists/`.

If this stops working after a Windows/JBR/Norton update, regenerate:
```
keytool -importcert -noprompt -trustcacerts -alias norton-safeweb ^
  -file "C:\ProgramData\Norton\Antivirus\wscert.pem" ^
  -keystore "C:\Users\sjmin\.android-dev-truststore\cacerts" -storepass changeit
```
(copy a fresh `cacerts` from the current JBR's `lib\security\cacerts`
into that path first, via a NON-admin-owned copy — the JBR's own copy
under `Program Files` needs admin rights to edit directly, which is why
this workaround exists as a separate copy instead of patching it in
place.)

## Gotcha #2: `buildPython` must match `chaquopy.defaultConfig.version` EXACTLY

Chaquopy runs `pip` on THIS machine (not the phone) to resolve packages
before bundling them for Android. By default it looks for a local Python
matching the SAME major.minor as the on-device target version — it will
flatly refuse a mismatched one ("is not a valid Python 3.11 command: it
is version 3.12"), it does not just use whatever's close. Since only
Python 3.12 is installed here, `app/build.gradle.kts` sets BOTH
`version = "3.12"` (confirmed valid — Chaquopy resolved a real
`cryptography` wheel for `cp312`) and `buildPython(...)` pointing
straight at `Python312\python.exe`. If you ever install a Python 3.11
and want to switch, change both together.

## Version choices, and why (as of 2026-09-28)

- **AGP 9.4.1** — the version installed AGP moved to a 9.x line aligned
  with Gradle's own numbering; 8.x releases wouldn't resolve. Latest
  stable at the time; check for newer before assuming this is still current.
- **Gradle 9.8.0** — AGP 9.4.1 threw an internal `NoClassDefFoundError`
  (`ProjectTypeBinding`) against Gradle 9.3.0; 9.8.0 (then-current stable)
  resolved it. Suggests AGP 9.4.1's floor is somewhere between those.
- **No separate `org.jetbrains.kotlin.android` plugin.** Applying it
  alongside this AGP version fails ("extension 'kotlin' already
  registered") — Kotlin support is integrated into `com.android.application`
  itself now. Only `org.jetbrains.kotlin.plugin.compose` (required
  separately since Kotlin 2.0 for Compose specifically) is applied.
- **Chaquopy 17.0.0** — confirmed via their own licensing page: MIT-licensed
  since 12.0.1 (July 2022), no commercial fee, no revenue tiers. Always use
  17.x+, not an old pre-12 tutorial that talks about license keys.
- **minSdk 26 / compileSdk & targetSdk 37** — 37 matches the one SDK
  platform actually installed; 26 is a reasonable modern floor, not
  load-bearing, change freely.

## Building from the command line (not just Android Studio)

```
set JAVA_HOME=C:\Program Files\Android\Android Studio\jbr
gradlew.bat :app:assembleDebug
```
Output: `app\build\outputs\apk\debug\app-debug.apk`. First run took ~3.5
min (mostly Chaquopy downloading per-ABI wheels); cached rebuilds are
much faster. `abiFilters` currently builds `arm64-v8a` (real devices) and
`x86_64` (emulator) — the x86_64 pip resolve hit a transient PyPI/Chaquopy
timeout once; if that happens, just rerun, arm64-v8a's already-installed
packages aren't re-downloaded.

## Gotcha #3: raw `/sdcard/...` paths are NOT readable even by your own app

Scoped storage (Android 10+) blocks direct filesystem access to shared
storage paths like `/sdcard/Download/whatever` from app code —
`PermissionError: [Errno 13] Permission denied`, even though `adb push`
can write there just fine and even for the app that "owns" the intent.
This bit the debug "Load test map" button specifically. Two ways around
it, both used here:
- **Real feature (the "Open .smmap…" button)**: use SAF
  (`ActivityResultContracts.OpenDocument`), which hands back a
  `content://` URI with proper access regardless of scoped storage, then
  copy its bytes into the app's own cache dir before handing a real path
  to Python.
- **Debug-only convenience**: `getExternalFilesDir(null)` — the app's own
  external-storage sandbox, e.g.
  `/sdcard/Android/data/com.syntheticcodelab.untanglemate/files/` — is
  readable without any special permission, and `adb push` can write
  there directly for test fixtures.

## SDK tooling on this machine has moved past `sdkmanager`/`avdmanager`

Both are deprecated; `cmdline-tools/latest/bin/android.exe` (a single new
binary) replaces them, with real subcommands: `android sdk install
"system-images;android-37.0;google_apis;x86_64"`,
`android emulator create medium_phone` / `medium_tablet` (device profiles,
not raw AVD configs — `--list-profiles` shows what's available),
`android emulator start <name>` (blocks until fully booted),
`android emulator stop <name>`. The OLD `sdkmanager.bat` wrapper script
that ships alongside it silently mis-splits package IDs containing
semicolons (`system-images;android-37.0;...` → four separate "Package
not found" errors) — use `android.exe` directly, not the wrapper.

## Not done yet

- No app icon (manifest has no `android:icon`; builds fine, just shows
  a default).
- Only renaming is implemented — no add/delete/move/reparent a node yet,
  and expand/collapse is still UI-only (doesn't touch the model's real
  `collapsed` field). No undo/redo UI either, though `android_bridge`
  already exposes `undo()`/`redo()`/`can_undo()`/`can_redo()` — wiring
  buttons up is the next small step, not a new design.
- Save has no dirty-tracking or "unsaved changes" indicator — it always
  writes, and there's no warning before navigating away from an edited,
  unsaved map.
- Pinch-zoom is wired up in code (`detectTransformGestures` updates
  `scale`) but NOT verified interactively — `adb shell input` doesn't
  have a simple multi-touch pinch primitive, only pan (drag) was
  actually tested this round.
- No node styling (fill/border colors, images, badges) — every box is
  the same two colors regardless of what the map actually stores.
- Not tested against a REAL user map (only the small synthetic
  root+2-children+1-grandchild fixture) — large maps, aliases, and every
  other `core/` feature beyond plain parent/child text are unverified.
  Untested at scale: `computeVisible` walks and re-measures the ENTIRE
  expanded subtree on every recomposition with no memoization beyond the
  `remember(root, expanded)` key — fine for a handful of nodes, likely
  needs work before trying a map with hundreds.
