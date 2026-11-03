"""Apply a reviewed source overlay, then verify canonical packet contents."""
from pathlib import Path, PurePosixPath
import base64, hashlib, json, sys, tarfile
root=Path.cwd().resolve()
patch=json.loads((Path(__file__).parent/'sorca_cm_cutworkflow_r6.json').read_text())
def digest(data):return hashlib.sha256(data).hexdigest()
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
if sys.argv[1]=='apply':
    assert sha(root/'sorca-inputs.tar.gz')==patch['base_packet_sha256']
    pending=[]
    for row in patch['changes']:
        name=PurePosixPath(row['path']);assert not name.is_absolute() and '..' not in name.parts
        target=(root/row['path']).resolve();assert target.is_relative_to(root/'native')
        if row['before'] is None:assert not target.exists();data=b''
        else:data=target.read_bytes();assert digest(data)==row['before']
        last=len(data)+1
        for start,end,replacement in reversed(row['changes']):
            assert 0<=start<=end<last;last=start
            data=data[:start]+base64.b64decode(replacement,validate=True)+data[end:]
        assert digest(data)==row['after']
        pending.append((target,data))
    for target,data in pending:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    print('Reviewed source overlay verified:',len(pending),'files')
elif sys.argv[1]=='verify':
    packet=root/'artifacts/Sorca-CM-v1.1-CutWorkflow-Source-r6.tar.gz'
    with tarfile.open(packet) as archive:
        raw=archive.extractfile('SOURCE_MANIFEST.json').read()
        assert digest(raw)==patch['source_manifest_sha256'], 'Canonical source manifest mismatch'
        manifest=json.loads(raw);assert manifest['file_count']==patch['file_count']
        names=archive.getnames();expected={r['path']:r for r in manifest['files']}
        assert len(names)==len(set(names)) and set(names)==set(expected)|{'SOURCE_MANIFEST.json'}
        for name,row in expected.items():
            data=archive.extractfile(name).read()
            assert len(data)==row['bytes'] and digest(data)==row['sha256']
            assert sha(root/name)==row['sha256']
        (root/'SOURCE_MANIFEST.json').write_bytes(raw)
    receipt=dict(status='PASS',all_payloads_verified=True,file_count=len(expected),
        base_packet_sha256=patch['base_packet_sha256'],reference_source_packet_sha256=patch['reference_packet_sha256'],
        actual_source_packet_sha256=sha(packet),source_manifest_sha256=digest(raw),
        overlay_sha256=sha(Path(__file__).parent/'sorca_cm_cutworkflow_r6.json'),
        note='Exact canonical manifest and every payload verified. Compressed archive bytes are recorded, not assumed identical across zlib implementations.')
    (root/'artifacts/SOURCE_RECONSTRUCTION.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))
else:raise ValueError('apply or verify required')
