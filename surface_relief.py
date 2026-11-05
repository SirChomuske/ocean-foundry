"""Restrained glass relief derived only from the shared normal surface."""
import numpy as np
from scipy.ndimage import gaussian_filter


def from_slopes(sx,sz,wavelength=24.,footprint=1.):
    # Curvature locates crests independently of light direction, colour or foam.
    curvature=-(np.gradient(sx,axis=1)+np.gradient(sz,axis=0))/(2*max(1.,footprint))
    curvature=gaussian_filter(curvature,2/max(1.,footprint),mode='nearest')
    return np.clip(.5+.32*np.tanh(curvature*min(64.,wavelength)*.6),.18,.82).astype(np.float32)
