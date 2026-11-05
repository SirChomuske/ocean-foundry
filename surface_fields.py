"""Bounded surface-field cache and cancellable row batches, before block matching."""
from collections import OrderedDict
from threading import RLock
import numpy as np
import lua_waves
import water_packets
import water_spectrum

_cache = OrderedDict()
_lock = RLock()
MAX_BYTES = 96 * 1024 * 1024


def clear():
    with _lock:
        _cache.clear()


def generate(x, z, a, angle, footprint, check=lambda: None, progress=None, gpu=None):
    model = a['surface_model']
    key = (model, x.shape, float(x[0,0]), float(z[0,0]), float(x[0,-1]), float(z[-1,0]),
           a['ripple_scale'], angle, a['breakup'], a['seed'], a['micro_detail'], footprint,
           a['wind'], a['peak_enhancement'], a['choppiness'], a['ripple_ratio'], bool(gpu),
           int(a.get('lua_layers',1)))
    check()
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    output = tuple(np.empty_like(x) for _ in range(4))
    # Short-wave energy responds to wind; Lua waves are a normal-map source and
    # keep the authored small-ripple strength independent of wind.
    micro = a['micro_detail'] * (1. if model == 'lua_waves' else (.15 + .85 * a['wind']))
    for first in range(0, len(x), 32):
        check()
        section = slice(first, first + 32)
        args = (x[section], z[section], a['ripple_scale'], angle, a['breakup'], a['seed'], micro, footprint)
        if model == 'fft_normals':
            values = water_spectrum.fields(*args, wind=a['wind'], gamma=a['peak_enhancement'],
                choppiness=a['choppiness'] * (.15 + .85 * a['wind']), ripple_ratio=a['ripple_ratio'])
        elif model == 'lua_waves':
            values = lua_waves.fields(*args, layers=int(a.get('lua_layers',1)))
        else:
            values = gpu(*args) if gpu else water_packets.fields(*args)
        for target, value in zip(output, values):
            target[section] = value
        if progress:
            progress(min(first + 32, len(x)), len(x))
    check()
    for field in output:
        field.flags.writeable = False
    with _lock:
        size = sum(field.nbytes for field in output)
        while _cache and (sum(sum(f.nbytes for f in v) for v in _cache.values()) + size > MAX_BYTES or len(_cache) >= 4):
            _cache.popitem(last=False)
        if size <= MAX_BYTES:
            _cache[key] = output
    return output
