"""Apply two reviewed source deltas after the immutable r4 packet is verified."""
from pathlib import Path
import base64, hashlib, json
root=Path.cwd().resolve()
patch=json.loads((Path(__file__).parent/'sorca_cm_flatcap_r5.json').read_text())
assert hashlib.sha256((root/'sorca-inputs.tar.gz').read_bytes()).hexdigest()==patch['base_packet_sha256']
assert {r['path'] for r in patch['changes']}=={'native/src/libslic3r/ChromaMatterContourCut.cpp','native/src/libslic3r/ChromaMatterFlatCentreCap.hpp'}
pending=[]
for row in patch['changes']:
    target=(root/row['path']).resolve();assert target.is_relative_to(root)
    data=target.read_bytes();assert hashlib.sha256(data).hexdigest()==row['before']
    last=len(data)+1
    for start,end,replacement in reversed(row['changes']):
        assert 0<=start<=end<last;last=start
        data=data[:start]+base64.b64decode(replacement,validate=True)+data[end:]
    assert hashlib.sha256(data).hexdigest()==row['after']
    pending.append((target,data))
for target,data in pending:target.write_bytes(data)
print('Applied and verified two reviewed flat-cap source changes')
