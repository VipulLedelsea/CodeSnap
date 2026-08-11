# PyInstaller spec — builds "Code Capture.app" for macOS.
# Build on a Mac:  pyinstaller CodeCapture.spec   (see DEPLOY.md)
# One binary that runs the web app by default and the capture worker with --capture.

block_cipher = None

a = Analysis(
    ['../src/main.py'],
    pathex=['../src'],
    binaries=[],
    datas=[('../src/webapp/static', 'webapp/static')],   # ship the UI files
    hiddenimports=[
        # uvicorn loads these dynamically — PyInstaller can't see them without help
        'uvicorn', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
        'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan', 'uvicorn.lifespan.on',
        # runtime libraries
        'anthropic', 'pynput', 'pynput.keyboard', 'pynput.mouse',
        'mss', 'PIL', 'PIL.Image', 'imagehash', 'fastapi', 'starlette',
        'docx', 'dotenv',
        # this project's own modules (imported lazily inside functions)
        'hotkey_capture', 'agent', 'team', 'tools',
        'core.analysis', 'core.capture', 'core.validate',
        'core.outputs', 'core.notify', 'core.status',
        'webapp.server', 'webapp.session', 'webapp.reports',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    win_no_prefer_redirects=False, win_private_assemblies=False,
    cipher=block_cipher, noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='Code Capture',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False,              # windowed app (no terminal)
    argv_emulation=False,       # keep our --capture flag intact
    target_arch=None, codesign_identity=None, entitlements_file=None,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name='Code Capture',
)

app = BUNDLE(
    coll,
    name='Code Capture.app',
    icon=None,
    bundle_identifier='com.ledelsea.codecapture',
    info_plist={
        'CFBundleName': 'Code Capture',
        'CFBundleDisplayName': 'Code Capture',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'LSMinimumSystemVersion': '12.0',
        # osascript notifications send Apple events:
        'NSAppleEventsUsageDescription': 'Code Capture uses AppleScript to show desktop notifications.',
        'NSHumanReadableCopyright': 'Ledelsea',
    },
)
