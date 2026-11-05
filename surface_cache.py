"""Bounded in-memory cache of surface fields, excluding appearance-only inputs."""
from collections import OrderedDict
from threading import RLock
import hashlib,json
import numpy as np
import normal_maps

LOOK_KEYS={'crest','foam_colour','lit_strength','depth_colour_influence','depth_colour_reach',
    'shading_strength','shading_contrast','shading_midpoint','shadow_softness','reflection','roughness','light_direction','light_elevation',
    'view_direction','view_elevation','gpu','glass_layers','lava_cold','lava_hot','lava_peak','lava_glow'}
_entries=OrderedDict();_lock=RLock();MAX_BYTES=96*1024*1024


def signature(settings,c,a):
    source={k:v for k,v in a.items() if k not in LOOK_KEYS}
    if a['normal_source']=='imported':
        p=normal_maps.resolve_path(a['normal_map_path'])
        source['asset_revision']=(p.stat().st_mtime_ns,p.stat().st_size) if p.exists() else None
    return json.dumps([settings,{k:c[k] for k in ('depth_slope','depth_direction')},source],sort_keys=True)


def key(f,c,a,size,gpu):
    digest=hashlib.sha256(np.asarray(f['heights'],dtype=np.float32).tobytes()).hexdigest()
    return signature(f['settings'],c,a),digest,size,bool(gpu)


def get(key):
    with _lock:
        value=_entries.get(key)
        if value is not None:_entries.move_to_end(key)
        return value


def put(key,value):
    size=sum(v.nbytes for v in value if isinstance(v,np.ndarray))
    if size>MAX_BYTES:return
    with _lock:
        _entries[key]=value
        while sum(sum(v.nbytes for v in item if isinstance(v,np.ndarray)) for item in _entries.values())>MAX_BYTES or len(_entries)>3:
            _entries.popitem(last=False)


def clear():
    with _lock:_entries.clear()
