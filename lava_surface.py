"""User-supplied tangent-space normal baselines sampled locally for lava."""
from pathlib import Path
from functools import lru_cache
import sys,math
import normal_maps
import texture_synthesis
import surface_relief
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

BASELINES=(('smooth','Smooth flow'),('crust','Broken crust'),('folded','Folded flow'),
    ('cracked','Cracked plates'),('turbulent','Turbulent flow'),('slabs','Fractured slabs'),
    ('eddies','Soft eddies'),('fine_cracks','Fine cracks'),('jagged','Jagged crust'))

@lru_cache(maxsize=9)
def baseline(name):
    if name not in dict(BASELINES):raise ValueError('Unknown lava normal baseline.')
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
    rgb=np.asarray(Image.open(root/'lava_normals'/(name+'.png')).convert('RGB'),dtype=np.float32)/255
    n=rgb*2-1;n/=np.maximum(np.linalg.norm(n,axis=-1,keepdims=True),1e-6)
    rough=gaussian_filter(1-n[:,:,2],1)
    lo,hi=np.percentile(rough,[5,95]);rough=np.clip((rough-lo)/max(.01,hi-lo),0,1)
    heat=1-rough if name=='crust' else rough
    return n,heat

def prepare(f,a,size=None,check=lambda:None,progress=None):
    w,l=f['settings']['width'],f['settings']['length'];ow,ol=size or (w,l)
    z,x=np.mgrid[:ol,:ow].astype(np.float32);x=(x+.5)*w/ow-.5;z=(z+.5)*l/ol-.5
    if a['normal_source']=='imported':n,heat=normal_maps.load(a['normal_map_path'])
    else:n,heat=baseline(a['lava_pattern'])
    check()
    if a['lava_heat_mode']=='valleys':heat=normal_maps.valley_heat(n)
    span=a['lava_scale'];angle=math.radians(f['settings']['direction'] if a['link_direction'] else a['wind_direction'])
    angle+=math.radians(a.get('normal_rotation',0.))
    ca,sa=math.cos(angle),math.sin(angle)
    u=x*ca+z*sa;v=-x*sa+z*ca
    phase=(a['seed']%10007)/10007*2*np.pi
    # Smooth domain distortion preserves larger folds; no white-noise overlay.
    amp=a['lava_distortion']*span*.08;k=2*np.pi/(span*1.7)
    du=amp*np.sin(v*k+phase);dv=amp*np.sin(u*k*.73+phase*1.7)
    qu=u+du;qv=v+dv
    if a['lava_sampling']=='legacy':
        fields=[np.empty_like(qu) for _ in range(3)]
        for first in range(0,ol,32):
            check();sl=slice(first,first+32)
            sampled=normal_maps.patches(n,heat,qu[sl],qv[sl],span,a['seed'],a['lava_flip_y'])
            for target,value in zip(fields,sampled):target[sl]=value
            if progress:progress(min(first+32,ol),ol)
        sx,sz,h=fields
    else:
        sx,sz,h=texture_synthesis.sample(n,heat,qu,qv,span,a['seed'],a['lava_sampling'],a['lava_flip_y'],max(w/ow,l/ol),check=check,progress=progress)
    gx=sx+sz*amp*k*.73*np.cos(u*k*.73+phase*1.7)
    gz=sz+sx*amp*k*np.cos(v*k+phase)
    normals=np.stack([-(gx*ca-gz*sa)*a['normal_strength'],
                      -(gx*sa+gz*ca)*a['normal_strength'],np.ones_like(x)],-1)
    normals/=np.linalg.norm(normals,axis=-1,keepdims=True)
    relief=surface_relief.from_slopes(-normals[...,0]/np.maximum(normals[...,2],.15),-normals[...,1]/np.maximum(normals[...,2],.15),24,max(w/ow,l/ol))
    if a['invert_normals']:normals[:,:,:2]*=-1
    if a['invert_normals']:h=1-h
    threshold=a['lava_crust']
    t=np.clip((h-(threshold-.2))/.4,0,1);hot=t*t*(3-2*t)*(.35+.65*h)
    if threshold==0:hot[:]=1
    if threshold==1:hot[:]=0
    masks=np.concatenate([np.stack([np.zeros_like(x),relief,hot,np.ones_like(x)],-1),normals*.5+.5],-1)
    return normals.astype(np.float32),masks.astype(np.float32)

def shade(normals,heat,a):
    import colour
    cold,molten,peak=np.array([colour.hex_rgb(a[k]) for k in ('lava_cold','lava_hot','lava_peak')],np.float32)/255
    glow=heat*(.35+.65*a['lava_glow'])
    hot=np.clip((heat-.55)/.45,0,1)**2*a['lava_glow']
    crust=cold*(.55+.45*normals[...,2:3])
    rgb=crust+(molten-crust)*glow[...,None]
    rgb=rgb*(1-hot[...,None])+peak*hot[...,None]
    return np.clip(np.round(rgb*255),0,255).astype(np.uint8)
