"""Explicit Ocean colour contributions; no geometry or material selection."""
import numpy as np
from scipy.ndimage import gaussian_filter
import defaults

RANGES=dict(lit_strength=(0,1),depth_colour_influence=(0,1),depth_colour_reach=(1,2048),
            shading_strength=(0,1),shadow_softness=(0,12),shading_contrast=(0,6),shading_midpoint=(0,1))
# Same file as the rest of the appearance section; this module only owns the ranges.
_APPEARANCE=defaults.section('appearance')
DEFAULTS={key:_APPEARANCE[key] for key in RANGES}


def smooth(lo,hi,x):
    t=np.clip((x-lo)/(hi-lo),0,1)
    return t*t*(3-2*t)


def illumination(nl,softness=3.,footprint=1.):
    # Retain the original shadow/highlight contrast. A small continuous shoulder
    # removes the dead band without raising the whole surface toward the lit tint.
    # Both components retain exact 0/1 endpoints, independent of crop or palette.
    facing=np.clip(nl,0,1)
    face=.94*smooth(.4,1.,facing)**2+.06*facing**2
    sigma=softness/max(1.,footprint)
    return gaussian_filter(face,sigma,mode='nearest') if sigma else face


def weight(illumination,depth,a):
    shallow=1-smooth(0,a['depth_colour_reach'],np.asarray(depth))
    face=np.clip((illumination-a['shading_midpoint'])*a['shading_contrast']+.5,0,1)
    lit_face=1-a['shading_strength']+a['shading_strength']*face
    return np.clip(a['lit_strength']*lit_face*(1+a['depth_colour_influence']*shallow),0,1)


def linear(rgb):
    x=np.asarray(rgb,dtype=np.float32)/255
    return np.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)


def encode(rgb):
    x=np.where(rgb<=.0031308,rgb*12.92,1.055*np.maximum(rgb,0)**(1/2.4)-.055)
    return np.clip(np.round(x*255),0,255).astype(np.uint8)


def shade(illumination,depth,reflection,foam,colours,a):
    lit,body,sky,white=linear(colours)
    scatter=weight(illumination,depth,a)
    rgb=body+(lit-body)*scatter[...,None]
    rgb=rgb*(1-reflection[...,None])+sky*reflection[...,None]
    return encode(rgb*(1-foam[...,None])+white*foam[...,None])


# Same formula as weight(); the GPU consumes the same softened illumination.
GLSL='''
float shallow=1.-smoothstep(0.,colourControls.z,depth);
float face=clamp((bodyLight-shadingMidpoint)*shadingContrast+.5,0.,1.);
float litFace=mix(1.,face,colourControls.w);
float scatter=clamp(colourControls.x*litFace*(1.+colourControls.y*shallow),0.,1.);
vec3 rgb=mix(deepColour,shallowColour,scatter);
'''
