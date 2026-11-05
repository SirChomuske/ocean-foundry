"""Deterministic spatial palette mixing in perceptual colour space."""
import numpy as np
from scipy.ndimage import gaussian_filter

METHODS = {'none':'Off', 'ordered':'Ordered (Bayer)', 'noise':'Seeded noise',
           'diffusion':'Error diffusion (Floyd–Steinberg)'}


def threshold_grid(shape,method,grain,seed):
    z,x=np.indices(shape,dtype=np.uint64)
    x//=grain; z//=grain
    if method=='ordered':
        matrix=np.array([[0]],dtype=float)
        for _ in range(3): matrix=np.block([[4*matrix,4*matrix+2],[4*matrix+3,4*matrix+1]])
        return (matrix[(z%8).astype(int),(x%8).astype(int)]+.5)/64
    # Stable coordinate hash: changing build width does not shuffle the pattern.
    v=(x*np.uint64(374761393)+z*np.uint64(668265263)+np.uint64(seed)*np.uint64(1442695041)) & np.uint64(0xffffffff)
    v=((v^(v>>13))*np.uint64(1274126177)) & np.uint64(0xffffffff)
    v^=v>>16
    return (v.astype(float)+.5)/4294967296


def assign(target,palette,baseline,method='none',strength=.65,grain=1,seed=4271):
    """Select existing palette entries only; never adds blocks or changes shape."""
    if method=='none' or strength==0 or len(palette)<2:
        return baseline.copy()
    target=np.asarray(target,dtype=float)
    palette=np.asarray(palette,dtype=float)
    if method=='diffusion':
        return error_diffusion(target,palette,strength)
    if method not in ('ordered','noise'): raise ValueError('Unknown dithering method.')
    distances=np.sum((target[:,:,None,:]-palette[None,None,:,:])**2,axis=-1)
    nearest=np.argsort(distances,axis=-1,kind='stable')[...,:2]
    first,second=nearest[...,0],nearest[...,1]
    a,b=palette[first],palette[second]
    delta=b-a
    denominator=np.sum(delta*delta,axis=-1)
    # Project onto the nearest pair. A fractional mixture can approximate a
    # colour that neither Minecraft block can represent on its own.
    fraction=np.clip(np.sum((target-a)*delta,axis=-1)/np.maximum(denominator,1e-12),0,1)
    threshold=threshold_grid(first.shape,method,grain,seed)
    mix=threshold < strength*fraction
    return np.where(mix,second,baseline).astype(np.intp)


def error_diffusion(target,palette,strength,limit=15.,progress=None):
    """Serpentine Floyd–Steinberg: 7/16 forward, 3/16 back-below,
    5/16 below and 1/16 forward-below. Strength scales propagated error.

    ``limit`` bounds out-of-gamut error so unattainable target colours do not
    leave long streaks; the production bake and the palette helper share this
    one implementation. ``progress`` receives (rows_done, rows_total) every
    eighth row.
    """
    work=target.copy()
    length,width=work.shape[:2]
    output=np.empty((length,width),dtype=np.intp)
    for z in range(length):
        direction=1 if z%2==0 else -1
        for x in (range(width) if direction==1 else range(width-1,-1,-1)):
            current=work[z,x]
            index=int(np.argmin(np.sum((palette-current)**2,axis=1)))
            output[z,x]=index
            error=np.clip(current-palette[index],-limit,limit)*strength
            if 0<=x+direction<width: work[z,x+direction]+=error*(7/16)
            if z+1<length:
                if 0<=x-direction<width: work[z+1,x-direction]+=error*(3/16)
                work[z+1,x]+=error*(5/16)
                if 0<=x+direction<width: work[z+1,x+direction]+=error*(1/16)
        if progress is not None and (z+1)%8==0:
            progress(z+1,length)
    if progress is not None and length%8:
        progress(length,length)
    return output


def blend_edges(baseline, output, palette, strength, method, grain=1, seed=4271):
    """Mix neighbouring material patches without spreading high-contrast foam.

    Local material coverage supplies the candidates, rather than an unrelated
    second-nearest colour. Uniform interiors and the material pool are preserved.
    """
    if method=='none' or strength<=0 or len(palette)<2:return output.copy()
    palette=np.asarray(palette,dtype=float)
    sigma=.65+1.35*strength
    weights=[]
    for index in range(len(palette)):
        coverage=gaussian_filter((baseline==index).astype(np.float32),sigma,truncate=2,mode='nearest')
        difference=np.sum((palette[baseline]-palette[index])**2,axis=-1)
        # Distinct foam/reflection edges stay sharp; close water shades intermix.
        coverage*=np.exp(-difference/(24.**2))
        weights.append(coverage)
    total=np.maximum(sum(weights),1e-12)
    threshold=threshold_grid(baseline.shape,'ordered' if method=='ordered' else 'noise',grain,seed+1921)
    cumulative=np.zeros_like(total);result=output.copy()
    for index,weight in enumerate(weights):
        probability=.8*strength*weight/total+(1-.8*strength)*(output==index)
        take=(threshold>=cumulative)&(threshold<cumulative+probability)
        result[take]=index;cumulative+=probability
    return result
