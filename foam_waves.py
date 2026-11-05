# Lua-style whitecap judgement shared by generated and map-backed surfaces.
# The supplied Lua locates white crests from horizontal compression, the
# downwind front slope and a normalized wave height, then fragments residual
# foam with noise. This module reproduces that structure on the app's fields.
import numpy as np
from scipy.ndimage import gaussian_filter
import lua_waves


def front_slope(sx,sz,angle):
    ca,sa=np.cos(angle),np.sin(angle)
    return sx*ca+sz*sa


def along_derivative(field,angle,footprint):
    ca,sa=np.cos(angle),np.sin(angle)
    gx=np.gradient(field,axis=1)/footprint
    gz=np.gradient(field,axis=0)/footprint
    return gx*ca+gz*sa


def compression(sx,sz,angle,footprint,wavelength,smoothing=0.):
    # Positive at crests: minus the second height derivative along travel.
    front=front_slope(sx,sz,angle)
    if smoothing>0:front=gaussian_filter(front,smoothing,mode='nearest')
    return np.maximum(0,along_derivative(front,angle,footprint))*(wavelength/(2*np.pi))


def amplitude(elevation):
    return max(.08,float(np.percentile(np.abs(elevation-np.median(elevation)),95)))


def whitecaps(sx,sz,angle,footprint,wavelength,base,x,z,elevation=None,
              crest_threshold=.65,crest_compression=.15,foam_compression=.11,
              foam_front=.03,foam_front_loose=.16,foam_density=.36,seed=4271,
              check=lambda:None):
    # base is the existing eligible normal-driven foam mask. New foam never
    # leaves it; placement inside it follows the Lua compression/front rules.
    check();base=np.asarray(base,np.float32)
    if float(base.max(initial=0))<=0:
        return np.zeros_like(base),np.zeros_like(base)
    front=front_slope(sx,sz,angle)
    sigma=max(.35,min(1.,wavelength*.02))/footprint
    comp=compression(sx,sz,angle,footprint,wavelength,sigma)
    if elevation is not None:
        # Slope and compression units differ between generators; normalize both
        # inside the eligible mask and keep the wave height in its own units.
        eligible=base>0
        amp=amplitude(elevation)
        wave=(elevation-np.median(elevation))/amp
        # Owner-band switches leave small derivative seams. Smooth the crest
        # height/compression so a whitewater band does not break into pieces.
        bridge=max(1.,wavelength*.12)
        wave=gaussian_filter(wave,bridge,mode='nearest')
        comp=gaussian_filter(comp,bridge,mode='nearest')
        front_n=front/max(1e-6,float(np.percentile(np.abs(front[eligible]),95)) if eligible.any() else 1.)
        comp_n=comp/max(1e-6,float(np.percentile(comp[eligible],95)) if eligible.any() else 1.)
        # The supplied Lua rule: compression, forward face and a wave-height
        # floor near the crest. This keeps the band narrow instead of painting
        # the whole upper face.
        # The visible whitewater is the continuous crest band; compression only
        # weights it. A hard front/compression gate chopped the band at owner
        # seams and along-crest sign changes.
        white=(wave>=crest_threshold-.15)
        # Bridge small owner-band seams along the crest so whitewater reads as a
        # continuous band rather than short dashes.
        bridged=gaussian_filter(white.astype(np.float32),max(1.,wavelength*.05),mode='nearest')
        white=bridged>.28
        residual=(front_n>foam_front_loose)&(comp_n>=foam_compression)&(wave>=crest_threshold-.55)&(wave<crest_threshold-.08)
    else:
        # Map-backed sources have no elevation. Normalize both fields by their
        # own robust range and keep the same crest/front ordering.
        # A static normal map cannot determine travel sign, so front slope is
        # used by magnitude. Normal-derived slopes carry the opposite sign to
        # generated height slopes, so compression uses the negated derivative.
        eligible=base>0
        comp=np.maximum(0,-along_derivative(front,angle,footprint))*(wavelength/(2*np.pi))
        front_n=front/max(1e-6,float(np.percentile(np.abs(front[eligible]),95)) if eligible.any() else 1.)
        comp_n=comp/max(1e-6,float(np.percentile(comp[eligible],95)) if eligible.any() else 1.)
        white=(comp_n>=.68)&(np.abs(front_n)>.36)
        residual=(comp_n>=.55)&(np.abs(front_n)>.55)
    ca,sa=np.cos(angle),np.sin(angle)
    u=x*ca+z*sa;v=-x*sa+z*ca
    grain=max(6.,wavelength*.45)
    noise=lua_waves._value_noise(u,v,grain,grain,seed+18371)
    support=np.clip((base-.02)/.12,0,1)
    # Whitewater is the continuous crest band; only residual foam is
    # noise-fragmented. The supplied Lua does the same (foam=2 vs foam=1).
    whitewater=(white&(base>0)).astype(np.float32)*support
    residual=(residual&(base>0)).astype(np.float32)*support
    residual*=np.clip((noise-(1-foam_density))/.12,0,1)
    check()
    return whitewater.astype(np.float32),residual.astype(np.float32)
