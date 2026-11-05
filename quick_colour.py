"""Small target renders with reusable fields; no material matching or voxel work."""
import appearance
import colour
import ocean
import lava_surface
import surface_cache


def foundation(s,a,previous=None):
    geometry=appearance.foundation_settings(s,a)
    if previous and previous['settings']==s and previous.get('geometry_settings',previous['settings'])==geometry:
        return dict(settings=s,geometry_settings=geometry,heights=previous['heights'])
    return {**ocean.generate(geometry),'settings':s,'geometry_settings':geometry}


def cache_fields(f,c,a,m,size):
    raw=None
    if a['surface_model']!='lava':
        for gpu in (False,True):
            raw=surface_cache.get(surface_cache.key(f,c,a,size,gpu))
            if raw is not None:break
    if raw is None:raw=(m[...,4:7]*2-1,m,0)
    return dict(foundation=f,signature=surface_cache.signature(f['settings'],c,a),
                raw=raw,size=size,footprint=max(f['settings']['width']/size[0],f['settings']['length']/size[1]))


def from_bake(result):
    f={key:result[key] for key in ('settings','geometry_settings','heights')}
    m=result['preview_fields'];size=(m.shape[1],m.shape[0])
    return cache_fields(f,result['colour_settings'],result['appearance_settings'],m,size)


def render(settings,colours,appearance_settings,cached=None,previous=None,check=lambda:None):
    s=ocean.validate(settings);c=colour.validate(colours);a=appearance.validate(appearance_settings)
    check();size=(min(192,s['width']),min(192,s['length']))
    signature=surface_cache.signature(s,c,a)
    reused=cached is not None and cached['signature']==signature and cached['size']==size
    if not reused:
        f=foundation(s,a,cached['foundation'] if cached else previous)
        check();_,m=appearance.prepare(f,c,a,size,check)
        cached=cache_fields(f,c,a,m,size)
    n,m,border=cached['raw'];check()
    if a['surface_model']=='lava':rgb=lava_surface.shade(n,m[...,2],a)
    else:
        nl,_,_=appearance.light_fields(n,a,m[...,0]*128)
        body=appearance.body_illumination(nl,footprint=cached['footprint'],softness=a['shadow_softness'])
        rgb=appearance.shade_surface(n,m[...,2],c,a,m[...,0]*128,body)
    if border:rgb=rgb[border:-border,border:-border]
    check()
    return dict(rgb=rgb,cache=cached,reused=reused)
