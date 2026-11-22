import copy
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
from occurrence_identity import collapse_occurrences

fixture = Path(__file__).with_name('entry-duplicate-fixture.json')
raw = json.loads(fixture.read_text())
original = copy.deepcopy(raw)
canonical = collapse_occurrences(list(reversed(raw)))
assert len(canonical) == 1
first = canonical[0]
assert first['entry'] == 84229.67
assert first['available_at'] == raw[0]['available_at']
assert first['direction'] == 'LONG'
assert first['points'] == raw[0]['points']
assert len(first['occurrence_aliases']) == 3
assert first['last_seen_at'] == raw[-1]['available_at']
assert collapse_occurrences(canonical) == canonical
assert raw == original
others = []
for field, value in [('method','ZigZag Limit'),('tf','4h'),('symbol','SOLUSDT'),('name','Double_Bottom')]:
    item = copy.deepcopy(raw[0]); item[field] = value; item['id'] = field
    others.append(item)
new_structure = copy.deepcopy(raw[0])
new_structure['id'] = 'new-anchor'
new_structure['points'][0]['time'] -= 3600
others.append(new_structure)
assert len(collapse_occurrences(raw+others)) == 6, 'Distinct anchors/methods/markets remain independent'
script = """
const fs=require('fs'), assert=require('node:assert/strict');
const {timeline,createNotificationSession}=require('./static/pattern-presentation.js');
const raw=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));
const view=timeline(raw,raw[2].id);
assert.equal(view.total,1); assert.equal(view.main.id,raw[0].id);
assert.equal(view.main.entry,84229.67); assert.equal(view.main.direction,'LONG');
assert.deepEqual(view.main.points,raw[0].points);
const session=createNotificationSession();
session.observe('BTC:1h',[raw[0]],(raw[0].available_at+10)*1000,3600);
assert.deepEqual(session.observe('BTC:1h',raw,(raw[2].available_at+10)*1000,3600),[]);
console.log(JSON.stringify(view.main));
"""
js = json.loads(subprocess.check_output(['node','-e',script,str(fixture)],cwd=ROOT,text=True))
assert js == first, 'Frontend and backend resolve the same canonical Entry'
print('PASS: actual BTC 07/10 repeats collapse 3 -> 1 at 07:00 UTC / Entry 84229.67; direction and pivots frozen; alias navigation; no duplicate alert; distinct structures retained; Python/JS parity.')
