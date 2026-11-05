"""Local normal-image loading and continuous, seeded patch sampling."""
from pathlib import Path
from functools import lru_cache
import hashlib
import sys
import numpy as np
from PIL import Image, ImageOps
from scipy.ndimage import map_coordinates, gaussian_filter


ROOT=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent


def resolve_path(path):
    path=Path(path)
    if not path.is_absolute():return ROOT/path
    if path.exists():return path
    recovered=ROOT/'normal_maps'/path.name
    return recovered if recovered.exists() else path


def portable_path(path):
    path=Path(path).resolve()
    try:return path.relative_to(ROOT.resolve()).as_posix()
    except ValueError:return str(path)


def read_image(path):
    with Image.open(resolve_path(path)) as source:
        if source.width * source.height > 16777216:
            raise ValueError('Use a normal map up to 16 megapixels.')
        if min(source.size) < 8:
            raise ValueError('Normal maps must be at least 8 pixels in each direction.')
        if source.mode not in ('RGB','RGBA'):
            raise ValueError('Choose an RGB tangent-space normal map, not a height/grayscale image.')
        image=ImageOps.exif_transpose(source).convert('RGB')
        image.thumbnail((2048,2048),Image.Resampling.LANCZOS)
        return image.copy()


def import_image(path,folder):
    """Store a normalized local copy so moving the original cannot break a project."""
    image=read_image(path)
    digest=hashlib.sha256(image.tobytes()+str(image.size).encode()).hexdigest()[:24]
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    destination=folder/(digest+'.png')
    if not destination.exists():image.save(destination)
    return portable_path(destination)


@lru_cache(maxsize=6)
def load(path):
    rgb=np.asarray(read_image(path),dtype=np.float32)/255
    n=rgb*2-1
    n[:,:,2]=np.maximum(n[:,:,2],.05)
    n/=np.maximum(np.linalg.norm(n,axis=-1,keepdims=True),1e-6)
    rough=gaussian_filter(1-n[:,:,2],1)
    lo,hi=np.percentile(rough,[5,95])
    return n,np.clip((rough-lo)/max(.01,hi-lo),0,1)


def patches(n,heat,u,v,span,seed,flip_y=False,*,preserve_direction=False):
    """Four overlapping source patches, with zero weight/slope at their boundaries.

    No reflected or wrapped source edges are sampled. World-cell hashes select
    crops and quarter-turn rotations; growing the area does not rescale the field.
    Directional maps use translations at a fixed scale, without patch rotations.
    """
    step=span*.5
    ix=np.floor(u/step).astype(np.int64);iz=np.floor(v/step).astype(np.int64)
    sx=np.zeros_like(u,dtype=np.float32);sz=sx.copy();h=sx.copy()
    source_x=-n[:,:,0]/np.maximum(n[:,:,2],.15)
    source_z=-n[:,:,1]/np.maximum(n[:,:,2],.15)*(-1 if flip_y else 1)
    for dz in (0,1):
        for dx in (0,1):
            tx=ix+dx;tz=iz+dz
            key=(tx.astype(np.uint64)*np.uint64(0x9e3779b185ebca87))^(tz.astype(np.uint64)*np.uint64(0xc2b2ae3d27d4eb4f))^np.uint64(seed)
            key^=key>>30;key*=np.uint64(0xbf58476d1ce4e5b9);key^=key>>27;key*=np.uint64(0x94d049bb133111eb);key^=key>>31
            rotation=np.zeros_like(key,dtype=int) if preserve_direction else (key&3).astype(int)
            ca=np.array([1,0,-1,0],np.float32)[rotation];sa=np.array([0,1,0,-1],np.float32)[rotation]
            crop=.75 if preserve_direction else .65+.3*((key>>2)&65535).astype(np.float32)/65535
            offx=(((key>>18)&65535).astype(np.float32)/65535-.5)*(1-crop)
            offz=(((key>>34)&65535).astype(np.float32)/65535-.5)*(1-crop)
            x=(u-tx*step)/span;z=(v-tz*step)/span
            weight=(np.cos(np.pi*x)*np.cos(np.pi*z))**2
            su=(x*ca+z*sa)*crop+.5+offx
            sv=(-x*sa+z*ca)*crop+.5+offz
            coords=[sv*(n.shape[0]-1),su*(n.shape[1]-1)]
            def sample(field):return map_coordinates(field,coords,order=1,mode='nearest',prefilter=False)
            px=sample(source_x);pz=sample(source_z)
            sx+=weight*(px*ca-pz*sa)*crop
            sz+=weight*(px*sa+pz*ca)*crop
            h+=weight*sample(heat)
    return sx,sz,np.clip(h,0,1)


def valley_heat(n):
    """Approximate valleys from a least-squares height reconstruction, not temperature."""
    from scipy.fft import rfft2,irfft2,rfftfreq,fftfreq
    step=max(1,int(np.ceil(max(n.shape[:2])/256)))
    nn=n[::step,::step];sx=-nn[...,0]/np.maximum(nn[...,2],.15);sz=-nn[...,1]/np.maximum(nn[...,2],.15)
    h,w=sx.shape;kx=(2*np.pi*rfftfreq(w))[None,:];kz=(2*np.pi*fftfreq(h))[:,None]
    denom=kx*kx+kz*kz;denom[0,0]=1
    freq=(-1j*kx*rfft2(sx-sx.mean())-1j*kz*rfft2(sz-sz.mean()))/denom;freq[0,0]=0
    height=irfft2(freq,s=(h,w)).astype(np.float32)
    local=height-gaussian_filter(height,max(2,min(h,w)*.06),mode='nearest')
    lo,hi=np.percentile(local,[10,90]);heat=np.clip((hi-local)/max(1e-5,hi-lo),0,1)
    if step>1:
        yy,xx=np.mgrid[:n.shape[0],:n.shape[1]].astype(np.float32)
        heat=map_coordinates(heat,[yy*(h-1)/max(1,n.shape[0]-1),xx*(w-1)/max(1,n.shape[1]-1)],order=1,mode='nearest')
    return heat.astype(np.float32)
