"""Directional stochastic blending and content-aware quilting of slope/heat fields."""
from collections import OrderedDict
from threading import RLock
import hashlib
import numpy as np
from scipy.ndimage import map_coordinates, gaussian_filter, distance_transform_edt

_cache=OrderedDict()
_lock=RLock()
MAX_BYTES=96*1024*1024


def source_fields(n,heat,span,footprint=1,flip_y=False,crop_scale=.5):
    sx=-n[...,0]/np.maximum(n[...,2],.15)
    sz=-n[...,1]/np.maximum(n[...,2],.15)*(-1 if flip_y else 1)
    fields=np.stack((sx,sz,heat),axis=-1).astype(np.float32)
    # A source crop covers roughly half the original image. Filter before shrinking.
    sigma=max(0,(min(n.shape[:2])*crop_scale*footprint/span-1)*.5)
    if sigma>.1:fields=gaussian_filter(fields,(sigma,sigma,0),mode='nearest')
    return fields


_axis_cache=OrderedDict()


def source_orientation(n):
    """Spatial ridge axis and Y-convention conversion, independent of RGB signs."""
    key=id(n)
    with _lock:
        cached=_axis_cache.get(key)
        if cached is not None and cached[0] is n:return cached[1]
    stride=max(1,int(np.ceil(max(n.shape[:2])/256)))
    slopes=-n[...,:2]/np.maximum(n[...,2:3],.15)
    if stride>1:slopes=gaussian_filter(slopes,(stride*.5,stride*.5,0),mode='nearest')
    slopes=slopes[::stride,::stride].astype(np.float64)
    dx=np.gradient(slopes,axis=1);dz=np.gradient(slopes,axis=0)
    xx,xz,zz=np.sum(dx*dx),np.sum(dx*dz),np.sum(dz*dz)
    # A global green flip changes vector signs but not the image's ridge axis.
    axis=0. if np.hypot(xx-zz,2*xz)<max(1e-10,.08*(xx+zz)) else float(.5*np.arctan2(2*xz,xx-zz))
    # For a height-derived normal, d(sx)/dz = d(sz)/dx. Opposite signs identify
    # the other common tangent-space Y convention. Ambiguous maps stay unchanged.
    cross_x=dz[...,0];cross_z=dx[...,1]
    norm=float(np.sqrt(np.sum(cross_x**2)*np.sum(cross_z**2)))
    agreement=float(np.sum(cross_x*cross_z))/max(norm,1e-12)
    flip=bool(norm>1e-8 and agreement<-.25)
    result=(axis,flip)
    with _lock:
        _axis_cache[key]=(n,result)
        while len(_axis_cache)>8:_axis_cache.popitem(last=False)
    return result


def dominant_wave_axis(n,flip_y=False):
    """Axis across visible source crests, modulo 180 degrees; Y-flip invariant."""
    return source_orientation(n)[0]


def ocean_y_flip(n,reverse=False):
    return source_orientation(n)[1] ^ bool(reverse)


def characteristic_wavelength(n,span):
    """Energy-weighted source wavelength, converted from pixels to world blocks."""
    field=n[...,0]+n[...,1]
    stride=max(1,int(np.ceil(max(field.shape)/256)))
    field=field[::stride,::stride];h,w=field.shape
    field=(field-field.mean())*np.hanning(h)[:,None]*np.hanning(w)[None,:]
    power=abs(np.fft.rfft2(field))**2
    freq=np.hypot(np.fft.fftfreq(h)[:,None],np.fft.rfftfreq(w)[None,:])
    power[freq<2/max(h,w)]=0
    mean=float((power*freq).sum()/max(1e-12,power.sum()))
    return float(np.clip(span/max(2,mean*min(h,w)*.5),3,256))


def _hash(x,z,seed):
    with np.errstate(over='ignore'):
        key=x.astype(np.uint64)*np.uint64(0x9e3779b185ebca87)^z.astype(np.uint64)*np.uint64(0xc2b2ae3d27d4eb4f)^np.uint64(seed)
        key^=key>>30;key*=np.uint64(0xbf58476d1ce4e5b9);key^=key>>27;key*=np.uint64(0x94d049bb133111eb);key^=key>>31
    return key


def directional_patches(fields,u,v,span,seed):
    """Unrotated source crops; blend only in narrow overlaps, never whole patches.

    Span is the source's shorter side in blocks. Fixed world-space cells retain
    crop stability when a selection grows. Slopes retain their authored strength.
    """
    step=span*.75;outer=span*.425;inner=step-outer
    ix=np.floor(u/step).astype(np.int64);iz=np.floor(v/step).astype(np.int64)
    height,width=fields.shape[:2];side=min(height,width)-1
    out=np.zeros((*u.shape,3),np.float32);total=np.zeros_like(u)
    def weight(distance):
        t=np.clip((np.abs(distance)-inner)/(outer-inner),0,1)
        return 1-t*t*(3-2*t)
    for dz in (0,1):
        for dx in (0,1):
            cx,cz=ix+dx,iz+dz;key=_hash(cx,cz,seed)
            px,pz=u-cx*step,v-cz*step;w=weight(px)*weight(pz)
            ox=(((key>>2)&65535)/65535*2-1)*((width-1)*.5-outer/span*side)
            oz=(((key>>18)&65535)/65535*2-1)*((height-1)*.5-outer/span*side)
            at=[(height-1)*.5+pz/span*side+oz,(width-1)*.5+px/span*side+ox]
            for k in range(3):out[...,k]+=w*map_coordinates(fields[...,k],at,order=1,mode='nearest',prefilter=False)
            total+=w
    return out/np.maximum(total[...,None],1e-8)


def stochastic(fields,u,v,span,seed,preserve_direction=False):
    """Three-way triangular blending; normalize centred variance, not normal RGB."""
    step=span*.52
    qx=u/step-v/(step*np.sqrt(3));qz=2*v/(step*np.sqrt(3))
    ix=np.floor(qx).astype(np.int64);iz=np.floor(qz).astype(np.int64)
    fx=qx-ix;fz=qz-iz;upper=fx+fz>1
    coords=[(ix+upper,iz+upper),(ix+1,iz),(ix,iz+1)]
    weights=[np.where(upper,fx+fz-1,1-fx-fz),np.where(upper,1-fz,fx),np.where(upper,1-fx,fz)]
    weights=[np.maximum(0,w)**2 for w in weights];total=sum(weights)
    weights=[w/np.maximum(total,1e-8) for w in weights]
    mean=fields.mean(axis=(0,1));out=np.zeros((*u.shape,3),np.float32);means=np.zeros_like(out)
    for (cx,cz),weight in zip(coords,weights):
        key=_hash(cx,cz,seed)
        rot=np.zeros_like(cx) if preserve_direction else (key&3).astype(int)
        ca=np.array([1,0,-1,0])[rot];sa=np.array([0,1,0,-1])[rot]
        crop=.5 if preserve_direction else .35+.25*((key>>2)&65535)/65535
        ox=(((key>>18)&65535)/65535-.5)*(1-1.2*crop)
        oz=(((key>>34)&65535)/65535-.5)*(1-1.2*crop)
        x=(u-step*(cx+cz*.5))/span;z=(v-step*cz*np.sqrt(3)*.5)/span
        side=min(fields.shape[:2])
        su=(x*ca+z*sa)*crop*side/fields.shape[1]+.5+ox
        sv=(-x*sa+z*ca)*crop*side/fields.shape[0]+.5+oz
        at=[np.clip(sv,0,1)*(fields.shape[0]-1),np.clip(su,0,1)*(fields.shape[1]-1)]
        px,pz,h=[map_coordinates(fields[...,i],at,order=1,mode='nearest',prefilter=False) for i in range(3)]
        mx=(mean[0]*ca-mean[1]*sa)*crop;mz=(mean[0]*sa+mean[1]*ca)*crop
        centred=np.stack(((px*ca-pz*sa)*crop-mx,(px*sa+pz*ca)*crop-mz,h-mean[2]),axis=-1)
        out+=weight[...,None]*centred
        means+=weight[...,None]*np.stack((mx,mz,np.full_like(mx,mean[2])),axis=-1)
    out=means+out/np.sqrt(sum(w*w for w in weights))[...,None]
    out[...,2]=np.clip(out[...,2],0,1)
    return out


def _cut(error):
    """Minimum-error vertical boundary through an overlap strip."""
    cost=error.copy();back=np.zeros(error.shape,np.int8)
    for y in range(1,len(cost)):
        prev=np.pad(cost[y-1],1,constant_values=np.inf)
        choices=np.stack((prev[:-2],prev[1:-1],prev[2:]))
        choice=np.argmin(choices,axis=0);back[y]=choice-1
        cost[y]+=np.min(choices,axis=0)
    x=int(np.argmin(cost[-1]));path=np.empty(len(cost),int)
    for y in range(len(cost)-1,-1,-1):path[y]=x;x+=int(back[y,x])
    return path


def _quilting(fields,height,width,patch,span,seed,check,progress):
    rng=np.random.default_rng(seed);overlap=max(6,patch//5);step=patch-overlap
    out=np.zeros((height+patch,width+patch,3),np.float32);recent=[]
    std=np.maximum(fields.std(axis=(0,1)),.04)
    positions=[(y,x) for y in range(0,height,step) for x in range(0,width,step)]
    for index,(y,x) in enumerate(positions):
        check();old=out[y:y+patch,x:x+patch];best=None;best_score=np.inf;best_id=None
        for _ in range(10):
            check();rotation=int(rng.integers(4));crop=float(np.clip((patch-1)/span*rng.uniform(.8,1.2),.04,.85));ox,oz=rng.uniform(0,1-crop,2)
            signature=(rotation,int(ox*12),int(oz*12),int(crop*12))
            yy,xx=np.mgrid[:patch,:patch].astype(np.float32)
            side=min(fields.shape[:2])-1
            at=[oz*(fields.shape[0]-1)+yy/(patch-1)*crop*side,ox*(fields.shape[1]-1)+xx/(patch-1)*crop*side]
            candidate=np.stack([map_coordinates(fields[...,k],at,order=1,mode='nearest',prefilter=False) for k in range(3)],axis=-1)
            candidate=np.rot90(candidate,rotation).copy()
            px=candidate[...,0].copy();pz=candidate[...,1].copy()
            ca=(1,0,-1,0)[rotation];sa=(0,1,0,-1)[rotation]
            candidate[...,0]=(px*ca+pz*sa)*.5;candidate[...,1]=(-px*sa+pz*ca)*.5
            error=np.mean(((candidate-old)/std)**2,axis=-1)
            score=(float(error[:,:overlap].mean()) if x else 0)+(float(error[:overlap].mean()) if y else 0)
            if signature in recent:score+=2
            if score<best_score:best=candidate;best_score=score;best_id=signature
        mask=np.ones((patch,patch),bool);error=np.mean(((best-old)/std)**2,axis=-1)
        if x:mask[:,:overlap]=np.arange(overlap)[None,:]>=_cut(error[:,:overlap])[:,None]
        if y:mask[:overlap]&=np.arange(overlap)[:,None]>=_cut(error[:overlap].T)[None,:]
        # Narrow feathering keeps normals continuous without washing out entire patches.
        if x or y:
            signed=distance_transform_edt(mask)-distance_transform_edt(~mask)
            alpha=np.clip(.5+signed/4,0,1)[...,None]
        else:alpha=1
        out[y:y+patch,x:x+patch]=old*(1-alpha)+best*alpha
        recent.append(best_id);recent=recent[-16:]
        if progress:progress(index+1,len(positions))
    return out[:height,:width].copy()


def sample(n,heat,u,v,span,seed,method='stochastic',flip_y=False,footprint=1,preserve_direction=False,check=lambda:None,progress=None):
    digest=hashlib.blake2b(n.tobytes()+heat.tobytes(),digest_size=12).digest()
    coordinates=hashlib.blake2b(u.tobytes()+v.tobytes(),digest_size=12).digest()
    key=(digest,coordinates,u.shape,span,seed,method,flip_y,footprint,preserve_direction)
    check()
    with _lock:
        if key in _cache:
            _cache.move_to_end(key);return tuple(_cache[key][...,i] for i in range(3))
    fields=source_fields(n,heat,span,footprint,flip_y)
    if method=='quilt' and not preserve_direction:
        xmin=int(np.floor(u.min()))-2;zmin=int(np.floor(v.min()))-2
        width=int(np.ceil(u.max()))-xmin+3;height=int(np.ceil(v.max()))-zmin+3
        patch=int(np.clip(span*.65,24,160))
        atlas=_quilting(fields,height,width,patch,span,seed,check,progress)
        out=np.stack([map_coordinates(atlas[...,i],[(v-zmin),(u-xmin)],order=1,mode='nearest',prefilter=False) for i in range(3)],axis=-1)
    else:
        out=np.empty((*u.shape,3),np.float32)
        for first in range(0,len(u),32):
            check();sl=slice(first,first+32)
            # Preserve existing span-to-feature scale: the old sampler used half
            # the source per span. Larger coherent crops replace its superposition.
            out[sl]=directional_patches(fields,u[sl],v[sl],span*2,seed) if preserve_direction else stochastic(fields,u[sl],v[sl],span,seed)
            if progress:progress(min(first+32,len(u)),len(u))
    check();out.flags.writeable=False
    with _lock:
        while _cache and (sum(a.nbytes for a in _cache.values())+out.nbytes>MAX_BYTES or len(_cache)>=4):_cache.popitem(last=False)
        if out.nbytes<=MAX_BYTES:_cache[key]=out
    return tuple(out[...,i] for i in range(3))
