"""Verify the common v1.1 source identity before native compilation."""
from pathlib import Path
import hashlib, json
EXPECTED_PACKET = 'e02c8a2444ea9cff0792678553bb43b3b9de24b9d3d582166a0f189b05c8e727'
EXPECTED_MANIFEST = '0e0d22ef85ce6a573d8e9076c8214d5babe2172ae9fabaf81a628081cac2cae4'
def sha(p):
    with p.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
assert sha(Path('sorca-inputs.tar.gz')) == EXPECTED_PACKET
raw = Path('SOURCE_MANIFEST.json').read_bytes()
assert hashlib.sha256(raw).hexdigest() == EXPECTED_MANIFEST
m = json.loads(raw)
assert m['file_count'] == len(m['files']) == 14541
assert len({r['path'] for r in m['files']}) == 14541
for row in m['files']:
    p = Path(row['path'])
    assert p.stat().st_size == row['bytes'] and sha(p) == row['sha256'], row['path']
Path('artifacts/SOURCE_VERIFICATION.json').write_text(json.dumps(dict(status='PASS', all_payloads_verified=True, file_count=14541, source_packet_sha256=EXPECTED_PACKET, source_manifest_sha256=EXPECTED_MANIFEST), indent=2)+'\n')
print('Verified common v1.1 source:', len(m['files']), 'files')
