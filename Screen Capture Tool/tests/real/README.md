# Real-screenshot accuracy fixtures

One folder per sample. Each folder holds the actual screenshot(s) plus the true
source that was on screen:

```
tests/real/<name>/001.png 002.png ...   # screenshots, in scroll order
tests/real/<name>/truth.py              # the real source (any one non-png file)
```

The truth file's extension sets the language (e.g. truth.py, truth.cpp, truth.cs).

Easiest way to create one: run hotkey_capture.py, capture a code file, then copy
that session's captures/session_*/ folder here as tests/real/<name>/ and drop in
the matching source as truth.<ext>.

Run:  python tests/accuracy_harness.py --real

Note: *.png is gitignored project-wide, so these fixtures won't be committed by
default. They may contain real code — keep that in mind before adding an
exception to track them.
