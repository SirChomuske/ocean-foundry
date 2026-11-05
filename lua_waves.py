# Lua-style surface synthesis: several complete wave bands are composited with
# the supplied Lua's priority/owner rule. Each point keeps the highest wave
# candidate after a fade penalty; foam/normals therefore follow the owning band.
# Static synthesis, not a propagation or breaking-wave solver.
import numpy as np
import texture_synthesis


def _value_noise(u,v,su,sv,seed):
    # Coherent value noise fixed in world coordinates (bilinear smoothstep).
    x=u/su;z=v/sv
    ix=np.floor(x).astype(np.int64);iz=np.floor(z).astype(np.int64)
    tx=x-ix;tz=z-iz
    tx=tx*tx*(3-2*tx);tz=tz*tz*(3-2*tz)
    out=np.zeros_like(u,dtype=np.float32)
    for dz in (0,1):
        for dx in (0,1):
            h=(texture_synthesis._hash(ix+dx,iz+dz,seed)&65535).astype(np.float32)/65535.
            out+=h*(tx if dx else 1-tx)*(tz if dz else 1-tz)
    return out


def _band(x,z,wavelength,angle,disorder,seed,micro):
    k1=2*np.pi/wavelength
    k2=k1/0.61;k3=k1/0.29;k4=k1/0.15;k5=k1/0.10;k6=k1/0.08
    n2=np.sqrt(.95**2+.32**2);n3=np.sqrt(.87**2+.42**2)
    u2a,u2c=.95/n2,.32/n2;u3a,u3c=.87/n3,-.42/n3
    ca,sa=np.float32(np.cos(angle)),np.float32(np.sin(angle))
    u=x*ca+z*sa;v=-x*sa+z*ca
    noise_a=_value_noise(x,z,95.,95.,seed);noise_b=_value_noise(x,z,71.,71.,seed+1)
    along=u+(noise_a-.5)*wavelength*.60
    cross=v+(noise_b-.5)*wavelength*.25
    group_a=_value_noise(along,cross,wavelength*3.0,52.0,seed+41)
    group_b=_value_noise(along,cross,wavelength*1.8,52.0*.65,seed+59)
    t=np.clip((.76*group_a+.24*group_b-.33)/(.57-.33),0,1)
    group_active=t*t*(3-2*t)
    group_gain=1-.78*(1-group_active)
    wave_along=along+(group_b-.5)*wavelength*.19
    g1,g2,g3=.55*group_gain,.24*group_gain,.12*group_gain
    slope_budget=k1*.55+k2*.24*n2+k3*.12*n3
    chop=min(1.15+.8*float(np.clip(disorder,0,1)),.86/max(1e-4,slope_budget))
    p1=k1*wave_along
    p2=k2*(.95*wave_along+.32*cross)+1.31
    p3=k3*(.87*wave_along-.42*cross)+2.73
    d_along=chop*(g1*np.cos(p1)+g2*u2a*np.cos(p2)+g3*u3a*np.cos(p3))
    d_cross=chop*(g2*u2c*np.cos(p2)+g3*u3c*np.cos(p3))
    source_along=wave_along-d_along;source_cross=cross-d_cross
    p1=k1*source_along
    p2=k2*(.95*source_along+.32*source_cross)+1.31
    p3=k3*(.87*source_along-.42*source_cross)+2.73
    p4=k4*(.68*source_along+.73*source_cross)+.71
    p5=k5*(.46*source_along-.89*source_cross)+2.12
    p6=k6*(.77*source_along+.62*source_cross)+.42
    lean=.18
    w1=np.sin(p1)-lean*np.sin(2*p1)
    w2=np.sin(p2);w3=np.sin(p3);w4=np.sin(p4);w5=np.sin(p5);w6=np.sin(p6)
    short=float(np.clip(micro,0,1))
    elevation=g1*w1+g2*w2+g3*w3+.06*w4+short*(.02*w5+.01*w6)
    h_a=(g1*k1*(np.cos(p1)-2*lean*np.cos(2*p1))+g2*k2*.95*np.cos(p2)
         +g3*k3*.87*np.cos(p3)+.06*k4*.68*np.cos(p4)
         +short*(.02*k5*.46*np.cos(p5)+.01*k6*.77*np.cos(p6)))
    h_c=(g2*k2*.32*np.cos(p2)-g3*k3*.42*np.cos(p3)+.06*k4*.73*np.cos(p4)
         +short*(.02*k5*(-.89)*np.cos(p5)+.01*k6*.62*np.cos(p6)))
    sx=-(h_a*ca-h_c*sa);sz=-(h_a*sa+h_c*ca)
    curv=(g1*k1*k1*(np.sin(p1)-4*lean*np.sin(2*p1))+g2*k2*k2*.95**2*np.sin(p2)
          +g3*k3*k3*.87**2*np.sin(p3)+.06*k4*k4*.73**2*np.sin(p4)
          +short*(.02*k5*k5*.89**2*np.sin(p5)+.01*k6*k6*.62**2*np.sin(p6)))
    # Lua's own crest/face flags: Jacobian compression and forward-face slope.
    b1=chop*g1*k1*np.sin(p1);b2=chop*g2*k2*np.sin(p2)/n2;b3=chop*g3*k3*np.sin(p3)/n3
    jaa=1-b1-b2*.95**2-b3*.87**2
    jcc=1-b2*.32**2-b3*.42**2
    jac=-b2*.95*.32+b3*.87*.42
    comp=np.maximum(0,1-(jaa*jcc-jac*jac))
    return (np.asarray(elevation,np.float32),np.asarray(sx,np.float32),
            np.asarray(sz,np.float32),np.asarray(curv,np.float32),
            np.asarray(elevation,np.float32),np.asarray(-h_a,np.float32),np.asarray(comp,np.float32))


def _fraction(seed,i,salt):
    h=(seed*1103515245+i*1013904223+salt*2654435761)&0x7fffffff
    return ((h>>8)&65535)/65535.


def fields(x,z,scale,angle,disorder,seed,micro=.45,footprint=1,layers=1):
    # Stack complete Lua wave bands with the script's owner rule: for every
    # point, the band with the highest noise priority keeps its full wave; the
    # others fade by a smooth penalty. The visible surface is the highest
    # candidate, and its slopes/curvature are the ones used for normals and foam.
    count=int(np.clip(layers,1,8))
    wavelength=float(max(4,scale))
    noise_strength=float(np.clip(.35+.65*float(np.clip(disorder,0,1)),0,1))
    crest_length=max(24.,wavelength*2.7)
    cover_depth=1.5
    ca,sa=np.cos(angle),np.sin(angle)
    along0=x*ca+z*sa;cross0=-x*sa+z*ca
    drift=_value_noise(along0,cross0,wavelength*3.9,crest_length*1.1,seed+529)-.5
    mask_along=along0+wavelength*1.1*drift
    candidates=[];slopes_x=[];slopes_z=[];curvatures=[];priorities=[]
    waves=[];fronts=[];comps=[]
    for i in range(count):
        band_seed=(seed+i*1013)%2147483647
        if i==0:
            coefficient,turn,shift=1.0,0.0,0.0
        else:
            rnd=_fraction(seed,i,7)
            coefficient=.55+.9*rnd
            phase=_fraction(seed,i,11)
            spread=_fraction(seed,i,13)
            shift=wavelength*coefficient*phase
            turn=(.3+.7*spread)*float(np.clip(disorder,0,1))*.35
            if i%2==0:turn=-turn
        ox,oz=shift*ca,shift*sa
        e,sx,sz,c,wave,front,comp=_band(x+ox,z+oz,wavelength*coefficient,angle+turn,disorder,band_seed,micro)
        packet=_value_noise(mask_along,cross0,wavelength*2.4,crest_length,band_seed+41)
        priority=noise_strength*(packet-.5)
        if i==0:priority=priority+.5*(1.0-noise_strength)**2
        candidates.append(e);slopes_x.append(sx);slopes_z.append(sz);curvatures.append(c)
        waves.append(wave);fronts.append(front);comps.append(comp)
        priorities.append(priority)
    if count==1:
        return (np.asarray(candidates[0],np.float32),np.asarray(slopes_x[0],np.float32),
                np.asarray(slopes_z[0],np.float32),np.asarray(curvatures[0],np.float32))
    prio=np.stack(priorities,axis=0)
    best=prio.max(axis=0)
    out_e=None;owner=None
    cand_stack=np.empty((count,)+x.shape,np.float32)
    for i in range(count):
        t=np.clip((best-prio[i]-.03)/.22,0,1)
        smooth=t*t*(3-2*t)
        cand_stack[i]=candidates[i]-cover_depth*smooth
    owner=np.argmax(cand_stack,axis=0)
    take=owner[None,...]
    elevation=np.take_along_axis(cand_stack,take,axis=0)[0]
    sx=np.take_along_axis(np.stack(slopes_x,axis=0),take,axis=0)[0]
    sz=np.take_along_axis(np.stack(slopes_z,axis=0),take,axis=0)[0]
    curv=np.take_along_axis(np.stack(curvatures,axis=0),take,axis=0)[0]
    return (elevation.astype(np.float32),sx.astype(np.float32),sz.astype(np.float32),curv.astype(np.float32))


def foam_owner(x,z,scale,angle,disorder,seed,micro=.45,footprint=1,layers=1):
    # Owner band's own wave/forward-slope/compression, mirroring sampleOriginal.
    count=int(np.clip(layers,1,8))
    wavelength=float(max(4,scale))
    noise_strength=float(np.clip(.35+.65*float(np.clip(disorder,0,1)),0,1))
    crest_length=max(24.,wavelength*2.7);cover_depth=1.5
    ca,sa=np.cos(angle),np.sin(angle)
    along0=x*ca+z*sa;cross0=-x*sa+z*ca
    drift=_value_noise(along0,cross0,wavelength*3.9,crest_length*1.1,seed+529)-.5
    mask_along=along0+wavelength*1.1*drift
    candidates=[];waves=[];fronts=[];comps=[];priorities=[]
    for i in range(count):
        band_seed=(seed+i*1013)%2147483647
        if i==0:
            coefficient,turn,shift=1.0,0.0,0.0
        else:
            rnd=_fraction(seed,i,7);coefficient=.55+.9*rnd
            phase=_fraction(seed,i,11);spread=_fraction(seed,i,13)
            shift=wavelength*coefficient*phase
            turn=(.3+.7*spread)*float(np.clip(disorder,0,1))*.35
            if i%2==0:turn=-turn
        ox,oz=shift*ca,shift*sa
        e,sx,sz,c,wave,front,comp=_band(x+ox,z+oz,wavelength*coefficient,angle+turn,disorder,band_seed,micro)
        packet=_value_noise(mask_along,cross0,wavelength*2.4,crest_length,band_seed+41)
        priority=noise_strength*(packet-.5)
        if i==0:priority=priority+.5*(1.0-noise_strength)**2
        candidates.append(e);waves.append(wave);fronts.append(front);comps.append(comp);priorities.append(priority)
    if count==1:return waves[0],fronts[0],comps[0]
    prio=np.stack(priorities,0);best=prio.max(0);cand=np.empty((count,)+x.shape,np.float32)
    for i in range(count):
        t=np.clip((best-prio[i]-.03)/.22,0,1);sm=t*t*(3-2*t)
        cand[i]=candidates[i]-cover_depth*sm
    owner=np.argmax(cand,axis=0)[None,...]
    wave=np.take_along_axis(np.stack(waves,0),owner,axis=0)[0]
    front=np.take_along_axis(np.stack(fronts,0),owner,axis=0)[0]
    comp=np.take_along_axis(np.stack(comps,0),owner,axis=0)[0]
    return wave.astype(np.float32),front.astype(np.float32),comp.astype(np.float32)
