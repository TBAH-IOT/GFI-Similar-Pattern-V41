import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'SHA256SUMS.json').read_text(encoding='utf-8'))
for name,digest in manifest.items():
    path=root/name
    assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==digest,name
print(f'PASS: {len(manifest)} packaged files verified')
