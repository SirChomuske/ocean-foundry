"""Ocean Foundry — Python 3 ocean foundation and export engine.
CLI: python ocean.py --settings settings.json --output ocean.litematic
A static procedural approximation, not a simulation or recovered original algorithm.
"""
import math
import json
import struct
import gzip
import zlib
import defaults

# Owned by default_settings.json so new installations and missing-key fallbacks agree.
DEFAULTS = defaults.section('settings')
# Verified against version.json inside each official Mojang client archive.
VERSIONS = {'26.3': 5023, '26.2': 4903, '26.1.2': 4790, '26.1.1': 4788, '26.1': 4786, '1.21.11': 4671, '1.21.10': 4556, '1.21.8': 4440, '1.21.5': 4325, '1.21.4': 4189, '1.21.1': 3955, '1.20.1': 3465}

COLOURS = ['white','light_gray','gray','black','blue','light_blue','cyan','green',
           'lime','yellow','orange','red','pink','magenta','purple','brown']


def validate(settings):
    s = dict(DEFAULTS)
    s.update({k:v for k,v in settings.items() if k in s})
    limits = {'width':(16,1024),'length':(16,1024),'wave_height':(0,96),
              'wavelength':(8,256),'direction':(0,360),'irregularity':(0,1),
              'detail':(0,1),'sharpness':(0,1),'seed':(0,2147483647),
              'thickness':(1,16),'base_y':(-64,319)}
    ints = {'width','length','wave_height','seed','thickness','base_y'}
    for k,(lo,hi) in limits.items():
        v=float(s[k])
        if not math.isfinite(v) or not lo<=v<=hi or (k in ints and int(v)!=v):
            raise ValueError(f'{k} must be {"an integer " if k in ints else ""}between {lo} and {hi}.')
        s[k]=int(v) if k in ints else v
    if s['fill'] not in ('shell','solid') or s['block'] not in COLOURS:
        raise ValueError('Invalid foundation type or concrete colour.')
    if s['base_y']+s['thickness']-1+s['wave_height']>319:
        raise ValueError('The foundation exceeds Y 319. Reduce base Y, wave height or thickness.')
    return s


def build_foundation(s,h):
    """Convert a heightfield to vertical concrete column intervals."""
    w=s['width']; l=s['length']
    bottom=[0 if s['fill']=='solid' else y-s['thickness']+1 for y in h]
    count=sum(y-b+1 for y,b in zip(h,bottom))
    return {'settings':s,'heights':h,'bottoms':bottom,'stats':{
        'min_y':s['base_y']+min(h),'max_y':s['base_y']+max(h),
        'blocks':count,'volume':w*l*(max(h)+1),'height':max(h)+1}}


def generate(settings):
    """Orchestrate height field -> material placement -> preview data."""
    from waves import heightfield
    settings = validate(settings)
    heights = heightfield(settings)
    return build_foundation(settings, heights)


def _tag(t,name,payload):
    n=name.encode('utf-8'); return bytes([t])+struct.pack('>H',len(n))+n+payload


def _int(name,n): return _tag(3,name,struct.pack('>i',n))
def _short(name,n): return _tag(2,name,struct.pack('>H',n))
def _compound(name,*tags): return _tag(10,name,b''.join(tags)+b'\0')
def _string(name,s):
    b=s.encode('utf-8'); return _tag(8,name,struct.pack('>H',len(b))+b)


def schematic(result, minecraft_version='26.1.2'):
    if 'voxels' in result:
        from voxel_exports import schematic as writer
        return writer(result,minecraft_version)
    s=result['settings']; w=s['width']; l=s['length']; h=result['heights']; b=result['bottoms']
    height=max(h)+1; plane=w*l
    data=bytearray(plane*height)
    for i,palette_index in iter_foundation_blocks(result): data[i]=palette_index
    palette=_compound('Palette',_int('minecraft:air',0),_int('minecraft:'+s['block']+'_concrete',1))
    blocks=_compound('Blocks',palette,_tag(7,'Data',struct.pack('>i',len(data))+data))
    # Stable air/concrete states; target data version comes from Mojang's client.
    # Paste-relative origin [0,0,0]; base_y is a placement instruction, not an offset.
    schematic_tag=_compound('Schematic',_int('Version',3),_int('DataVersion',version_data(minecraft_version)),
        _short('Width',w),_short('Height',height),_short('Length',l),
        _tag(11,'Offset',struct.pack('>iiii',3,0,0,0)),
        _compound('Metadata',_string('Name','Ocean Foundry foundation'),
                  _string('OceanFoundrySettings',json.dumps(s))), blocks)
    return gzip.compress(_compound('',schematic_tag),mtime=0)


def heightmap_png(result):
    s=result['settings']; h=result['heights']; lo,hi=min(h),max(h)
    def chunk(t,d): return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
    rows=[]
    for z in range(s['length']):
        rows.append(b'\0'+b''.join(struct.pack('>H',round((v-lo)/(hi-lo)*65535) if hi>lo else 0) for v in h[z*s['width']:(z+1)*s['width']]))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',s['width'],s['length'],16,0,0,0,0))+
            chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b''))



def version_data(version):
    if version not in VERSIONS:
        raise ValueError('Unsupported Minecraft version. Choose a verified release.')
    return VERSIONS[version]


def iter_foundation_blocks(result):
    """Material placement stage: (flat YZX index, block palette index).

    The heightfield remains independent of palette choice. Future colour/glass
    stages can extend this placement stage and palette without changing waves.
    """
    s=result['settings']; plane=s['width']*s['length']
    for i,(top,bottom) in enumerate(zip(result['heights'],result['bottoms'])):
        for y in range(bottom,top+1):
            yield y*plane+i, 1


def litematic(result, minecraft_version='26.1.2', omit_air=True):
    """Gzipped NBT, format 6, compatible block-only subset read by format 7 mods.

    Format version describes the container, not the Minecraft release. Current
    Litematica explicitly accepts format 1..7; format 6 also serves older mods.
    MinecraftDataVersion is selected independently for the target release.
    """
    if 'voxels' in result:
        from voxel_exports import litematic as writer
        return writer(result,minecraft_version,omit_air=omit_air)
    import numpy as np
    from voxel_exports import air_free_litematic
    s=result['settings']
    v=np.zeros((result['stats']['height'],s['length'],s['width']),dtype=np.uint8)
    for index,state in iter_foundation_blocks(result):v.flat[index]=state
    palette=[dict(id='minecraft:air',properties={}),dict(id='minecraft:'+s['block']+'_concrete',properties={})]
    return air_free_litematic(v,palette,minecraft_version,s['base_y'],omit_air)



def blueprint(result, minecraft_version='26.1.2'):
    """Axiom .bp v1 compatible container, per Moulberry BlueprintIo/Header.

    Version 1 uses structure_void as the skip sentinel (current readers support
    both versions 1 and 2). No air is placed outside the concrete foundation.
    Minecraft DataVersion is independent of this container version.
    """
    if 'voxels' in result:
        from voxel_exports import blueprint as writer
        return writer(result,minecraft_version)
    s=result['settings']; w=s['width']; plane=w*s['length']
    chunks={}
    for index,state in iter_foundation_blocks(result):
        y,rest=divmod(index,plane); z,x=divmod(rest,w)
        key=(x//16,y//16,z//16)
        words=chunks.get(key)
        if words is None: words=chunks.setdefault(key,[0]*256)
        local=(y%16)*256+(z%16)*16+x%16
        words[local//16] |= state << (4*(local%16))
    def listing(name,kind,items):
        return _tag(9,name,struct.pack('>bi',kind,len(items))+b''.join(items))
    entries=[_string('Name',name)+b'\0' for name in
             ['minecraft:structure_void','minecraft:'+s['block']+'_concrete']]
    sections=[]
    for (cx,cy,cz),words in sorted(chunks.items()):
        packed=struct.pack('>i',len(words))+b''.join(struct.pack('>Q',n) for n in words)
        section=(_int('X',cx)+_int('Y',cy)+_int('Z',cz)+
                 _compound('BlockStates',listing('palette',10,entries),_tag(12,'data',packed))+b'\0')
        sections.append(section)
    payload=gzip.compress(_compound('',_int('DataVersion',version_data(minecraft_version)),
        listing('BlockRegion',10,sections),listing('BlockEntities',10,[]),listing('Entities',10,[])),mtime=0)
    header=_compound('',_int('Version',1),_string('Name','Ocean Foundry foundation'),
        _string('Author','Ocean Foundry'),listing('Tags',8,[]),
        _tag(5,'ThumbnailYaw',struct.pack('>f',135)),_tag(5,'ThumbnailPitch',struct.pack('>f',30)),
        _tag(1,'LockedThumbnail',b'\0'),_int('BlockCount',result['stats']['blocks']),
        _tag(1,'ContainsAir',b'\0'))
    thumbnail=heightmap_png(result)
    return struct.pack('>I',0x0AE5BB36)+b''.join(struct.pack('>I',len(part))+part for part in [header,thumbnail,payload])


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings',type=Path)
    parser.add_argument('--output',type=Path,default=Path('ocean.litematic'))
    args=parser.parse_args()
    settings=json.loads(args.settings.read_text()) if args.settings else {}
    result=generate(settings)
    exporters={'.litematic':litematic,'.schem':schematic,'.bp':blueprint}
    writer=exporters.get(args.output.suffix.lower())
    if writer is None: parser.error('Output must end with .litematic, .schem or .bp')
    args.output.write_bytes(writer(result,settings.get('minecraft_version','26.1.2')))
    print(json.dumps(result['stats'],indent=2))
