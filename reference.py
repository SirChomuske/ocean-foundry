"""Fixed reference benchmarks; approximate preview, exact layered exports."""
from pathlib import Path
import gzip
import json
import math
import struct
import sys
import time
import numpy as np
import mesh
from ocean import _compound, _int, _string, _tag
from voxel_exports import listing, packed_contiguous, state_payload

ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'reference_tests'
LAYERS = [('combined', 'Combined appearance'), ('foundation', 'Concrete support'),
          ('solid', 'Solid colour'), ('glass', 'All glass'),
          ('glass_1', 'Glass layer 1'), ('glass_2', 'Glass layer 2'), ('glass_3', 'Glass layer 3')]


def manifest():
    return json.loads((ASSETS / 'manifest.json').read_text(encoding='utf-8'))


def load(key):
    if key not in {p['key'] for p in manifest()}:
        raise ValueError('Unknown reference patch.')
    with np.load(ASSETS / (key + '.npz'), allow_pickle=False) as data:
        patch = {name: data[name].copy() for name in ('voxels', 'base', 'top', 'rgb', 'alpha')}
        patch['palette'] = json.loads(str(data['palette_json']))
        patch['meta'] = json.loads(str(data['metadata_json']))
    return patch


def layer_volume(patch, layer):
    if layer not in dict(LAYERS):
        raise ValueError('Unknown reference layer.')
    v, base = patch['voxels'], patch['base']
    if layer == 'combined':
        return v.copy()
    yy = np.arange(v.shape[0])[:, None, None]
    if layer == 'foundation': mask = yy < base
    elif layer == 'solid': mask = yy == base
    elif layer == 'glass': mask = yy > base
    else: mask = yy == base + int(layer[-1])
    return np.where(mask, v, 0).astype(np.uint8)


def composite(patch):
    """Top-face diagnostic: one visible face per adjacent same-colour run."""
    v, base = patch['voxels'], patch['base']
    zz, xx = np.indices(base.shape)
    rgb, alpha = patch['rgb'], patch['alpha']
    result = rgb[v[base, zz, xx]].copy()
    padded = np.pad(v, ((0, 4), (0, 0), (0, 0)))
    for i in range(1, 4):
        state = padded[base+i, zz, xx]
        above = padded[base+i+1, zz, xx]
        opacity = (alpha[state] * (state != above))[..., None]
        result = result * (1-opacity) + rgb[state] * opacity
    return np.clip(result * 255, 0, 255).astype(np.uint8)


def envelope(top, colours, height):
    """Approximate coloured exterior for composite inspection, never exported."""
    length, width = top.shape
    padded = np.pad(top, 1)
    neighbours = [None, padded[1:-1, 2:], padded[1:-1, :-2], padded[2:, 1:-1], padded[:-2, 1:-1]]
    vertices, rgb, directions = [], [], []
    for face, neighbour in enumerate(neighbours):
        z, x = np.where(top > 0 if face == 0 else top > neighbour)
        hi = top[z, x]
        lo = np.zeros_like(hi) if face == 0 else neighbour[z, x]
        if face == 0: points = [(x, hi, z), (x+1, hi, z), (x+1, hi, z+1), (x, hi, z+1)]
        elif face == 1: points = [(x+1, lo, z), (x+1, lo, z+1), (x+1, hi, z+1), (x+1, hi, z)]
        elif face == 2: points = [(x, lo, z), (x, lo, z+1), (x, hi, z+1), (x, hi, z)]
        elif face == 3: points = [(x, lo, z+1), (x+1, lo, z+1), (x+1, hi, z+1), (x, hi, z+1)]
        else: points = [(x, lo, z), (x+1, lo, z), (x+1, hi, z), (x, hi, z)]
        vertices.append(np.stack([np.stack(p, axis=-1) for p in points], axis=1))
        rgb.append(colours[z, x] * [1, .70, .70, .85, .85][face])
        directions.append(np.full(len(z), face, dtype=np.uint8))
    verts = np.concatenate(vertices).astype(np.float32)
    verts[:, :, 0] -= width/2
    verts[:, :, 2] -= length/2
    return dict(vertices=verts, centres=verts.mean(axis=1), rgb=np.concatenate(rgb).astype(np.uint8),
                directions=np.concatenate(directions), step=1, simplified=False,
                width=width, length=length, height=height)


def layer_mesh(v, palette_rgb, surface_rgb=None):
    """Vectorized exposed faces for small fixed patches; no Python face loop."""
    height, length, width = v.shape
    occupied = np.pad(v != 0, 1)
    neighbours = [occupied[2:, 1:-1, 1:-1], occupied[1:-1, 1:-1, 2:],
                  occupied[1:-1, 1:-1, :-2], occupied[1:-1, 2:, 1:-1], occupied[1:-1, :-2, 1:-1]]
    vertices, colours, directions = [], [], []
    for face, neighbour in enumerate(neighbours):
        y, z, x = np.where((v != 0) & ~neighbour)
        if face == 0: points = [(x,y+1,z), (x+1,y+1,z), (x+1,y+1,z+1), (x,y+1,z+1)]
        elif face == 1: points = [(x+1,y,z), (x+1,y,z+1), (x+1,y+1,z+1), (x+1,y+1,z)]
        elif face == 2: points = [(x,y,z), (x,y,z+1), (x,y+1,z+1), (x,y+1,z)]
        elif face == 3: points = [(x,y,z+1), (x+1,y,z+1), (x+1,y+1,z+1), (x,y+1,z+1)]
        else: points = [(x,y,z), (x+1,y,z), (x+1,y+1,z), (x,y+1,z)]
        vertices.append(np.stack([np.stack(p, axis=-1) for p in points], axis=1))
        rgb = surface_rgb[z, x] if face == 0 and surface_rgb is not None else palette_rgb[v[y, z, x]]*255
        colours.append(rgb*[1,.70,.70,.85,.85][face])
        directions.append(np.full(len(y), face, dtype=np.uint8))
    verts = np.concatenate(vertices).astype(np.float32)
    verts[:, :, 0] -= width/2
    verts[:, :, 2] -= length/2
    return dict(vertices=verts, centres=verts.mean(axis=1), rgb=np.concatenate(colours).astype(np.uint8),
                directions=np.concatenate(directions), step=1, simplified=False,
                width=width, length=length, height=height)


def prepare_views(key):
    start = time.perf_counter()
    patch = load(key)
    height, length, width = patch['voxels'].shape
    palette = [{**state, 'top_rgb': (rgb*255).tolist(), 'side_rgb': (rgb*255).tolist()}
               for state, rgb in zip(patch['palette'], patch['rgb'])]
    views = {}
    for layer, title in LAYERS:
        v = layer_volume(patch, layer)
        occupied = v != 0
        top = height - np.argmax(occupied[::-1], axis=0)
        top[~occupied.any(axis=0)] = 0
        zz, xx = np.indices(top.shape)
        pixels = (patch['rgb'][v[np.maximum(top-1, 0), zz, xx]]*255).astype(np.uint8)
        pixels[top == 0] = [16, 29, 41]
        if layer == 'combined': pixels = composite(patch)
        result = dict(settings=dict(width=width, length=length), heights=(top-1).ravel(),
                      voxels=v, palette=palette, target_rgb=pixels, block_rgb=pixels,
                      stats={'blocks': int(np.count_nonzero(v))},
                      preview_note=('Approximate glass colours · Exact exterior shape' if layer == 'combined'
                                    else 'Exact layer geometry · Glass shown opaque for inspection'))
        result['mesh'] = layer_mesh(v, patch['rgb'], pixels if layer == 'combined' else None)
        # A small interaction mesh keeps the software fallback usable too.
        step = 2
        small = envelope(top[::step, ::step], pixels[::step, ::step], height)
        small['vertices'][:, :, [0, 2]] *= step
        small['centres'] = small['vertices'].mean(axis=1)
        small.update(width=width, length=length, step=step, simplified=True)
        result['interaction_mesh'] = small
        result['gpu_vertices'] = mesh.triangle_data(result['mesh'])
        views[layer] = result
    return dict(patch=patch, views=views, prepare_ms=(time.perf_counter()-start)*1000)


def litematic(patch, layer='combined'):
    """All layers retain the same origin and bounds, including empty spaces."""
    v = layer_volume(patch, layer)
    palette = patch['palette']
    height, length, width = v.shape
    bits = max(2, math.ceil(math.log2(len(palette))))
    words = packed_contiguous(v, bits)
    def vec(name, x, y, z):
        return _compound(name, _int('x', x), _int('y', y), _int('z', z))
    region = _compound('ocean', vec('Position', 0, 0, 0), vec('Size', width, height, length),
        listing('BlockStatePalette', 10, [state_payload(s) for s in palette]),
        _tag(12, 'BlockStates', struct.pack('>i', len(words)) + words.astype('>u8').tobytes()),
        *[listing(n, 10, []) for n in ('Entities', 'TileEntities', 'PendingBlockTicks', 'PendingFluidTicks')])
    now = int(time.time()*1000)
    meta = _compound('Metadata', _string('Name', patch['meta']['title']+' / '+dict(LAYERS)[layer]),
        _string('Author', 'Ocean Foundry reference extraction'),
        _string('Description', 'Exact reference crop. Local source origin '+str(patch['meta']['source_local_origin_xyz'])+
                '. All layers share bounds. Use ignore-air when overlaying separate layers. Java 26.1.2.'),
        _int('RegionCount', 1), _int('TotalVolume', v.size), _int('TotalBlocks', int(np.count_nonzero(v))),
        _tag(4, 'TimeCreated', struct.pack('>q', now)), _tag(4, 'TimeModified', struct.pack('>q', now)),
        vec('EnclosingSize', width, height, length))
    return gzip.compress(_compound('', _int('Version', 6), _int('SubVersion', 1),
        _int('MinecraftDataVersion', patch['meta']['data_version']), meta, _compound('Regions', region)), mtime=0)
