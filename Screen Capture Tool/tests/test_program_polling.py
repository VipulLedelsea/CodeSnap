"""Exercise the browser's redraw decision with real recapture progress changes."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_program_poll_redraws_recapture_counts_errors_and_capture_bar():
    source = (Path(__file__).parents[1] / 'src/webapp/static/app.js').read_text()
    function = source.split('function _programRenderSignature(', 1)[1].split('\nasync function loadProgram', 1)[0]
    script = 'function _programRenderSignature(' + function + r'''
const assert = require('node:assert/strict');
const rows = [{id: 1, name: 'schema.sql', state: 'needs_recapture', version: 1}];
const recaps = {'schema.sql': {id: 2, state: 'reading', pending: {read: 0, frames: 60}}};
const data = {session_running: true, waiting: 1, coverage: {missing: []}};
const signature = () => _programRenderSignature(rows, recaps, data);
const change = update => { const before = signature(); update(); assert.notEqual(signature(), before); };
assert.equal(signature(), signature());
change(() => recaps['schema.sql'].pending.read = 1);
change(() => recaps['schema.sql'].pending.frames = 61);
change(() => recaps['schema.sql'].state = 'failed');
change(() => recaps['schema.sql'].pending.error = 'Please retry');
change(() => data.session_running = false);
change(() => data.waiting = 0);
change(() => data.coverage.missing.push({name: 'new dependency'}));
change(() => rows[0].name = 'renamed.sql');
'''
    subprocess.run([shutil.which('node'), '-e', script], check=True, capture_output=True, text=True)


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_failed_recapture_shows_failure_and_retries_the_pending_capture():
    source = (Path(__file__).parents[1] / 'src/webapp/static/app.js').read_text()
    state = 'const STATE =' + source.split('const STATE =', 1)[1].split('const ISSUE', 1)[0]
    row = 'function _fileRow(' + source.split('function _fileRow(', 1)[1].split('let _progSig', 1)[0]
    action = 'async function fileAction(' + source.split('async function fileAction(', 1)[1].split('async function loadArtifact', 1)[0]
    script = state + row + action + r'''
const assert = require('node:assert/strict');
const escapeHtml = s => String(s), _attr = escapeHtml;
const original = {id: 1, name: 'schema.sql', state: 'done', version: 1};
const pending = {id: 2, state: 'failed', pending: {error: 'Read timeout', frames: 60, read: 3}};
const html = _fileRow(original, pending);
assert.ok(html.includes("Couldn't read"));
assert.ok(html.includes('Read timeout'));
assert.ok(html.includes('data-artifact-id="2"'));
assert.ok(!html.includes('Recapture in progress'));
let requested;
const _program = 'test';
const _pbase = () => '/api/programs/test';
const _json = async (url, options) => { requested = [url, options.method]; return {}; };
const toast = () => {}, loadProgram = () => {};
fileAction({dataset: {id: '1', name: 'schema.sql'}}, 'retry', '2').then(() => {
  assert.deepEqual(requested, ['/api/programs/test/artifacts/2/retry', 'POST']);
});
'''
    subprocess.run([shutil.which('node'), '-e', script], check=True, capture_output=True, text=True)
