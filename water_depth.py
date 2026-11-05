"""Virtual bathymetry and bounded, wavelength-aware surface response.

This is a static appearance model, not a time-stepped coastal flow solver.
The carrier phase is preserved: depth never rescales or masks the whole texture.
"""
import math
import numpy as np


def plane(x, z, width, length, c, a):
    angle = math.radians(c['depth_direction'])
    dx, dz = math.cos(angle), math.sin(angle)
    minimum = min(0, dx * (width - 1)) + min(0, dz * (length - 1))
    extent = abs(dx) * (width - 1) + abs(dz) * (length - 1)
    slope = a['depth_rise'] / max(1, extent) if a['depth_mode'] == 'span' else c['depth_slope']
    return np.maximum(a['shallow_depth'], a['shallow_depth'] + (x * dx + z * dz - minimum) * slope)


def migrate(values, c, settings):
    """Preserve the shallow end of saved legacy deepest-anchored planes."""
    values = dict(values)
    if 'shallow_depth' not in values and 'depth_base' in values:
        angle = math.radians(c['depth_direction'])
        extent = abs(math.cos(angle)) * (settings['width'] - 1) + abs(math.sin(angle)) * (settings['length'] - 1)
        values['shallow_depth'] = max(0, values['depth_base'] - c['depth_slope'] * extent)
    values.pop('depth_base', None)
    return values


def response(depth, wavelength):
    """Solve finite-depth dispersion at the carrier's deep-water frequency.

    tanh(k*d) distinguishes shallow from deep relative to each wavelength.
    Limit amplitude shoaling near zero depth; breaking dissipates that energy.
    """
    d = np.maximum(np.asarray(depth, np.float32), .5)
    k0 = 2 * np.pi / max(4, wavelength)
    k = np.maximum(k0, np.sqrt(k0 / d))
    for _ in range(5):
        t = np.tanh(k * d)
        k -= (k * t - k0) / np.maximum(t + k * d * (1 - t * t), 1e-6)
    kh = k * d
    bottom = 1 - np.tanh(kh)
    group_ratio = .5 * (1 + 2 * kh / np.sinh(np.minimum(2 * kh, 40)))
    speed_ratio = k0 / k
    shoal = np.clip(np.sqrt(.5 / np.maximum(.08, group_ratio * speed_ratio)), .85, 1.65)
    return bottom.astype(np.float32), shoal.astype(np.float32)


def phase_coordinates(x,z,width,length,c,a,wavelength,angle):
    """Planar-bathymetry WKB phase approximation, conserving along-contour k.

    A bounded contraction toward the shallow edge keeps the FFT sample domain
    bounded. Zero slope or disabled refraction is exactly the original carrier.
    This is a steady planar approximation; no currents, diffraction or ray crossing.
    """
    strength=a.get('depth_refraction',0.)
    az=math.radians(c['depth_direction']);nx,nz=math.cos(az),math.sin(az)
    extent=abs(nx)*(width-1)+abs(nz)*(length-1)
    slope=a['depth_rise']/max(1,extent) if a['depth_mode']=='span' else c['depth_slope']
    alignment=math.cos(angle-az)
    if not strength or not slope or abs(alignment)<.15:return x,z,np.ones_like(x),nx,nz
    minimum=min(0,nx*(width-1))+min(0,nz*(length-1))
    q=x*nx+z*nz-minimum
    grid=np.arange(min(0,int(np.floor(q.min()))-1),max(2,int(np.ceil(max(extent,float(q.max()))))+2),dtype=np.float32)
    depth=np.maximum(.5,a['shallow_depth']+np.maximum(grid,0)*slope)
    k0=2*np.pi/max(4,wavelength)
    k=np.maximum(k0,np.sqrt(k0/depth))
    for _ in range(6):
        t=np.tanh(k*depth);k-=(k*t-k0)/np.maximum(t+k*depth*(1-t*t),1e-6)
    tangent=k0*math.sin(angle-az)
    normal=np.sqrt(np.maximum(k*k-tangent*tangent,1e-8))
    ratio=np.clip(normal/np.interp(0,grid,normal),.35,1.)
    ratio=1-strength+strength*ratio
    integral=np.r_[0,np.cumsum((ratio[:-1]+ratio[1:])*.5)]
    integral-=np.interp(0,grid,integral)
    shift=np.interp(q,grid,integral)-q
    derivative=np.interp(q,grid,ratio).astype(np.float32)
    return (x+nx*shift).astype(np.float32),(z+nz*shift).astype(np.float32),derivative,nx,nz
