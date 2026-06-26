# Inbox — drop screenshots here

Put one or more screenshots (.png) of the same thing (e.g. a code file you
scrolled through) directly in this folder, then run:

    python tests/accuracy_harness.py --inbox

It analyses them as ONE document and prints: the detected language, whether the
result compiles, and the extracted text/code so you can eyeball accuracy.

Optional: drop the real source file here too (e.g. truth.py) and it will also
print a char-similarity and line-match score against it.

Screenshots here are local only (*.png is gitignored).
