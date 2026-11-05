"""Export the same full-resolution material grid to all three formats."""
import gzip
import json
import math
import struct
import time
import zlib
import numpy as np
from ocean import _tag, _int, _short, _compound, _string, version_data, heightmap_png


def listing(name,kind,items):
    return _tag(9,name,struct.pack('>bi',kind,len(items))+b''.join(items))


def state_payload(state):
    props=state.get('properties',{})
    return _string('Name',state['id'])+(_compound('Properties',*[_string(k,v) for k,v in sorted(props.items())]) if props else b'')+b'\0'


def state_name(state):
    props=state.get('properties',{})
    return state['id']+('['+','.join(k+'='+v for k,v in sorted(props.items()))+']' if props else '')


def validate(result,version):
    if version!='26.1.2': raise ValueError('The coloured block catalogue targets Minecraft Java 26.1.2. Select 26.1.2 for colour exports.')
    if len(result['palette'])>128: raise ValueError('Exports support at most 128 total states.')
    v=result['voxels']
    if tuple(result.get('export_offset',()))==(-1,0,-1):v=v[:,1:-1,1:-1]
    return v,result['palette']


def packed_contiguous(values,bits):
    """Litematica continuous bitstream, including entries crossing word boundaries."""
    values=np.asarray(values,dtype=np.uint8)
    words=np.zeros((values.size*bits+63)//64,dtype=np.uint64)
    for start in range(0,values.size,262144):
        part=values.flat[start:start+262144].astype(np.uint64)
        bit=np.arange(start,start+len(part),dtype=np.uint64)*bits
        shift=bit%64
        np.bitwise_or.at(words,(bit//64).astype(np.intp),part<<shift)
        crosses=shift+bits>64
        np.bitwise_or.at(words,(bit[crosses]//64+1).astype(np.intp),part[crosses]>>(64-shift[crosses]))
    return words


def compressed_chunks(parts):
    """Compress bounded NBT fragments without assembling a second raw volume."""
    encoder=zlib.compressobj(wbits=31)
    output=bytearray()
    for part in parts:output.extend(encoder.compress(part))
    output.extend(encoder.flush())
    return bytes(output)


def portable_appearance(settings):
    from pathlib import PureWindowsPath
    settings=dict(settings)
    if settings.get('normal_map_path'):
        settings['normal_map_path']='normal_maps/'+PureWindowsPath(settings['normal_map_path']).name
    return settings


def schematic(result,version):
    voxels,palette=validate(result,version)
    height,length,width=voxels.shape
    # At most 128 states: indices 0..127 fit single-byte VarInts.
    prefix=_tag(10,'',b'')+_tag(10,'Schematic',b'')+b''.join([_int('Version',3),_int('DataVersion',version_data(version)),
        _short('Width',width),_short('Height',height),_short('Length',length),
        _tag(11,'Offset',struct.pack('>iiii',3,0,0,0)),
        _compound('Metadata',_string('Name','Ocean Foundry coloured ocean'),
            _string('OceanFoundrySettings',json.dumps({'foundation':result['settings'],'colour':result['colour_settings'],
                'appearance':portable_appearance(result.get('appearance_settings',{}))}))),
        _tag(10,'Blocks',b''),_compound('Palette',*[_int(state_name(s),i) for i,s in enumerate(palette)]),
        _tag(7,'Data',struct.pack('>i',voxels.size))])
    def parts():
        yield prefix
        for plane in voxels:yield plane.tobytes()
        yield listing('BlockEntities',10,[])+b'\0'+listing('Entities',10,[])+b'\0\0'
    return compressed_chunks(parts())


def litematic(result,version,omit_air=True):
    voxels,palette=validate(result,version)
    return air_free_litematic(voxels,palette,version,result['settings']['base_y'],omit_air)


def occupied_boxes(voxels):
    """Disjoint occupied cuboids, merging identical row runs and layer rectangles."""
    active={};finished=[]
    for y,plane in enumerate(voxels):
        rows={};rectangles=[]
        for z,row in enumerate(plane):
            edges=np.flatnonzero(np.diff(np.pad(row!=0,(1,1)).astype(np.int8)))
            runs=set(zip(edges[::2].tolist(),edges[1::2].tolist()))
            for run,z0 in rows.items():
                if run not in runs:rectangles.append((*run,z0,z))
            rows={run:rows.get(run,z) for run in runs}
        rectangles.extend((*run,z0,len(plane)) for run,z0 in rows.items())
        current=set(rectangles)
        for rect,y0 in active.items():
            if rect not in current:finished.append((*rect,y0,y))
        active={rect:active.get(rect,y) for rect in current}
    finished.extend((*rect,y0,len(voxels)) for rect,y0 in active.items())
    return sorted(finished,key=lambda b:(b[4],b[2],b[0]))


def air_free_litematic(voxels,palette,version,base_y,omit_air=True):
    """No region contains an air voxel. Gaps are outside every placement region.

    Litematica reserves palette index zero for air, retained but never referenced.
    A multi-region file is necessary: the format has no sparse mask within a region.
    """
    height,length,width=voxels.shape
    boxes=occupied_boxes(voxels) if omit_air else [(0,width,0,length,0,height)]
    def vec(name,x,y,z): return _compound(name,_int('x',x),_int('y',y),_int('z',z))
    now=int(time.time()*1000)
    meta=_compound('Metadata',_string('Name','Ocean Foundry coloured ocean'),_string('Author','Ocean Foundry'),
        _string('Description',f'Java {version}. Origin Y {base_y}. '+('No air placements; keep all regions together at X/Z 0.' if omit_air else 'Compact region: use ignore-air placement.')),
        _int('RegionCount',len(boxes)),_int('TotalVolume',int(np.count_nonzero(voxels)) if omit_air else voxels.size),_int('TotalBlocks',int(np.count_nonzero(voxels))),
        _tag(4,'TimeCreated',struct.pack('>q',now)),_tag(4,'TimeModified',struct.pack('>q',now)),
        vec('EnclosingSize',width,height,length))
    def parts():
        yield _tag(10,'',b'')+_int('Version',6)+_int('SubVersion',1)+_int('MinecraftDataVersion',version_data(version))+meta+_tag(10,'Regions',b'')
        for number,(x0,x1,z0,z1,y0,y1) in enumerate(boxes):
            part=voxels[y0:y1,z0:z1,x0:x1]
            used=np.unique(part);used=used[used!=0];lookup=np.zeros(len(palette),dtype=np.uint8)
            lookup[used]=np.arange(1,len(used)+1,dtype=np.uint8)
            local=[palette[0]]+[palette[int(i)] for i in used]
            words=packed_contiguous(lookup[part],max(2,math.ceil(math.log2(len(local)))))
            yield (_tag(10,f'part_{number:06d}',b'')+vec('Position',x0,y0,z0)+vec('Size',x1-x0,y1-y0,z1-z0)
                +listing('BlockStatePalette',10,[state_payload(s) for s in local])+_tag(12,'BlockStates',struct.pack('>i',len(words))))
            for first in range(0,len(words),32768):yield words[first:first+32768].astype('>u8').tobytes()
            yield b''.join(listing(n,10,[]) for n in ['Entities','TileEntities','PendingBlockTicks','PendingFluidTicks'])+b'\0'
        yield b'\0\0'
    return compressed_chunks(parts())


def blueprint(result,version):
    voxels,palette=validate(result,version)
    palette=[{'id':'minecraft:structure_void','properties':{}},*palette[1:]]
    entries=listing('palette',10,[state_payload(s) for s in palette])
    sections=[]
    height,length,width=voxels.shape
    for y in range(0,height,16):
        for z in range(0,length,16):
            for x in range(0,width,16):
                part=voxels[y:y+16,z:z+16,x:x+16]
                if not np.any(part): continue
                section=np.zeros((16,16,16),dtype=np.uint8)
                section[:part.shape[0],:part.shape[1],:part.shape[2]]=part
                # Block-state storage packs whole entries within each 64-bit word.
                bits=max(4,math.ceil(math.log2(len(palette))))
                per_word=64//bits
                words=np.zeros(math.ceil(4096/per_word),dtype=np.uint64)
                flat=section.ravel()
                for slot in range(per_word):
                    values=flat[slot::per_word].astype(np.uint64)
                    words[:len(values)]|=values<<(slot*bits)
                packed=struct.pack('>i',len(words))+words.astype('>u8').tobytes()
                sections.append(_int('X',x//16)+_int('Y',y//16)+_int('Z',z//16)+
                    _compound('BlockStates',entries,_tag(12,'data',packed))+b'\0')
    body=gzip.compress(_compound('',_int('DataVersion',version_data(version)),
        listing('BlockRegion',10,sections),listing('BlockEntities',10,[]),listing('Entities',10,[])),mtime=0)
    header=_compound('',_int('Version',1),_string('Name','Ocean Foundry coloured ocean'),
        _string('Author','Ocean Foundry'),listing('Tags',8,[]),
        _tag(5,'ThumbnailYaw',struct.pack('>f',135)),_tag(5,'ThumbnailPitch',struct.pack('>f',30)),
        _tag(1,'LockedThumbnail',b'\0'),_int('BlockCount',result['stats']['blocks']),_tag(1,'ContainsAir',b'\0'))
    return struct.pack('>I',0x0AE5BB36)+b''.join(struct.pack('>I',len(p))+p for p in [header,heightmap_png(result),body])
