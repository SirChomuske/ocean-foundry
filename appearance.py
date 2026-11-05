"""Local spectral water surface, normal-driven reflection and separate breaking foam.
Generated or explicitly imported normals; CPU and OpenGL share shading parameters.
"""
import math
import re
from functools import lru_cache
import numpy as np
from scipy.ndimage import gaussian_filter
import colour
import defaults
import water_spectrum
import water_packets
import lava_surface
import normal_maps
import ocean_library
import water_depth
import surface_fields
import texture_synthesis
import water_colour
import surface_relief
import surface_cache
import foam_style
import foam_waves
import lua_waves

# Owned by default_settings.json so new installations and missing-key fallbacks agree.
DEFAULTS=defaults.section('appearance')


def validate(values):
    values=dict(values)
    if 'shallow_depth' not in values and 'depth_base' in values:values['shallow_depth']=values['depth_base']

    s={**DEFAULTS,**{k:v for k,v in values.items() if k in DEFAULTS}}
    if s['foam_style'] not in ('classic','lua_crests','whitecaps'):raise ValueError('Unknown foam style.')
    if s['lava_heat_mode'] not in ('valleys','slope'):raise ValueError('Unknown lava heat interpretation.')
    if s['lava_sampling'] not in ('legacy','stochastic','quilt'):raise ValueError('Unknown texture synthesis method.')
    if s['depth_mode'] not in ('slope','span'):raise ValueError('Unknown depth mode.')
    if s['normal_source'] not in ('built_in','imported'):raise ValueError('Unknown normal source.')
    for key in ('normal_map_path','normal_map_name'):
        if not isinstance(s[key],str):raise ValueError('Normal map path/name must be text.')
    if s['surface_model'] not in ('procedural','fft_normals','lua_waves','ocean_maps','lava'): raise ValueError('Unknown surface model.')
    if s['ocean_pattern'] not in dict(ocean_library.BASELINES):raise ValueError('Unknown ocean normal map.')
    if s['lava_pattern'] not in dict(lava_surface.BASELINES):raise ValueError('Unknown lava baseline.')
    for k in ('crest','foam_colour','lava_cold','lava_hot','lava_peak'):
        if not isinstance(s[k],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',s[k]): raise ValueError('Appearance colours must use #RRGGBB.')
        s[k]=s[k].lower()
    for k in ('link_direction','gpu','link_scale','lava_flip_y','invert_normals','imported_flip_y'):
        if type(s[k]) is not bool: raise ValueError(k+' must be true or false.')
    for k,lo,hi in [('depth_refraction',0,1),('swell_strength',0,1),('swell_scale',16,256),('wave_spacing',.5,2),('foundation_normals',0,1),('view_direction',0,360),('view_elevation',10,90),('normal_rotation',0,360),('imported_span',32,1024),('wind',0,1),('wind_direction',0,360),('ripple_scale',4,256),('foam',0,1),
        ('breakup',0,1),('glass_layers',0,3),('seed',0,2147483647),
        ('shallow_depth',0,2048),('depth_rise',0,2048),('reflection',0,1),('light_direction',0,360),
        ('light_elevation',10,85),('roughness',0,1),('crest_bias',0,.3),('scale_ratio',.05,1),('micro_detail',0,1),('peak_enhancement',1,7),('choppiness',0,1),('normal_strength',0,2),('ripple_ratio',.05,.25),('lava_scale',32,1024),('lava_crust',0,1),('lava_glow',0,1),('lava_distortion',0,1),('lua_layers',1,8)]:
        v=float(s[k])
        if not math.isfinite(v) or not lo<=v<=hi: raise ValueError(k+' is outside its allowed range.')
        if k in ('seed','glass_layers','lua_layers'):
            if int(v)!=v: raise ValueError(k+' must be an integer.')
            v=int(v)
        s[k]=v
    for key,(lo,hi) in water_colour.RANGES.items():
        v=float(s[key])
        if not math.isfinite(v) or not lo<=v<=hi:raise ValueError(key+' is outside its allowed range.')
        s[key]=v
    return s



def smooth(lo,hi,x):
    t=np.clip((x-lo)/(hi-lo),0,1);return t*t*(3-2*t)


def depth_field(x,z,w,l,c,a):
    return water_depth.plane(x,z,w,l,c,a)


def effective(f,a):
    spacing=float(a.get('wave_spacing',1))
    base=f['settings']['wavelength']*a['scale_ratio'] if a['link_scale'] else a['ripple_scale']
    return {**a,'ripple_scale':max(4,min(256,base*spacing))}


def mapped_ocean(a):
    return a['surface_model']!='lava' and (a['normal_source']=='imported' or a['surface_model']=='ocean_maps')


def wave_heading(settings,a):
    heading=settings['direction'] if a['link_direction'] else a['wind_direction']
    return (heading+(a['normal_rotation'] if mapped_ocean(a) else 0))%360


def foundation_settings(settings,a):
    out={**settings,'direction':wave_heading(settings,a)} if mapped_ocean(a) else dict(settings)
    spacing=float(a.get('wave_spacing',1))
    if spacing!=1 and a['surface_model']!='lava':out['wavelength']=float(settings['wavelength'])*spacing
    return out


def crest_curvature(sx,sz,wavelength,footprint=1,direction=None):
    from scipy.ndimage import gaussian_filter
    sigma=max(.35,min(1.,wavelength*.02))/footprint
    sx=gaussian_filter(sx,sigma,mode='nearest');sz=gaussian_filter(sz,sigma,mode='nearest')
    xx=np.gradient(sx,axis=1)/footprint;zz=np.gradient(sz,axis=0)/footprint
    xz=(np.gradient(sx,axis=0)+np.gradient(sz,axis=1))*.5/footprint
    spread=np.sqrt((xx-zz)**2+4*xz*xz)
    low=(xx+zz-spread)*.5;high=(xx+zz+spread)*.5
    crest=np.maximum(0,-low)
    # Suppress round caps: foam follows narrow crest ridges with tapered ends.
    elongation=np.clip((crest-np.maximum(0,-high))/np.maximum(crest,1e-6),0,1)
    if direction is not None:
        ca,sa=math.cos(direction),math.sin(direction)
        along=np.maximum(0,-(xx*ca*ca+2*xz*ca*sa+zz*sa*sa))
        crest=np.minimum(crest,along)
    return crest*smooth(.25,.85,elongation)**2


@lru_cache(maxsize=24)
def foam_calibration(items,angle):
    """Fixed world-space probe; resizing a selection never renormalizes its foam."""
    a=dict(items);z,x=np.mgrid[-8:264,-8:264].astype(np.float32)
    mapped=a['normal_source']=='imported' or a['surface_model']=='ocean_maps'
    if mapped:
        n,h=normal_maps.load(a['normal_map_path']) if a['normal_source']=='imported' else ocean_library.baseline(a['ocean_pattern'])
        ca,sa=math.cos(angle),math.sin(angle)
        px,pz,_=texture_synthesis.sample(n,h,x*ca+z*sa,-x*sa+z*ca,a['imported_span'],a['seed'],flip_y=texture_synthesis.ocean_y_flip(n,a['imported_flip_y']),preserve_direction=True)
        sx=px*ca-pz*sa;sz=px*sa+pz*ca
        direction=angle+texture_synthesis.dominant_wave_axis(n,a['imported_flip_y'])
    else:
        _,sx,sz,_=surface_fields.generate(x,z,a,angle,1,lambda:None,None,None)
        direction=None
    q=crest_curvature(sx,sz,a['ripple_scale'],direction=direction)[8:-8,8:-8]
    return max(1e-5,float(np.percentile(q,95)))


def foam_variation(x,z,scale,seed):
    """Continuous seeded patches, fixed in world coordinates rather than pixel noise."""
    u=(x*.83+z*.56)/scale;v=(-x*.56+z*.83)/scale
    ix=np.floor(u).astype(np.int64);iz=np.floor(v).astype(np.int64)
    tx=smooth(0,1,u-ix);tz=smooth(0,1,v-iz);out=np.zeros_like(x)
    for dz in (0,1):
        for dx in (0,1):
            h=(texture_synthesis._hash(ix+dx,iz+dz,seed)&65535).astype(np.float32)/65535
            out+=h*(tx if dx else 1-tx)*(tz if dz else 1-tz)
    return out


def foam_face_weight(sx,sz,angle,offshore,breaking,scale,wavelength,footprint):
    """Static crest/wake approximation; angle points toward wave travel.

    Positive along-wave slope rises toward the crest from its trailing side.
    Wind whitecaps retain a small active front component and a stronger wake;
    depth-limited rollers favour the front face. This is not foam advection.
    """
    from scipy.ndimage import gaussian_filter
    along=sx*math.cos(angle)+sz*math.sin(angle)
    along=gaussian_filter(along,max(.35,min(1.,wavelength*.02))/footprint,mode='nearest')
    trailing=.5+.5*np.tanh(along/max(1e-5,scale*wavelength*.04))
    wind_face=.18+.82*trailing
    shallow_face=1-.65*trailing
    activity=offshore+(1-offshore)*breaking
    return (offshore*wind_face+(1-offshore)*breaking*shallow_face)/np.maximum(activity,1e-6)


def foam_field(sx,sz,depth,shoal,macro,a,angle,footprint,x,z,check,direction_angle=None,elevation=None,lua_flags=None):
    if not a['foam'] or not a['normal_strength']:return np.zeros_like(sx)
    keys=('normal_source','normal_map_path','surface_model','ocean_pattern','imported_span','imported_flip_y','seed','ripple_scale','wind','breakup','micro_detail','peak_enhancement','choppiness','ripple_ratio')
    direction_angle=angle if direction_angle is None else direction_angle
    offshore=smooth(.2,.95,a['wind'])
    # Detail waves are shading-only: they must not raise the breaking/foam activity.
    height=a['ripple_scale']*.1*a['wind']**2*shoal
    breaking=smooth(.2,.8,height/np.maximum(depth,.5))
    activity=1-(1-offshore)*(1-breaking)
    from scipy.ndimage import maximum_filter
    # Use the wave frame for both breakup fields: rotating the surface must also
    # rotate its foam, including the common rotation of imported/library maps.
    ca,sa=math.cos(direction_angle),math.sin(direction_angle);u=x*ca+z*sa;v=-x*sa+z*ca
    variation=foam_variation(u,v,max(8,a['ripple_scale']*1.2),a['seed']+3517)
    if elevation is not None and a['surface_model']=='lua_waves' and lua_flags is not None:
        # Foam flags are evaluated inside each band and carried by the owner,
        # exactly like the supplied Lua. This keeps a thin crest line instead of
        # blobs caused by composited-slope seams.
        wave,front,comp=lua_flags
        if a['foam_style']=='classic':
            gaps=foam_variation(u,v,max(6,a['ripple_scale']*.9),a['seed']+9517)
            foam=.95*activity*smooth(.30,.60,wave)
            foam*=1-a['wind']**.4*(1-smooth(.28,.48,gaps))
            return foam.astype(np.float32)
        gaps=foam_variation(u,v,max(6,a['ripple_scale']*.9),a['seed']+9517)
        noise=foam_variation(u,v,max(4,a['ripple_scale']*.35),a['seed']+18371)
        white=(comp>=.12)&(front>.015)&(wave+.22*comp>=.47)
        residual=(front>.085)&(comp>=.09)&(wave>=.10)&(wave<.57)&(noise>.64)
        foam=np.maximum(white.astype(np.float32),residual.astype(np.float32)*.85)
        foam*=activity*(1-.35*(1-smooth(.28,.48,gaps)))
        return foam.astype(np.float32)
    if elevation is not None and a['surface_model']=='lua_waves':
        amp=max(.08,float(np.percentile(np.abs(elevation-np.median(elevation)),95)))
        wave=(elevation-np.median(elevation))/amp
        support=.95*activity*smooth(.45,.70,wave)
        check();white,residual=foam_waves.whitecaps(sx,sz,direction_angle,footprint,a['ripple_scale'],support,x,z,
            elevation=elevation,seed=a['seed'],check=check)
        return np.maximum(white,residual*.85).astype(np.float32)
    check();scale=foam_calibration(tuple((k,a[k]) for k in keys),angle);check()
    score=crest_curvature(sx,sz,a['ripple_scale'],footprint,direction_angle if mapped_ocean(a) else None)/scale
    score*=1+a['crest_bias']*(macro-.5)
    threshold=.12+2.2*(1-a['foam'])**2+1.4*(1-activity)
    threshold+=3*a['wind']**1.5*(1-smooth(.28,.56,variation))
    foam=.95*activity*smooth(threshold,threshold+.18,score)
    # Grow only along connected crest shoulders. Never bridge an unsupported trough.
    support=.95*activity*smooth(.12,.6,score)
    grown=foam.copy()
    for _ in range(max(1,int(round(min(3,a['ripple_scale']*.4)/footprint)))):
        grown=np.maximum(grown,np.minimum(maximum_filter(grown,3,mode='nearest')*.9,support))
    foam=np.maximum(foam,grown*smooth(.32,.56,variation)*a['wind']**.6)
    gaps=foam_variation(u,v,max(6,a['ripple_scale']*.9),a['seed']+9517)
    foam*=1-a['wind']**.4*(1-smooth(.28,.48,gaps))
    # Apply after shoulder growth so it cannot spread back onto the wrong face.
    foam*=foam_face_weight(sx,sz,direction_angle,offshore,breaking,scale,a['ripple_scale'],footprint)
    if a['foam_style']=='whitecaps':
        # Lua whitecap judgement inside the existing eligible mask: horizontal
        # compression, downwind front slope and normalized crest height.
        check()
        # The legacy mask is weighted toward the trailing shoulder, where the
        # along-travel compression is near zero. Whitecaps may use the broader
        # normal-driven crest support so the crest front is not starved.
        support=np.clip((foam+smooth(.12,.6,score)*.5),0,1)
        white,residual=foam_waves.whitecaps(sx,sz,direction_angle,footprint,a['ripple_scale'],support,x,z,
            elevation=elevation,seed=a['seed'],check=check)
        return np.maximum(white,residual*.85).astype(np.float32)
    if a['foam_style']=='lua_crests' and not mapped_ocean(a) and a['surface_model'] in ('fft_normals','procedural','lua_waves'):
        check()
        foam=foam_style.lua_crests(foam,x,z,direction_angle,a['ripple_scale'],a['seed'],footprint,foam_variation)
    return foam.astype(np.float32)


def light_fields(normals,a,depth=None):
    """Fixed bake lighting shared by procedural surfaces and normal-map experiments."""
    da,el=map(math.radians,(a['light_direction'],a['light_elevation']))
    light=np.array([math.cos(da)*math.cos(el),math.sin(da)*math.cos(el),math.sin(el)],np.float32)
    va,ve=map(math.radians,(a['view_direction'],a['view_elevation']))
    view=np.array([math.cos(va)*math.cos(ve),math.sin(va)*math.cos(ve),math.sin(ve)],np.float32);half=(light+view);half/=np.linalg.norm(half)
    # Reverse body lighting artistically; specular highlights follow reversed slopes.
    if a['invert_normals']:normals=normals*np.array([-1,-1,1],np.float32)
    nh=np.maximum(0,normals@half);nl=np.maximum(0,normals@light)
    rough=.003+.018*a['roughness']+.004*a['wind']
    glint=np.exp(-(1-nh)/rough)
    if a['invert_normals']:
        nl=1-nl
        # Move the specular lobe to the opposite slopes, without tinting all shadows.
        inverse=normals*np.array([-1,-1,1],np.float32)
        glint=np.exp(-(1-np.maximum(0,inverse@half))/rough)
    reflection=np.clip(a['reflection']*smooth(.025,.85,glint),0,.95)
    return nl,reflection,glint


def body_illumination(nl,wavelength=24.,footprint=1.,softness=3.):
    """Soften subsurface shading separately from sharp normals, foam and glints."""
    return water_colour.illumination(nl,softness,footprint)


def shade_surface(normals,foam,c,a,depth=None,body_light=None):
    nl,reflection,_=light_fields(normals,a,depth)
    colours=[colour.hex_rgb(k) for k in (c['light'],c['dark'],a['crest'],a['foam_colour'])]
    if body_light is None:body_light=body_illumination(nl,softness=a['shadow_softness'])
    return water_colour.shade(body_light,a['shallow_depth'] if depth is None else depth,reflection,foam,colours,a)


def _prepare_surface(f,c,a,size=None,check=lambda:None,progress=None,packet_gpu=None):
    a=effective(f,a)
    w,l=f['settings']['width'],f['settings']['length'];ow,ol=size or (w,l)
    border=50
    z,x=np.mgrid[-border:ol+border,-border:ow+border].astype(np.float32);x=(x+.5)*w/ow-.5;z=(z+.5)*l/ol-.5
    h=np.array(f['heights'],np.float32).reshape(l,w)
    h=(h-h.min())/np.ptp(h) if np.ptp(h) else np.full_like(h,.5)
    footprint=max(w/ow,l/ol)
    angle=math.radians(wave_heading(f['settings'],a))
    foam_angle=angle
    depth=depth_field(x,z,w,l,c,a);shallow=np.exp(-depth/24)
    mapped=a['normal_source']=='imported' or a['surface_model']=='ocean_maps'
    normal_map_like=mapped or a['surface_model']=='lua_waves'
    elevation=None
    swell=np.zeros_like(x)
    if mapped:
        n,heat=normal_maps.load(a['normal_map_path']) if a['normal_source']=='imported' else ocean_library.baseline(a['ocean_pattern'])
        # Align the source's intrinsic crest-normal axis with the shared heading.
        angle-=texture_synthesis.dominant_wave_axis(n,a['imported_flip_y'])
        a={**a,'ripple_scale':texture_synthesis.characteristic_wavelength(n,a['imported_span'])}
        ca,sa=math.cos(angle),math.sin(angle)
        px,pz,_=texture_synthesis.sample(n,heat,x*ca+z*sa,-x*sa+z*ca,a['imported_span'],a['seed'],flip_y=texture_synthesis.ocean_y_flip(n,a['imported_flip_y']),footprint=footprint,preserve_direction=True,check=check,progress=progress)
        sx=px*ca-pz*sa;sz=px*sa+pz*ca
    else:
        # Sample a filter halo so resizing the selection does not change edge normals.
        halo=max(2,int(np.ceil(a['ripple_scale']*.08/footprint*4)))
        hz,hx=np.mgrid[-halo-border:ol+halo+border,-halo-border:ow+halo+border].astype(np.float32)
        hx=(hx+.5)*w/ow-.5;hz=(hz+.5)*l/ol-.5
        px,pz,jac,nx,nz=water_depth.phase_coordinates(hx,hz,w,l,c,a,a['ripple_scale'],angle)
        # Warped samples depend on depth, so bypass the regular-grid field cache.
        if a['depth_refraction']:
            import water_packets
            if a['surface_model']=='fft_normals':evaluator=water_spectrum.fields
            elif a['surface_model']=='lua_waves':evaluator=lua_waves.fields
            else:evaluator=water_packets.fields
            # Same wind scaling as surface_fields.generate(): refraction bends the
            # carrier phase and must not also change crest sharpness.
            wind_gain=.15+.85*a['wind']
            if a['surface_model']=='fft_normals':kwargs=dict(wind=a['wind'],gamma=a['peak_enhancement'],choppiness=a['choppiness']*wind_gain,ripple_ratio=a['ripple_ratio'])
            elif a['surface_model']=='lua_waves':kwargs={'layers':int(a.get('lua_layers',1))}
            else:kwargs={}
            values=[np.empty_like(px) for _ in range(4)]
            for start in range(0,len(px),32):
                check();sl=slice(start,start+32)
                fields=evaluator(px[sl],pz[sl],a['ripple_scale'],angle,a['breakup'],a['seed'],a['micro_detail']*wind_gain,footprint,**kwargs)
                for target,field in zip(values,fields):target[sl]=field
                if progress:progress(min(start+32,len(px)),len(px))
            elevation,sx,sz,raw=values
            along=sx*nx+sz*nz;sx=sx+(jac-1)*along*nx;sz=sz+(jac-1)*along*nz
        else:elevation,sx,sz,raw=surface_fields.generate(hx,hz,a,angle,footprint,check,progress,packet_gpu)
        crop=(slice(halo,-halo),slice(halo,-halo))
        if a['surface_model']=='procedural':
            # A bounded harmonic steepens existing crests without a separate mask.
            k=2*np.pi/a['ripple_scale'];q=k*elevation
            sharpen=1+.35*a['wind']*np.tanh(q)
            sx=sx*sharpen;sz=sz*sharpen
        elevation=elevation[crop]
    bottom,shoal=water_depth.response(depth,a['ripple_scale'])
    # Preserve carrier locations and scale. Bathymetry modulates existing slopes,
    # never adds h*gradient(mask) ridges or randomly erases large surface patches.
    from scipy.ndimage import gaussian_filter
    # The seabed affects each scale separately. Fine ripples remain wind-driven
    # when their own wavelength is too short to interact with the bottom.
    if not mapped and not normal_map_like:
        fine_bottom,fine_shoal=water_depth.response(depth,max(3,a['ripple_scale']*a['ripple_ratio']))
        low_x=gaussian_filter(sx,max(.5,a['ripple_scale']*.08/footprint),mode='nearest')
        low_z=gaussian_filter(sz,max(.5,a['ripple_scale']*.08/footprint),mode='nearest')
        low_x=low_x[crop];low_z=low_z[crop];sx=sx[crop];sz=sz[crop]
        fine_gain=fine_shoal*(1+.35*fine_bottom)
        large_gain=shoal*(1+.35*bottom)
        sx=low_x*large_gain+(sx-low_x)*fine_gain
        sz=low_z*large_gain+(sz-low_z)*fine_gain
    elif not mapped:
        sx=sx[crop];sz=sz[crop]
    strength=a['normal_strength'] if normal_map_like else (.05+.72*a['wind']**1.25)*a['normal_strength']
    foam_sx=sx.copy();foam_sz=sz.copy()
    sx=sx*strength;sz=sz*strength
    if not normal_map_like and a['swell_strength']>0:
        swell_a={**a,'surface_model':'procedural','ripple_scale':a['swell_scale'],
                 'seed':(a['seed']+9173)%2147483647,'wind':.3,'micro_detail':0.,
                 'peak_enhancement':1.5,'choppiness':.35}
        we,wx,wz,wc=surface_fields.generate(x,z,swell_a,angle,footprint,check,progress,packet_gpu)
        swell=np.clip(we/0.9,-1,1)
        _,sg=water_depth.response(depth,a['swell_scale'])
        gain=a['swell_strength']*.35*a['normal_strength']*sg
        sx=sx+wx*gain;sz=sz+wz*gain
        foam_sx+=wx*a['swell_strength']*.35*sg;foam_sz+=wz*a['swell_strength']*.35*sg
    if a['foundation_normals'] and not normal_map_like:
        from scipy.ndimage import map_coordinates
        macro_height=np.asarray(f['heights'],np.float32).reshape(l,w)
        macro_height=gaussian_filter(macro_height-macro_height.min(),max(1.,f['settings']['wavelength']*.025))
        mz,mx=np.gradient(macro_height)
        at=[z,x]
        sx=sx+a['foundation_normals']*a['normal_strength']*map_coordinates(mx,at,order=1,mode='nearest')
        sz=sz+a['foundation_normals']*a['normal_strength']*map_coordinates(mz,at,order=1,mode='nearest')
    normals=np.stack([-sx,-sz,np.ones_like(x)],axis=-1)
    normals/=np.linalg.norm(normals,axis=-1,keepdims=True)
    relief=surface_relief.from_slopes(sx,sz,a['ripple_scale'],footprint)
    if a['invert_normals']:normals[:,:,:2]*=-1
    macro=h[np.clip(np.round(z).astype(int),0,l-1),np.clip(np.round(x).astype(int),0,w-1)]
    lua_flags=None
    if a['surface_model']=='lua_waves':
        check();lua_flags=lua_waves.foam_owner(x,z,a['ripple_scale'],angle,a['breakup'],a['seed'],a['micro_detail'],footprint,int(a['lua_layers']))
    foam=foam_field(foam_sx,foam_sz,depth,shoal,macro,a,angle,footprint,x,z,check,direction_angle=foam_angle,elevation=elevation,lua_flags=lua_flags)
    body_light=np.zeros_like(x);reflection=np.zeros_like(x)
    masks=np.concatenate([np.stack([depth/128,relief,foam,body_light],-1),normals*.5+.5,reflection[...,None],swell[...,None].astype(np.float32)],axis=-1)
    return normals.astype(np.float32),masks.astype(np.float32),border


def prepare(f,c,a,size=None,check=lambda:None,progress=None,packet_gpu=None):
    if a['surface_model']=='lava':return lava_surface.prepare(f,a,size,check,progress)
    check();key=surface_cache.key(f,c,a,size,packet_gpu is not None)
    cached=surface_cache.get(key)
    if cached is None:
        cached=_prepare_surface(f,c,a,size,check,progress,packet_gpu)
        check();surface_cache.put(key,cached)
    normals,stored,border=cached
    masks=stored.copy()
    w,l=f['settings']['width'],f['settings']['length'];ow,ol=size or (w,l)
    nl,reflection,_=light_fields(normals,a,masks[...,0]*128)
    masks[...,3]=body_illumination(nl,footprint=max(w/ow,l/ol),softness=a['shadow_softness'])
    masks[...,7]=reflection
    check()
    return normals[border:-border,border:-border],masks[border:-border,border:-border]


def cpu(f,c,a,size=None,check=lambda:None,progress=None):
    normals,masks=prepare(f,c,a,size,check,progress)
    if a['surface_model']=='lava':return lava_surface.shade(normals,masks[:,:,2],a),masks
    return shade_surface(normals,masks[:,:,2],c,a,masks[:,:,0]*128,masks[:,:,3]),masks


VERTEX='''#version 130
void main(){vec2 p=gl_VertexID==0?vec2(-1,-1):(gl_VertexID==1?vec2(3,-1):vec2(-1,3));gl_Position=vec4(p,0,1);}
'''
FRAGMENT='''#version 130
uniform vec4 dims,lighting,colourControls;
uniform float wind,lavaGlow,shadingContrast,shadingMidpoint;
uniform int lavaMode,invertNormals;
uniform vec3 lavaCold,lavaHot,lavaPeak,bakeView;
uniform vec3 shallowColour,deepColour,crestColour,foamColour;
uniform sampler2D surfaceData,surfaceAux;
out vec4 outputColour;
void main(){
ivec2 pos=ivec2(gl_FragCoord.x,dims.w-gl_FragCoord.y);
vec4 data=texelFetch(surfaceData,pos,0);vec3 n=data.xyz;float foam=data.w;
if(lavaMode==1){
 float glow=foam*(.35+.65*lavaGlow);float hot=pow(clamp((foam-.55)/.45,0.,1.),2.)*lavaGlow;
 vec3 crust=lavaCold*(.55+.45*n.z);
 outputColour=vec4(mix(mix(crust,lavaHot,glow),lavaPeak,hot),1.);return;
}
if(invertNormals==1)n.xy=-n.xy;
vec3 light=vec3(cos(lighting.x)*cos(lighting.y),sin(lighting.x)*cos(lighting.y),sin(lighting.y));
vec3 view=bakeView,halfway=normalize(light+view);
float nh=max(0.,dot(n,halfway)),nv=clamp(dot(n,view),0.,1.),nl=max(0.,dot(n,light));
float depth=texelFetch(surfaceAux,pos,0).x*128.;
float rough=.003+.018*lighting.w+.004*wind;
float glint=exp(-(1.-nh)/rough);
if(invertNormals==1){nl=1.-nl;glint=exp(-(1.-max(0.,dot(n*vec3(-1.,-1.,1.),halfway)))/rough);}
float reflection=clamp(lighting.z*smoothstep(.025,.85,glint),0.,.95);
float bodyLight=texelFetch(surfaceAux,pos,0).w;
''' + water_colour.GLSL + '''
rgb=mix(rgb,crestColour,reflection);rgb=mix(rgb,foamColour,foam);
rgb=mix(12.92*rgb,1.055*pow(max(rgb,vec3(0.)),vec3(1./2.4))-.055,step(vec3(.0031308),rgb));
outputColour=vec4(rgb,1.);
}
'''


class GPU:
    def __init__(self,surface):
        from PySide6.QtGui import QOpenGLContext
        from PySide6.QtOpenGL import QOpenGLShaderProgram,QOpenGLShader,QOpenGLVertexArrayObject
        self.ctx=QOpenGLContext();self.ctx.setFormat(surface.format());self.program=None;self.vao=None;self.packets=None
        if not self.ctx.create() or not self.ctx.makeCurrent(surface): raise RuntimeError('Offscreen OpenGL unavailable')
        self.gl=self.ctx.functions();self.renderer=self.gl.glGetString(0x1F01);self.program=QOpenGLShaderProgram()
        try:
            for kind,src in [(QOpenGLShader.ShaderTypeBit.Vertex,VERTEX),(QOpenGLShader.ShaderTypeBit.Fragment,FRAGMENT)]:
                if not self.program.addShaderFromSourceCode(kind,src): raise RuntimeError(self.program.log())
            if not self.program.link(): raise RuntimeError(self.program.log())
            self.vao=QOpenGLVertexArrayObject();self.vao.create();self.vao.bind()
        except Exception: self.close();raise

    def packet_fields(self,*args):
        from packet_gpu import PacketGPU
        if self.packets is None:self.packets=PacketGPU(self.gl,VERTEX)
        self.vao.bind()
        return self.packets.fields(*args)

    def render(self,f,c,a,size=None,check=lambda:None,progress=None):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QImage,QVector3D,QVector4D
        from PySide6.QtOpenGL import QOpenGLTexture,QOpenGLFramebufferObject
        normals,masks=prepare(f,c,a,size,check,progress,self.packet_fields if a['surface_model']=='procedural' and a['normal_source']!='imported' else None)
        ol,ow=normals.shape[:2]
        data=np.ascontiguousarray(np.concatenate([normals,masks[:,:,2:3]],axis=-1),dtype=np.float32)
        tex=QOpenGLTexture(QOpenGLTexture.Target.Target2D)
        aux=QOpenGLTexture(QOpenGLTexture.Target.Target2D)
        try:
            aux.setFormat(QOpenGLTexture.TextureFormat.RGBA32F);aux.setSize(ow,ol);aux.setMipLevels(1)
            aux.allocateStorage(QOpenGLTexture.PixelFormat.RGBA,QOpenGLTexture.PixelType.Float32)
            aux.setData(QOpenGLTexture.PixelFormat.RGBA,QOpenGLTexture.PixelType.Float32,np.ascontiguousarray(masks[:,:,:4]).tobytes())
            aux.setMinMagFilters(QOpenGLTexture.Filter.Nearest,QOpenGLTexture.Filter.Nearest)
            tex.setFormat(QOpenGLTexture.TextureFormat.RGBA32F);tex.setSize(ow,ol);tex.setMipLevels(1)
            tex.allocateStorage(QOpenGLTexture.PixelFormat.RGBA,QOpenGLTexture.PixelType.Float32)
            tex.setData(QOpenGLTexture.PixelFormat.RGBA,QOpenGLTexture.PixelType.Float32,data.tobytes())
            tex.setMinMagFilters(QOpenGLTexture.Filter.Nearest,QOpenGLTexture.Filter.Nearest)
            fbo=QOpenGLFramebufferObject(QSize(ow,ol))
            if not fbo.isValid(): raise RuntimeError('Offscreen bake target unavailable')
            fbo.bind();self.gl.glViewport(0,0,ow,ol);aux.bind(1);tex.bind(0);self.vao.bind()
            self.gl.glDisable(0x0BE2);self.gl.glDisable(0x0B71);p=self.program;p.bind()
            p.setUniformValue(p.uniformLocation('dims'),QVector4D(ow,ol,ow,ol))
            p.setUniformValue(p.uniformLocation('lighting'),QVector4D(math.radians(a['light_direction']),math.radians(a['light_elevation']),a['reflection'],a['roughness']))
            p.setUniformValue(p.uniformLocation('colourControls'),QVector4D(a['lit_strength'],a['depth_colour_influence'],a['depth_colour_reach'],a['shading_strength']))
            va,ve=map(math.radians,(a['view_direction'],a['view_elevation']))
            p.setUniformValue(p.uniformLocation('bakeView'),QVector3D(math.cos(va)*math.cos(ve),math.sin(va)*math.cos(ve),math.sin(ve)))
            self.gl.glUniform1f(p.uniformLocation('wind'),a['wind'])
            self.gl.glUniform1f(p.uniformLocation('shadingContrast'),a['shading_contrast'])
            self.gl.glUniform1f(p.uniformLocation('shadingMidpoint'),a['shading_midpoint'])
            self.gl.glUniform1i(p.uniformLocation('lavaMode'),int(a['surface_model']=='lava'))
            self.gl.glUniform1i(p.uniformLocation('invertNormals'),int(a['invert_normals']))
            self.gl.glUniform1f(p.uniformLocation('lavaGlow'),a['lava_glow'])
            for name,key in [('lavaCold','lava_cold'),('lavaHot','lava_hot'),('lavaPeak','lava_peak')]:
                p.setUniformValue(p.uniformLocation(name),QVector3D(*[v/255 for v in colour.hex_rgb(a[key])]))
            for name,val in [('shallowColour',c['light']),('deepColour',c['dark']),('crestColour',a['crest']),('foamColour',a['foam_colour'])]:
                rgb=np.array(colour.hex_rgb(val),float)/255;rgb=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
                p.setUniformValue(p.uniformLocation(name),QVector3D(*rgb.tolist()))
            self.gl.glUniform1i(p.uniformLocation('surfaceData'),0)
            self.gl.glUniform1i(p.uniformLocation('surfaceAux'),1)
            self.gl.glDrawArrays(0x0004,0,3)
            if self.gl.glGetError(): raise RuntimeError('OpenGL surface lighting failed')
            img=fbo.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            rgb=np.frombuffer(img.constBits(),np.uint8).reshape(ol,ow,4)[:,:,:3].copy()
            p.release();fbo.release()
            return rgb,masks
        finally: tex.destroy();aux.destroy()

    def close(self):
        if self.packets is not None:self.packets.close()
        if self.vao is not None: self.vao.destroy()
        if self.program is not None: self.program.removeAllShaders()
        self.ctx.doneCurrent()
