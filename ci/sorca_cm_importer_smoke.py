"""Exercise real GLB conversion in the bundled helper, without opening a GUI."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import zipfile


def cube_glb():
    corners = [(0,0,0),(1,0,0),(1,1,0),(0,1,0),(0,0,1),(1,0,1),(1,1,1),(0,1,1)]
    triangles = [(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),
                 (1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    colors = [(0,1,1,1),(1,0,1,1),(1,1,0,1),(0.01,0.01,0.01,1)]
    xyz = [component for face in triangles for index in face for component in corners[index]]
    rgba = [component for i in range(12) for _ in range(3) for component in colors[i//3]]
    positions = struct.pack('<108f', *xyz)
    colour_bytes = struct.pack('<144f', *rgba)
    indices = struct.pack('<36I', *range(36))
    data = positions + colour_bytes + indices
    document = {
        'asset': {'version':'2.0', 'generator':'Sorca CM synthetic helper smoke'},
        'scene':0, 'scenes':[{'nodes':[0]}], 'nodes':[{'mesh':0}],
        'meshes':[{'primitives':[{'attributes':{'POSITION':0,'COLOR_0':1},'indices':2,'material':0}]}],
        'materials':[{'pbrMetallicRoughness':{'baseColorFactor':[1,1,1,1],'metallicFactor':0,'roughnessFactor':1}}],
        'buffers':[{'byteLength':len(data)}],
        'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':len(positions)},
                       {'buffer':0,'byteOffset':len(positions),'byteLength':len(colour_bytes)},
                       {'buffer':0,'byteOffset':len(positions)+len(colour_bytes),'byteLength':len(indices)}],
        'accessors':[{'bufferView':0,'componentType':5126,'count':36,'type':'VEC3','min':[0,0,0],'max':[1,1,1]},
                     {'bufferView':1,'componentType':5126,'count':36,'type':'VEC4'},
                     {'bufferView':2,'componentType':5125,'count':36,'type':'SCALAR'}]
    }
    meta = json.dumps(document, separators=(',',':')).encode()
    meta += b' ' * (-len(meta) % 4)
    return (struct.pack('<III',0x46546c67,2,12+8+len(meta)+8+len(data))
            +struct.pack('<II',len(meta),0x4e4f534a)+meta+struct.pack('<II',len(data),0x004e4942)+data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--importer', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    source = directory/'synthetic_cube.glb'
    source.write_bytes(cube_glb())
    base = dict(schema='chromamatter.orca-glb-import.v8', input_path=str(source),
                mode='full_spectrum', height_mm=10, sizing_mode='height', up_axis='+Z',
                source_units='metres', basic_color_count=4, full_spectrum_color_count=24)
    cases = {
        'fixed4_dark_slots': dict(base, physical_hex=['#00FFFF','#FF00FF','#FFFF00','#FFFFFF'],
                                 dark_mix={'weights':[1,2,3],'slots':[3,1,2],'display_hex':'#202020'}),
        'coat_reserved_slot': dict(base, physical_hex=['#FF00FF','#FFFF00','#111111','#FFFFFF'],
                                  reserved_coating_slot=4),
    }
    rows = []
    for name, request in cases.items():
        request_path = directory/(name+'.request.json')
        result_path = directory/(name+'.3mf')
        report_path = directory/(name+'.report.json')
        request_path.write_text(json.dumps(request), encoding='utf-8')
        run = subprocess.run([str(args.importer.resolve()), '--request', str(request_path),
                              '--output', str(result_path), '--report', str(report_path)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        (directory/(name+'.log')).write_bytes(run.stdout)
        assert run.returncode == 0, (name, run.returncode, 'See retained helper report/log')
        report = json.loads(report_path.read_text(encoding='utf-8'))
        assert report['status'] == 'ok' and report['source_faces'] == 12 and report['output_faces'] == 12
        assert report['source_face_order_and_indices_preserved'] and report['original_glb_preserved']
        assert report['physical_hex'] == request['physical_hex']
        if 'dark_mix' in request:
            assert report['request']['dark_mix'] == request['dark_mix']
        if 'reserved_coating_slot' in request:
            assert report['reserved_coating_excluded_from_assignment']
        with zipfile.ZipFile(result_path) as archive:
            assert archive.testzip() is None
            assert archive.read('Metadata/chromamatter_original.glb') == source.read_bytes()
        rows.append({'case':name,'source_faces':12,'output_faces':12,
                     'result_sha256':hashlib.sha256(result_path.read_bytes()).hexdigest(),'passed':True})
    (directory/'SMOKE_RESULT.json').write_text(json.dumps({'cases':rows,'gui_tested':False},indent=2)+'\n')
    print('Bundled importer: 2 real GLB conversions and original-byte preservation passed')


if __name__ == '__main__':
    main()
