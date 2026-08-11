# Deploying Code Capture as a macOS app

This packages the whole tool (web UI + capture) into a single **Code Capture.app**
you can double-click — no terminal, no venv. You build it once on your Mac.

## Why a native app (not Docker)
Code Capture reads the screen and uses global hotkeys, which a Docker container
cannot do — it has no access to the Mac display or input. So deployment means a
native `.app`, not a container.

## How it works
`main.py` is a single entry point:
- no flag -> runs the web app (default)
- `--capture` -> runs the hotkey capture worker

When bundled, the app re-invokes **itself** with `--capture` to start a capture
session (instead of spawning a separate `python` process), so everything lives in
one binary.

## Build steps (run on your Mac)

1. Activate your virtual environment and install the build tool:
   ```bash
   source ~/sct-venv/bin/activate        # or: source .venv/bin/activate
   pip install -r requirements.txt
   pip install pyinstaller
   ```

2. Build from the project folder:
   ```bash
   cd "/path/to/Screen Capture Tool"
   pyinstaller packaging/CodeCapture.spec
   ```
   The app appears at `dist/Code Capture.app`.

3. Put your API key where the app can find it (it is not run from the project
   folder, so it looks here):
   ```bash
   mkdir -p ~/.code_capture
   echo 'ANTHROPIC_API_KEY=sk-ant-...' > ~/.code_capture/.env
   ```

4. Launch it:
   ```bash
   open "dist/Code Capture.app"
   ```
   It starts the local server and opens the browser UI. Click **Start capture**,
   switch to your editor, and press **Cmd+Shift+1**.

## Sign the app (do this after every rebuild)
Unsigned rebuilds change the binary, which invalidates macOS permission grants —
so the global hotkey stops working until you re-grant. Ad-hoc sign the app right
after building to give it a valid signature:

```bash
codesign --force --deep --sign - "dist/Code Capture.app"
```

Note: ad-hoc signing (`-`) makes the app a valid signed bundle, but the identity
is still derived from the build, so a rebuild can still require re-granting
permissions. Only a real Apple Developer ID signature makes grants survive every
rebuild. For personal use, just re-grant after a rebuild (below).

## First-run permissions (one time)
macOS will prompt, or grant these in **System Settings -> Privacy & Security**:
- **Screen Recording** -> enable **Code Capture** (read the screen)
- **Accessibility** -> enable **Code Capture** (global hotkey)
- **Notifications** -> allow **Code Capture** (session banners)

After any REBUILD, remove the old **Code Capture** entry in each list (select it, click **–**) and re-add `dist/Code Capture.app` (**+**), then relaunch — otherwise the hotkey silently does nothing.

Because the app is unsigned, the first open may be blocked by Gatekeeper —
**right-click the app -> Open** once to allow it (or run
`xattr -dr com.apple.quarantine "dist/Code Capture.app"`).

## Notes / limits
- The build must be done **on a Mac**; a `.app` can't be produced from Linux.
- Unsigned build is fine for personal use. To distribute it, sign and notarize
  with an Apple Developer ID (`codesign` + `notarytool`).
- To install: drag `Code Capture.app` into `/Applications`.
- Rebuild after code changes: re-run `pyinstaller packaging/CodeCapture.spec`.
