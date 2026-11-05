"""Seeded directional swells with bounded horizontal crest compression."""
import math
import numpy as np
import water_spectrum


def continuous(s):
    z,x=np.mgrid[:s['length'],:s['width']].astype(np.float32)
    angle=math.radians(s['direction'])
    if s['irregularity']==0:
        # Controlled single-wave limit, also useful for checking crest/trough shape.
        phase=2*np.pi*(x*np.cos(angle)+z*np.sin(angle))/s['wavelength']
        phase+=np.random.default_rng(s['seed']).uniform(0,2*np.pi)
        q=phase.copy();amount=.8*s['sharpness']
        for _ in range(12):q-=(q-amount*np.sin(q)-phase)/(1-amount*np.cos(q))
        return np.cos(q)
    h,_,_,_=water_spectrum.fields(x,z,s['wavelength'],angle,s['irregularity'],s['seed'],
        micro=s['detail']*.15,wind=.4,gamma=4-3*s['irregularity'],choppiness=s['sharpness'])
    return h


def heightfield(s):
    if not s['wave_height']:return [s['thickness']-1]*(s['width']*s['length'])
    raw=continuous(s);span=np.ptp(raw)
    h=np.floor((raw-raw.min())/span*s['wave_height']+.5) if span else np.zeros_like(raw)
    return (h.astype(int)+s['thickness']-1).ravel().tolist()
