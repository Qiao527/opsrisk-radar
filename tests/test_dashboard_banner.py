import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "src" / "opsrisk" / "assets" / "site" / "app.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed to execute dashboard JS")
def test_partial_run_warns_of_incomplete_coverage():
    script = """
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const banner = {};
const context = {document: {getElementById: (id) => id === 'banner' ? banner : {}}, Date};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8').replace(/main\\(\\);\\s*$/, ''), context);
const meta = {data_label: 'live', generated_at: new Date().toISOString(), stale_after_hours: 36, stale: false};
context.showBanner(meta, {last_run: {status: 'partial'}, hours_since_success: 0,
  feeds: [{status: 'ok'}, {status: 'network_error'}]});
assert.match(banner.textContent, /1\\/2 succeeded/);
assert.match(banner.textContent, /Coverage may be incomplete/);
context.showBanner(meta, {last_run: {status: 'ok'}, hours_since_success: 0, feeds: [{status: 'ok'}]});
assert.doesNotMatch(banner.textContent, /feeds failed/);
"""
    subprocess.run(["node", "-e", script, str(APP)], check=True, capture_output=True, text=True)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed to execute dashboard JS")
def test_alerts_only_include_high_recent_articles():
    script = """
const fs = require('fs'), vm = require('vm'), assert = require('assert');
class Node { constructor() { this.children = []; } setAttribute() {} append(c) { this.children.push(c); }
  replaceChildren(...c) { this.children = c; } }
const elements = {'alert-list': new Node(), 'alert-empty': new Node()};
const context = {Node, URL, document: {getElementById: id => elements[id],
  createElement: () => new Node(), createTextNode: s => s}, Date};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8').replace(/main\\(\\);\\s*$/, ''), context);
const article = (title, severity, first_seen) => ({title, severity, first_seen,
  url: 'https://example.com', source: 'Wire', reason: 'reason'});
context.renderAlerts([article('recent', 'HIGH', '2026-10-26T12:00:00'),
  article('old', 'CRITICAL', '2026-10-24T12:00:00'),
  article('low', 'LOW', '2026-10-26T12:00:00')], {generated_at: '2026-10-26T18:00:00Z'});
assert.equal(elements['alert-list'].children.length, 1);
assert.equal(elements['alert-empty'].hidden, true);
"""
    subprocess.run(["node", "-e", script, str(APP)], check=True, capture_output=True, text=True)
