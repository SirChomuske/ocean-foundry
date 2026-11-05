"""Vectorized preview meshes shared by generated and reference surfaces."""
import numpy as np

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

def layer_mesh(v, palette_rgb, surface_rgb=None, side_rgb=None, glass_states=None):
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
        rgb = surface_rgb[z, x] if face == 0 and surface_rgb is not None else (side_rgb if face and side_rgb is not None else palette_rgb)[v[y, z, x]]*255
        if face and surface_rgb is not None and glass_states is not None:
            glass=glass_states[v[y,z,x]]
            rgb=np.where(glass[:,None],surface_rgb[z,x],rgb)
        colours.append(rgb*[1,.70,.70,.85,.85][face])
        directions.append(np.full(len(y), face, dtype=np.uint8))
    verts = np.concatenate(vertices).astype(np.float32)
    verts[:, :, 0] -= width/2
    verts[:, :, 2] -= length/2
    return dict(vertices=verts, centres=verts.mean(axis=1), rgb=np.concatenate(colours).astype(np.uint8),
                directions=np.concatenate(directions), step=1, simplified=False,
                width=width, length=length, height=height)
