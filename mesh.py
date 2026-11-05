"""Exact exposed faces, merged into rectangles without losing thin coatings."""
import numpy as np
import math
from colour import catalogue


def rectangles(plane):
    """Merge equal horizontal material runs across successive rows."""
    active={}
    for row_index,row in enumerate(plane):
        changes=np.flatnonzero(np.diff(np.pad(row.astype(np.int16),(1,1))))
        current={}
        for start,end in zip(changes[:-1],changes[1:]):
            state=int(row[start])
            if not state: continue
            key=(int(start),int(end),state)
            current[key]=active.pop(key,row_index)
        for (start,end,state),first in active.items():
            yield first,row_index,start,end,state
        active=current
    for (start,end,state),first in active.items():
        yield first,len(plane),start,end,state


def build(result):
    if 'voxels' not in result:
        s=result['settings']; h=np.array(result['heights']).reshape(s['length'],s['width'])
        bottom=np.array(result['bottoms']).reshape(h.shape)
        yy=np.arange(int(h.max())+1)[:,None,None]
        voxels=((yy>=bottom)&(yy<=h)).astype(np.uint8)
        result={**result,'voxels':voxels,'palette':[{'id':'minecraft:air'},
            {'id':'minecraft:'+s['block']+'_concrete'}]}
    voxels=result['voxels']
    height,length,width=voxels.shape
    if max(width,length)>258 or (height>50 and max(width,length)>130):
        return simplified(result)
    solid=voxels!=0
    lookup={b['id']:b for b in catalogue()}
    top=np.array([lookup.get(b['id'],{}).get('top_rgb',[120,120,120]) for b in result['palette']])
    sides=np.array([lookup.get(b['id'],{}).get('side_rgb',[120,120,120]) for b in result['palette']])
    vertices=[]; colours=[]; directions=[]
    for face,axis,positive in [(0,0,True),(1,2,True),(2,2,False),(3,1,True),(4,1,False)]:
        for position in range(voxels.shape[axis]):
            plane=np.take(voxels,position,axis=axis)
            next_position=position+(1 if positive else -1)
            if 0<=next_position<voxels.shape[axis]:
                plane=np.where(np.take(solid,next_position,axis=axis),0,plane)
            if not np.any(plane): continue
            p=position+int(positive)
            for a0,a1,b0,b1,state in rectangles(plane):
                if axis==0: points=[(b0,p,a0),(b1,p,a0),(b1,p,a1),(b0,p,a1)]
                elif axis==2: points=[(p,a0,b0),(p,a0,b1),(p,a1,b1),(p,a1,b0)]
                else: points=[(b0,a0,p),(b1,a0,p),(b1,a1,p),(b0,a1,p)]
                vertices.append(points)
                rgb=(top if face==0 else sides)[state]
                colours.append(np.clip(rgb*[1,.70,.70,.85,.85][face],0,255))
                directions.append(face)
    verts=np.array(vertices,dtype=np.float32).reshape(-1,4,3)
    verts[:,:,0]-=width/2; verts[:,:,2]-=length/2
    return {'vertices':verts,'centres':verts.mean(axis=1),'rgb':np.array(colours,dtype=np.uint8),
        'directions':np.array(directions,dtype=np.uint8),'step':1,'simplified':False,'width':width,'length':length,'height':height}


def simplified(result, resolution=80):
    """Top-envelope preview for expensive builds; never used for placement/export.

    The exact voxel grid supplies top heights and materials. Interior cavities
    and small features are simplified to keep orbiting responsive.
    """
    v=result['voxels']; height,length,width=v.shape
    step=max(2,math.ceil(max(width,length)/resolution))
    xs=np.arange(0,width,step); zs=np.arange(0,length,step)
    sample=v[:,::step,::step]
    occupied=sample!=0
    top=height-np.argmax(occupied[::-1],axis=0)
    top[~occupied.any(axis=0)]=0
    zz,xx=np.indices(top.shape)
    ids=sample[np.maximum(top-1,0),zz,xx]
    lookup={b['id']:b for b in catalogue()}
    top_rgb=np.array([lookup.get(b['id'],{}).get('top_rgb',[120,120,120]) for b in result['palette']])
    side_rgb=np.array([lookup.get(b['id'],{}).get('side_rgb',[120,120,120]) for b in result['palette']])
    padded=np.pad(top,1)
    neighbours=[None,padded[1:-1,2:],padded[1:-1,:-2],padded[2:,1:-1],padded[:-2,1:-1]]
    vertices=[]; colours=[]; directions=[]
    for face,neighbor in enumerate(neighbours):
        mask=top>0 if face==0 else top>neighbor
        z,x=np.where(mask)
        x0=xs[x]; x1=np.minimum(x0+step,width)
        z0=zs[z]; z1=np.minimum(z0+step,length)
        hi=top[z,x]; lo=np.zeros_like(hi) if face==0 else neighbor[z,x]
        if face==0: points=[(x0,hi,z0),(x1,hi,z0),(x1,hi,z1),(x0,hi,z1)]
        elif face==1: points=[(x1,lo,z0),(x1,lo,z1),(x1,hi,z1),(x1,hi,z0)]
        elif face==2: points=[(x0,lo,z0),(x0,lo,z1),(x0,hi,z1),(x0,hi,z0)]
        elif face==3: points=[(x0,lo,z1),(x1,lo,z1),(x1,hi,z1),(x0,hi,z1)]
        else: points=[(x0,lo,z0),(x1,lo,z0),(x1,hi,z0),(x0,hi,z0)]
        vertices.append(np.stack([np.stack(p,axis=-1) for p in points],axis=1))
        colours.append(np.clip((top_rgb if face==0 else side_rgb)[ids[z,x]]*[1,.70,.70,.85,.85][face],0,255))
        directions.append(np.full(len(z),face,dtype=np.uint8))
    verts=np.concatenate(vertices).astype(np.float32)
    verts[:,:,0]-=width/2; verts[:,:,2]-=length/2
    return {'vertices':verts,'centres':verts.mean(axis=1),'rgb':np.concatenate(colours).astype(np.uint8),
        'directions':np.concatenate(directions),'step':step,'simplified':True,'width':width,'length':length,'height':height}


def triangle_data(mesh):
    """Interleaved positions and face colours, constructed once off the UI thread."""
    vertices=mesh['vertices'][:,[0,1,2,0,2,3],:]
    data=np.empty((len(vertices),6,6),dtype=np.float32)
    data[:,:,:3]=vertices
    if mesh.get('textured'):
        shade=np.array([1,.70,.70,.85,.85],dtype=np.float32)[mesh['directions']]
        data[:,:,3:]=shade[:,None,None]
    else:
        data[:,:,3:]=mesh['rgb'][:,None,:]/255
    return data.tobytes()
