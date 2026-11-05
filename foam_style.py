"""Approved Lua-inspired foam appearance; the existing mask owns placement."""
import numpy as np
from scipy.ndimage import maximum_filter,map_coordinates


def whitewater_and_foam(existing,x,z,angle,wavelength,seed,footprint,variation):
    """Scattered breaking whitewater and residual foam in existing eligible areas.

    No physical height, new breaking criteria, displacement or normal edits.
    The supplied Lua's two visual categories are adapted to the eligible normal-
    driven mask. Existing wind/depth/face/gap rules have already been applied.
    """
    def smooth(lo,hi,v):
        t=np.clip((v-lo)/(hi-lo),0,1);return t*t*(3-2*t)
    radius=max(1,int(np.ceil(1.5/max(1.,footprint))))
    peak=maximum_filter(existing,2*radius+1,mode='nearest')
    relative=existing/np.maximum(peak,.08)
    support=smooth(.025,.12,existing)
    ca,sa=np.cos(angle),np.sin(angle);u=x*ca+z*sa;v=-x*sa+z*ca
    # Shape only inside the old mask: no dilation or relocated crest detector.
    gaps=variation(u,v,max(6.,wavelength*.45),seed+18371)
    breaking=smooth(.65,.92,relative)*smooth(.09,.20,existing)*smooth(.22,.43,gaps)
    grain=max(1.,min(2.5,wavelength*.045))
    noise=variation(u,v,grain,seed+29173)
    # Crest alignment locates breaking; turbulent whitewater itself is fragmented.
    fragments=smooth(.27,.54,noise)
    fine=variation(u,v,max(1.,grain*.65),seed+39181)
    fragments*=.55+.45*smooth(.3,.6,fine)
    dots=smooth(.62,.72,noise)
    # A draft pixel may cover several small specks; average their coverage rather
    # than amplify one random sample. Full-resolution masks retain discrete detail.
    resolved=np.clip(grain/max(1.,footprint),0,1)
    dots=resolved*dots+(1-resolved)*.12
    fringe=(1-breaking)*smooth(.15,.45,relative)*dots
    brightness=np.minimum(.98,peak*1.6)
    whitewater=breaking*fragments*brightness*support
    # Static downstream decay: foam can remain only near breaking whitewater,
    # behind it along the shared wave heading, and inside the original mask.
    rows,cols=np.indices(existing.shape,dtype=np.float32)
    trail=whitewater.copy()
    step=max(1.,min(5.,wavelength*.06))
    for distance,decay in ((step,.8),(step*2,.55),(step*3,.3)):
        shifted=map_coordinates(whitewater,[rows+sa*distance/footprint,cols+ca*distance/footprint],
                                order=1,mode='nearest',prefilter=False)
        trail=np.maximum(trail,shifted*decay)
    residual=.88*fringe*brightness*support*smooth(.015,.15,trail)
    allowed=existing>0
    return (np.where(allowed,whitewater,0).astype(np.float32),
            np.where(allowed,residual,0).astype(np.float32))


def lua_crests(existing,x,z,angle,wavelength,seed,footprint,variation):
    whitewater,foam=whitewater_and_foam(existing,x,z,angle,wavelength,seed,footprint,variation)
    return np.maximum(whitewater,foam)
