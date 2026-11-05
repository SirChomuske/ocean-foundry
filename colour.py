"""Independent solid coating, virtual depth field and texture-derived matching."""
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import sys
import numpy as np
import dither
import defaults

# Owned by default_settings.json so new installations and missing-key fallbacks agree.
DEFAULTS = defaults.section('colour')


def validate(settings):
    s={**DEFAULTS,**{k:v for k,v in settings.items() if k in DEFAULTS}}
    for k in ['enabled','creative']:
        if type(s[k]) is not bool: raise ValueError(k+' must be true or false.')
    for k in ['light','dark']:
        if not isinstance(s[k],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',s[k]):
            raise ValueError('Colours must use #RRGGBB.')
        s[k]=s[k].lower()
    for k,lo,hi in [('texture_preference',0,1),('depth_slope',0,1),('depth_direction',0,360),('palette_size',1,32),
                    ('dither_strength',0,1),('dither_grain',1,8),('dither_seed',0,2147483647)]:
        v=float(s[k])
        if not math.isfinite(v) or not lo<=v<=hi: raise ValueError(k+' is outside its allowed range.')
        s[k]=v
    for k in ['palette_size','dither_grain','dither_seed']:
        if int(s[k])!=s[k]: raise ValueError(k+' must be an integer.')
        s[k]=int(s[k])
    if s['dither_method'] not in dither.METHODS: raise ValueError('Unknown dithering method.')
    if not isinstance(s['excluded'],list) or any(not isinstance(v,str) for v in s['excluded']):
        raise ValueError('Excluded blocks must be a list of block IDs.')
    s['excluded']=sorted(set(s['excluded']))
    replacements=s['block_replacements']
    if not isinstance(replacements,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in replacements.items()):
        raise ValueError('Block replacements must map block IDs to block IDs.')
    s['block_replacements']=dict(replacements)
    return s


def similar_blocks(block_id,settings,limit=24):
    blocks={b['id']:b for b in catalogue()}
    if block_id not in blocks: return []
    source=rgb_to_lab(blocks[block_id]['top_rgb'])
    eligible=[b for b in blocks.values() if (settings['creative'] or b['survival_friendly']) and b['id'] not in settings['excluded']]
    ranked=sorted(((float(np.linalg.norm(rgb_to_lab(b['top_rgb'])-source)),b) for b in eligible),key=lambda p:p[0])
    return [(b,d) for d,b in ranked if d<=25][:limit]


@lru_cache(maxsize=1)
def catalogue():
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
    data=json.loads((root/'palette_26_1_2.json').read_text(encoding='utf-8'))
    if data['minecraft_version']!='26.1.2' or data['data_version']!=4790:
        raise ValueError('Unexpected block palette version.')
    return data['blocks']


def rgb_to_lab(rgb):
    rgb=np.asarray(rgb,dtype=float)/255
    linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    xyz=linear @ np.array([[.4124564,.3575761,.1804375],[.2126729,.7151522,.072175],
                          [.0193339,.119192,.9503041]]).T / np.array([.95047,1,1.08883])
    f=np.where(xyz>(6/29)**3,np.cbrt(xyz),xyz/(3*(6/29)**2)+4/29)
    return np.stack([116*f[...,1]-16,500*(f[...,0]-f[...,1]),200*(f[...,1]-f[...,2])],axis=-1)


def lab_to_rgb(lab):
    lab=np.asarray(lab,dtype=float)
    fy=(lab[...,0]+16)/116
    f=np.stack([fy+lab[...,1]/500,fy,fy-lab[...,2]/200],axis=-1)
    xyz=np.where(f>6/29,f**3,3*(6/29)**2*(f-4/29))*np.array([.95047,1,1.08883])
    linear=xyz @ np.array([[3.2404542,-1.5371385,-.4985314],[-.969266,1.8760108,.041556],
                          [.0556434,-.2040259,1.0572252]]).T
    rgb=np.where(linear<=.0031308,12.92*linear,1.055*np.maximum(linear,0)**(1/2.4)-.055)
    return np.clip(np.round(rgb*255),0,255).astype(np.uint8)


def hex_rgb(value):
    return [int(value[i:i+2],16) for i in [1,3,5]]








def coating_geometry(foundation,compact=False):
    """Owner 0=air, 1=concrete, 2+n=colour associated with source surface n.

    Cover tops and upper exposed steps only. Hollow space below any column's
    concrete top is protected, as is the perimeter below its top cap.
    """
    s=foundation['settings']; w,l=s['width'],s['length']
    tops=np.asarray(foundation['heights']).reshape(l,w)
    bottoms=np.asarray(foundation['bottoms']).reshape(l,w)
    owner=np.zeros((int(tops.max())+2,l+2,w+2),dtype=np.uint8 if compact else np.int32)
    yy=np.arange(owner.shape[0])[:,None,None]
    original=(yy>=bottoms)&(yy<=tops)
    owner[:,1:-1,1:-1][original]=1
    zz,xx=np.mgrid[:l,:w]
    donor=np.full((l,w),2,dtype=np.uint8) if compact else np.arange(w*l,dtype=np.int32).reshape(l,w)+2
    owner[tops+1,zz+1,xx+1]=donor
    # Treat each surface column as filled downwards for coating purposes only.
    # This prevents a low neighbour depositing colour under a higher shell.
    ceiling=np.pad(tops,1,constant_values=owner.shape[0])
    for target,limit in [(owner[:,1:-1,:-2],ceiling[1:-1,:-2]),
                         (owner[:,1:-1,2:],ceiling[1:-1,2:]),
                         (owner[:,:-2,1:-1],ceiling[:-2,1:-1]),
                         (owner[:,2:,1:-1],ceiling[2:,1:-1])]:
        exposed=original & (target==0) & (yy>limit)
        np.copyto(target,np.broadcast_to(donor,target.shape),where=exposed)
    owner.flags.writeable=False
    return owner


