"""JONSWAP angular-frequency spectrum converted to a directional 2D k spectrum.
One seeded 2048-block domain is cropped, never tiled inside the supported 1024 area.
CPU FFTs run in the bake worker; outputs are cached independently of water colours.
"""
from functools import lru_cache
import numpy as np
from scipy.fft import rfft2,irfft2,rfftfreq,fftfreq

N=2048


def directional_spreading(omega_ratio,theta,spread=10.):
    """Donelan-Banner spreading (Horvath 2015, eq. 38-40), static even PSD.

    A real, static height field represents both +/- k. Average opposing travel
    lobes explicitly; abs(cos(theta)) alone cannot represent frequency spreading.
    The existing spread control scales beta artistically, then renormalizes it.
    """
    r=np.maximum(omega_ratio,1e-4)
    beta=np.where(r<.95,2.61*r**1.3,np.where(r<1.6,2.28*r**-1.3,
        10**(.8393*np.exp(-.567*np.log(np.maximum(r,1.6)**2))-.4)))
    beta*=.65+.14*np.clip(spread,4,24)
    theta=(theta+np.pi)%(2*np.pi)-np.pi
    opposite=(theta+2*np.pi)%(2*np.pi)-np.pi
    norm=beta/(2*np.tanh(beta*np.pi))
    return .5*norm*(1/np.cosh(beta*theta)**2+1/np.cosh(beta*opposite)**2)


def band_partition(k,boundary):
    """Complementary power windows: no hard frequency ring or duplicated power."""
    t=np.clip((k/boundary-.7)/.6,0,1)
    fine=t*t*(3-2*t)
    return 1-fine,fine


def spectrum(k,kx,kz,peak_length,direction,gamma,spread):
    g=9.81;safe=np.maximum(k,1e-6);omega=np.sqrt(g*safe);peak=np.sqrt(g*2*np.pi/peak_length)
    sigma=np.where(omega<=peak,.07,.09)
    enhancement=np.exp(-.5*((omega-peak)/(sigma*peak))**2)
    # d omega / d k and polar Jacobian 1/k convert S(omega) D(theta) to S(kx,kz).
    s=g*g*omega**-5*np.exp(-1.25*(peak/omega)**4)*gamma**enhancement*g/(2*omega*safe)
    directional=directional_spreading(omega/peak,np.arctan2(kz,kx)-direction,spread)
    cutoff=np.exp(-(safe/(2*np.pi/peak_length*5))**2)
    s*=directional*cutoff;s[0,0]=0
    return s.astype(np.float32)


@lru_cache(maxsize=2)
def full_fields(scale,angle,disorder,seed,micro,wind,gamma,separate=True,ripple_ratio=.16):
    kx=(2*np.pi*rfftfreq(N)).astype(np.float32)[None,:]
    kz=(2*np.pi*fftfreq(N)).astype(np.float32)[:,None];k=np.hypot(kx,kz)
    rng=np.random.default_rng(seed)
    boundary=2*np.pi/(scale*.3)
    for band in (0,1):
        length=scale if band==0 else max(3,scale*ripple_ratio)
        power=spectrum(k,kx,kz,length,angle,gamma if band==0 else 1,18-12*disorder)
        # Each band owns its wavelengths. No duplicated main/short-wave energy.
        if separate: power*=band_partition(k,boundary)[band]
        # A block cannot resolve sub-two-block waves. Dampen before Nyquist.
        power*=np.exp(-(k/(np.pi*.65))**8)
        white=rng.standard_normal((N,N),dtype=np.float32)
        coefficients=rfft2(white,workers=1)*np.sqrt(power)
        gx=irfft2(1j*kx*coefficients,s=(N,N),workers=1);gz=irfft2(1j*kz*coefficients,s=(N,N),workers=1)
        amplitude=(1 if band==0 else micro*.35)/max(1e-8,float(np.sqrt(np.mean(gx*gx+gz*gz))))
        if band==0:
            elevation=irfft2(coefficients,s=(N,N),workers=1)*amplitude
            main=coefficients*amplitude;safe=np.maximum(k,1e-6)
            dx=irfft2(1j*kx/safe*main,s=(N,N),workers=1)
            dz=irfft2(1j*kz/safe*main,s=(N,N),workers=1)
            dxx=irfft2(-kx*kx/safe*main,s=(N,N),workers=1)
            dxz=irfft2(-kx*kz/safe*main,s=(N,N),workers=1)
            dzz=irfft2(-kz*kz/safe*main,s=(N,N),workers=1)
            sx=gx*amplitude;sz=gz*amplitude
        else:
            elevation+=irfft2(coefficients,s=(N,N),workers=1)*amplitude
            sx+=gx*amplitude;sz+=gz*amplitude
    # Keep an oversized domain so horizontal displacement can sample beyond edges.
    return tuple(np.ascontiguousarray(a,dtype=np.float32) for a in (elevation,sx,sz,dx,dz,dxx,dxz,dzz))


@lru_cache(maxsize=2)
def deformation_limit(scale,angle,disorder,seed,micro,wind,gamma,separate,ripple_ratio=.16):
    maps=full_fields(scale,angle,disorder,seed,micro,wind,gamma,separate,ripple_ratio)
    xx,xz,zz=maps[5:8]
    low=.5*(xx+zz-np.sqrt((xx-zz)**2+4*xz*xz))
    # Single-valued Minecraft columns cannot represent a folded/overturned surface.
    # Bound the smallest deformation eigenvalue above .12 across the whole domain.
    return min(.8,.88/max(1e-6,-float(low.min())))


@lru_cache(maxsize=2)
def filtered_fields(args,footprint):
    from scipy.ndimage import gaussian_filter
    return tuple(gaussian_filter(m,max(0,(footprint-1)*.3)) for m in full_fields(*args)[:3])


def fields(x,z,scale,angle,disorder,seed,micro=.45,footprint=1,wind=.65,gamma=3.3,separate=True,choppiness=.65,ripple_ratio=.16):
    args=(float(scale),float(angle),float(disorder),int(seed),float(micro),float(wind),float(gamma),bool(separate),float(ripple_ratio))
    maps=full_fields(*args)
    from scipy.ndimage import map_coordinates,gaussian_filter
    px=x+512;pz=z+512;qx=px.copy();qz=pz.copy()
    amount=float(choppiness)*(.2+.8*wind)*deformation_limit(*args)
    def sample(a):return map_coordinates(a,[qz,qx],order=1,mode='wrap',prefilter=False)
    # Invert p=q+lambda D(q): bake at fixed block positions, not on a warped grid.
    if amount:
        for _ in range(7):
            dx,dz,xx,xz,zz=[sample(m) for m in maps[3:8]]
            a=1+amount*xx;b=amount*xz;d=1+amount*zz;det=a*d-b*b
            ex=qx+amount*dx-px;ez=qz+amount*dz-pz
            qx-=np.clip((d*ex-b*ez)/det,-64,64)
            qz-=np.clip((a*ez-b*ex)/det,-64,64)
    h,sx,sz=[sample(m) for m in (filtered_fields(args,float(footprint)) if footprint>1 else maps[:3])]
    xx,xz,zz=[sample(m) for m in maps[5:8]]
    a=1+amount*xx;b=amount*xz;d=1+amount*zz;det=a*d-b*b
    world_sx=(d*sx-b*sz)/det;world_sz=(a*sz-b*sx)/det
    minimum=.5*(a+d-np.sqrt((a-d)**2+4*b*b))
    compression=np.clip(1-minimum,0,1)
    return h,world_sx,world_sz,compression
