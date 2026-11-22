"""Portability regression plus fail-closed checks for real template edits."""
import copy
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
reference=json.loads((ROOT/'CANONICAL-MIGRATION.json').read_text(encoding='utf-8'))

def probe(root,extra=()):
    result=subprocess.run([sys.executable,'-I',str(ROOT/'tests/probe_canonical.py'),'--root',str(root),*extra],
                          capture_output=True,text=True,encoding='utf-8',timeout=90)
    return result,json.loads(result.stdout)

results=[]
for extra in (('--ulp','-1'),('--ulp','0'),('--ulp','1'),('--forbid-sine',)):
    process,data=probe(ROOT,extra)
    assert process.returncode==0,(extra,process.stdout,process.stderr)
    assert data['model_hash']==reference['new_model_hash']
    assert data['catalog_hash']==reference['catalog_hash_unchanged']
    assert data['strategy_hash']==reference['strategy_hash_unchanged']
    assert data['matrices']==reference['matrices_bit_exact']
    assert len(data['registry_markets'])==6
    results.append({'test':list(extra),'passed':True,'numpy':data['numpy']})

with tempfile.TemporaryDirectory(dir=ROOT/'tests',prefix='tmp-canonical-') as directory:
    fake=Path(directory)
    assert fake.resolve().is_relative_to((ROOT/'tests').resolve())
    shutil.copytree(ROOT/'engine',fake/'engine',ignore=shutil.ignore_patterns('__pycache__','Data'))
    shutil.copytree(ROOT/'tools',fake/'tools',ignore=shutil.ignore_patterns('__pycache__'))
    (fake/'runtime').mkdir()
    shutil.copy2(ROOT/'research_runner.py',fake/'research_runner.py')
    registry=json.loads((ROOT/'runtime/research-registry.json').read_text(encoding='utf-8'))
    registry_path=fake/'runtime/research-registry.json'
    registry_path.write_text(json.dumps(registry),encoding='utf-8')
    process,data=probe(fake)
    assert process.returncode==0,(process.stdout,process.stderr)
    canonical_path=fake/'engine/canonical_price_catalog.json'
    document=json.loads(canonical_path.read_text(encoding='utf-8'))
    pattern=next(p for p in document['patterns'] if p['name']=='Rounding_Top')
    value=float.fromhex(pattern['template'][1]['__binary64__'])
    pattern['template'][1]['__binary64__']=math.nextafter(value,math.inf).hex()
    canonical_path.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    process,data=probe(fake)
    assert process.returncode!=0 and not data['passed'],'An actual one-ULP prototype edit must NOT bypass validation'
    results.append({'test':'real_template_one_ulp_tamper_rejected','passed':True})
    shutil.copy2(ROOT/'engine/canonical_price_catalog.json',canonical_path)
    for field in ('model_hash','catalog_hash','strategy_hash','evaluation_hash'):
        bad=copy.deepcopy(registry);bad[field]='0'*64
        registry_path.write_text(json.dumps(bad),encoding='utf-8')
        process,data=probe(fake)
        assert process.returncode!=0 and not data['passed'],field
        results.append({'test':field+'_tamper_rejected','passed':True})

print(json.dumps({'passed':True,'checks':results,'hash_guards_preserved':True},indent=2))
