"""Explicit procedural bake: appearance -> joint material recipes -> block grid."""
from functools import lru_cache
from itertools import product
from pathlib import Path
import json
import sys
import time
import numpy as np
from scipy.spatial import cKDTree
from scipy.ndimage import gaussian_filter,median_filter
import ocean
import colour
import appearance
import dither
import mesh
import surface_mesh


class Cancelled(Exception): pass


@lru_cache(maxsize=1)
def glass_catalogue():
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
    return json.loads((root/'glass_26_1_2.json').read_text())['blocks']


def solid_features(rgb):
    """Lab accuracy plus relative RGB balance to avoid blue-to-purple substitutions."""
    rgb=np.asarray(rgb,dtype=float)
    balance=rgb/np.maximum(rgb.sum(axis=-1,keepdims=True),1.)
    return np.concatenate([colour.rgb_to_lab(rgb),balance*80.],axis=-1)


def choose_palette(target,c):
    candidates=[b for b in colour.catalogue() if (c['creative'] or b['survival_friendly']) and b['id'] not in c['excluded']]
    if not candidates: raise ValueError('All eligible solid blocks are excluded.')
    # Colour bins retain rare intermediate/highlight shades that a spatial stride
    # can miss. Mean colours and population weights preserve the target balance.
    pixels=target.reshape(-1,3).astype(np.float64)
    bins=(pixels.astype(np.uint32)//8)
    codes=bins[:,0]*1024+bins[:,1]*32+bins[:,2]
    _,inverse,counts=np.unique(codes,return_inverse=True,return_counts=True)
    samples=np.stack([np.bincount(inverse,weights=pixels[:,channel])/counts for channel in range(3)],axis=-1)
    weights=counts/counts.sum()
    # Match the rendered target only. Inactive colour controls must not reserve
    # palette slots or change the blocks through a second, hidden influence.
    labs=colour.rgb_to_lab([b['top_rgb'] for b in candidates])
    distances=np.sum((solid_features(samples)[:,None,:]-solid_features([b['top_rgb'] for b in candidates])[None,:,:])**2,axis=2)
    # Texture preference is charged where a block is used, not once against the
    # entire image whenever a new shade is added. The former cost stopped useful
    # palette expansion early, especially with smooth-texture preference at one.
    distances+=c['texture_preference']*np.array([b.get('texture_variation',0) for b in candidates])[None,:]*2
    best=np.full(len(samples),np.inf); selected=[]
    for _ in range(min(c['palette_size'],len(candidates))):
        score=weights@np.minimum(best[:,None],distances);score[selected]=np.inf
        i=int(np.argmin(score))
        if selected and weights@best-score[i]<1e-7:break
        selected.append(i); best=np.minimum(best,distances[:,i])
    return [candidates[i] for i in sorted(selected,key=lambda i:-labs[i,0])]


@lru_cache(maxsize=4)
def recipes(ids,max_layers):
    blocks={b['id']:b for b in colour.catalogue()}
    glass=glass_catalogue()
    stacks=[(0,0,0)]
    for n in range(1,max_layers+1): stacks.extend(tuple(p)+(0,)*(3-n) for p in product(range(1,len(glass)+1),repeat=n))
    stacks=np.array(stacks,dtype=np.uint8)
    rgb=np.array([[0,0,0]]+[b['rgb'] for b in glass],dtype=np.float32)
    alpha=np.array([0]+[b['alpha'] for b in glass],dtype=np.float32)
    tint=np.zeros((len(stacks),3),dtype=np.float32); transmission=np.ones((len(stacks),1),dtype=np.float32)
    previous=np.zeros(len(stacks),dtype=np.uint8)
    for i in range(3):
        state=stacks[:,i]; opacity=(alpha[state]*(state!=previous))[:,None]
        tint=tint*(1-opacity)+rgb[state]*opacity; transmission*=1-opacity; previous=state
    base_rgb=np.array([blocks[b]['top_rgb'] for b in ids],dtype=np.float32)
    combined=(base_rgb[:,None,:]*transmission[None,:,:]+tint[None,:,:]).reshape(-1,3)
    lengths=np.tile(np.count_nonzero(stacks,axis=1),len(ids))
    features=colour.rgb_to_lab(combined).astype(np.float32)
    groups={}
    for level in range(max_layers+1):
        positions=np.flatnonzero(lengths==level)
        for base in range(len(ids)):
            local=positions[(positions//len(stacks))==base]
            groups[(base,level)]=(local,cKDTree(features[local]))
    # Individual exposed glass faces matter at oblique views. Compare these
    # when mixing recipes so top-down-equivalent stacks cannot form bright speckle.
    side=base_rgb[:,None,None,:]*(1-alpha[stacks][None,:,:,None])+rgb[stacks][None,:,:,:]*alpha[stacks][None,:,:,None]
    side_lab=colour.rgb_to_lab(side).reshape(-1,3,3)
    return dict(stacks=stacks,rgb=combined,features=features,groups=groups,side_lab=side_lab)


def match_glass(tree, positions, features, threshold, side_lab=None):
    """Dither among near-equivalent tint recipes; never trade shape for colour."""
    distances,indices=tree.query(features,k=min(8,len(positions)),workers=1)
    if distances.ndim==1:return positions[indices]
    excess=distances-distances[:,:1]
    weights=np.where(excess<=1.5,np.exp(-excess/.6),0.)
    if side_lab is not None:
        sides=side_lab[positions[indices]]
        difference=np.linalg.norm(sides-sides[:,:1],axis=-1).max(axis=-1)
        weights*=np.where(difference<=12,np.exp(-difference/6),0.)
    cumulative=np.cumsum(weights,axis=1);cumulative/=cumulative[:,-1:]
    choice=np.minimum(np.sum(threshold[:,None]>cumulative,axis=1),indices.shape[1]-1)
    return positions[indices[np.arange(len(indices)),choice]]


def smooth_glass_coverage(counts,base_y,max_layers):
    """Continuous cover with coherent terraces; never modify the solid foundation.

    Filter recipe-length speckle, then raise low neighbours until the top changes
    by at most one block on gentle foundations. Steep concrete steps retain their
    own unavoidable step size. All lengths remain within the allowed stack depth.
    """
    if max_layers==0:return np.zeros_like(counts,dtype=np.uint8)
    filtered=gaussian_filter(np.asarray(counts,dtype=np.float32),1.2,mode='nearest')
    levels=np.clip(np.rint(median_filter(filtered,size=3,mode='nearest')),1,max_layers).astype(np.int32)
    base=np.asarray(base_y,dtype=np.int32);top=base+levels
    dx=np.maximum(1,np.abs(np.diff(base,axis=1)));dz=np.maximum(1,np.abs(np.diff(base,axis=0)))
    for _ in range(max_layers):
        previous=top.copy()
        top[:,1:]=np.maximum(top[:,1:],previous[:,:-1]-dx)
        top[:,:-1]=np.maximum(top[:,:-1],previous[:,1:]-dx)
        top[1:,:]=np.maximum(top[1:,:],previous[:-1,:]-dz)
        top[:-1,:]=np.maximum(top[:-1,:],previous[1:,:]-dz)
        if np.array_equal(previous,top):break
    return np.clip(top-base,1,max_layers).astype(np.uint8)


def build_preview(result,check=lambda:None):
    v=result['voxels']; height,length,width=v.shape
    samples={b['id']:b['top_rgb'] for b in colour.catalogue()}
    samples.update({b['id']:b['rgb'] for b in glass_catalogue()})
    rgb=np.array([samples.get(b['id'],[0,0,0]) for b in result['palette']],dtype=np.float32)/255
    padded=np.pad(result['block_rgb'],((1,1),(1,1),(0,0)),mode='edge')
    tops=np.pad(result['surface_base_y']+np.count_nonzero(result['glass_stacks'],axis=2)
              +(np.asarray(result.get('foam_glass',0))>0)+1,1)
    if max(width,length)<=130:
        side_samples={b['id']:b.get('side_rgb',b['top_rgb']) for b in colour.catalogue()}
        side_rgb=np.array([side_samples.get(b['id'],samples.get(b['id'],[0,0,0])) for b in result['palette']],dtype=np.float32)/255
        glass_states=np.array([b['id'].endswith('glass') for b in result['palette']])
        result['mesh']=surface_mesh.layer_mesh(v,rgb,padded,side_rgb,glass_states)
        note='Baked blocks · Approximate glass colours; exact exterior shape'
    else:
        step=max(2,int(np.ceil(max(width,length)/160)))
        m=surface_mesh.envelope(tops[::step,::step],padded[::step,::step],height)
        m['vertices'][:,:,[0,2]]*=step; m['centres']=m['vertices'].mean(axis=1)
        m.update(width=width,length=length,step=step,simplified=True)
        m['textured']=True
        result['preview_texture']=padded
        result['mesh']=m; note=f'Baked colours at full resolution · Geometry step {step}; exports exact'
    check()
    result['gpu_vertices']=mesh.triangle_data(result['mesh'])
    step=max(1,int(np.ceil(max(width,length)/32)))
    small=surface_mesh.envelope(tops[::step,::step],padded[::step,::step],height)
    small['vertices'][:,:,[0,2]]*=step;small['centres']=small['vertices'].mean(axis=1)
    small.update(width=width,length=length,step=step,simplified=True)
    result['interaction_mesh']=small
    result['preview_note']=note
    return result


def bake(settings,colour_settings,appearance_settings,progress=None,cancel=None,surface=None):
    started=time.perf_counter(); c=colour.validate(colour_settings); a=appearance.validate(appearance_settings)
    s=ocean.validate(settings)
    def check():
        if cancel is not None and cancel.is_set(): raise Cancelled('Bake cancelled; previous result retained.')
    def emit(stage,done=0,total=0,image=None,normal=None):
        check()
        if progress: progress(dict(stage=stage,done=done,total=total,image=image,normal=normal,elapsed=time.perf_counter()-started))
    emit('Preparing concrete geometry')
    geometry_settings=appearance.foundation_settings(s,a)
    f={**ocean.generate(geometry_settings),'settings':s,'geometry_settings':geometry_settings}; check()
    # Reserve the extra foam layer and, when enabled, the swell layer above it.
    # Lava has no foam/swell glass stage, so it keeps the tint-only budget.
    foam_extra=0 if a['surface_model']=='lava' else (1 if a['glass_layers'] else 0)
    max_layers=a['glass_layers']+foam_extra
    if s['base_y']+max(f['heights'])+1+max_layers>319:
        raise ValueError('The colour and glass layers would exceed Y 319. Lower placement Y, wave height or glass layers.')
    backend='CPU'; fallback=''; gpu=None
    if a['gpu'] and surface is not None:
        try:
            gpu=appearance.GPU(surface)
            source=('imported normals' if a['normal_source']=='imported' else
                {'fft_normals':'FFT','lava':'lava normals','ocean_maps':'library normals','procedural':'wave groups'}[a['surface_model']])
            backend=source+' + OpenGL lighting · '+gpu.renderer
        except Exception as exc: fallback=str(exc)
    try:
        render=gpu.render if gpu else appearance.cpu
        def field_progress(done,total):emit('Generating surface fields',done,total)
        emit('Generating procedural appearance')
        try:
            draft_size=(min(192,s['width']),min(192,s['length']))
            draft,dm=render(f,c,a,draft_size,check,field_progress)
            emit('Draft appearance',image=draft,normal=np.clip(dm[:,:,4:7]*255,0,255).astype(np.uint8))
            target,masks=render(f,c,a,check=check,progress=field_progress)
        except Exception as exc:
            check()
            if gpu is None: raise
            fallback=str(exc); backend='CPU fallback'
            draft,dm=appearance.cpu(f,c,a,draft_size,check,field_progress)
            target,masks=appearance.cpu(f,c,a,check=check,progress=field_progress)
    finally:
        if gpu is not None: gpu.close()
    emit('Matching solid palette',image=target,normal=np.clip(masks[:,:,4:7]*255,0,255).astype(np.uint8))
    automatic=choose_palette(target,c); check()
    target_lab=colour.rgb_to_lab(target);rows,cols=target.shape[:2]
    labs=solid_features([b['top_rgb'] for b in automatic]);solid_target=solid_features(target)
    tree=cKDTree(labs)
    _,baseline=tree.query(solid_target.reshape(-1,6),workers=1)
    baseline=baseline.reshape(rows,cols)
    if c['dither_method']=='diffusion' and c['dither_strength']:
        base_selection=dither.error_diffusion(solid_target,labs,c['dither_strength'],
            progress=lambda done,total:emit('Matching solid rows',done,total))
    else:
        base_selection=dither.assign(solid_target,labs,baseline,c['dither_method'],c['dither_strength'],c['dither_grain'],c['dither_seed'])
    base_selection=dither.blend_edges(baseline,base_selection,labs,c['dither_strength'],c['dither_method'],c['dither_grain'],c['dither_seed'])
    # Substitutions replace a material in its existing pattern; they do not
    # redistribute surface coverage or freeze the automatic palette.
    chosen=[];remap=[]
    for block in automatic:
        replacement=c['block_replacements'].get(block['id'],block['id'])
        actual=block
        if replacement!=block['id']:
            eligible={b['id']:b for b,_ in colour.similar_blocks(block['id'],c,limit=1000)}
            actual=eligible.get(replacement,block)
        if actual not in chosen:chosen.append(actual)
        remap.append(chosen.index(actual))
    base_selection=np.array(remap)[base_selection]
    emit('Preparing glass recipes')
    catalogue=recipes(tuple(b['id'] for b in chosen),a['glass_layers']);check()
    stack_count=len(catalogue['stacks'])
    # The continuous target and its assigned solids share one surface pattern.
    # No independent wave field, scale, direction or relief setting exists for glass.
    solid_rgb=np.array([b['top_rgb'] for b in chosen],dtype=np.uint8)[base_selection]
    relief=masks[:,:,1]
    features=target_lab.reshape(-1,3)
    selection=np.zeros(rows*cols,dtype=np.intp)
    tint_threshold=dither.threshold_grid((rows,cols),'noise',1,c['dither_seed']+733).ravel()
    owner=colour.coating_geometry(f,compact=True);check()
    h,l,w=owner.shape;coat=owner[:,1:-1,1:-1]>=2
    base_y=h-1-np.argmax(coat[::-1],axis=0)
    # Geometry is fixed before tint matching; colour cannot create terraces.
    coverage=1+max(0,a['glass_layers']-1)*relief
    lengths=smooth_glass_coverage(coverage,base_y,a['glass_layers'])
    changed=np.arange(rows*cols)
    for start in range(0,len(changed),4096):
        check();indices=changed[start:start+4096]
        for material in np.unique(base_selection.ravel()[indices]):
            for level in np.unique(lengths.ravel()[indices]):
                take=indices[(base_selection.ravel()[indices]==material)&(lengths.ravel()[indices]==level)]
                if not len(take):continue
                positions,tree=catalogue['groups'][(int(material),int(level))]
                selection[take]=match_glass(tree,positions,features[take],tint_threshold[take],catalogue['side_lab'])
        emit('Matching stained glass',min(start+4096,len(changed)),len(changed))
    stacks=catalogue['stacks'][selection%stack_count].reshape(rows,cols,3)
    # Foam hugs the colour layer: strong/medium foam replaces the top tint glass;
    # very faint foam adds one thin white layer above the tint stack.
    foam=masks[:,:,2]
    glass_states=glass_catalogue()
    white=next((i+1 for i,b in enumerate(glass_states) if b['id']=='minecraft:white_stained_glass'),0)
    light=next((i+1 for i,b in enumerate(glass_states) if b['id']=='minecraft:light_gray_stained_glass'),0)
    levels=np.count_nonzero(stacks,axis=2)
    top=np.maximum(levels.astype(np.int32),1)-1
    foam_layer=np.zeros((rows,cols),np.uint8)
    touched=np.zeros((rows,cols),bool)
    if a['surface_model']!='lava' and a['glass_layers']>0 and float(foam.max())>0:
        zz,xx=np.indices((rows,cols))
        strong=foam>=.55
        mild=(foam>=.25)&~strong
        faint=(foam>=.08)&(foam<.25)
        if white:stacks[zz[strong],xx[strong],top[strong]]=white
        if light:stacks[zz[mild],xx[mild],top[mild]]=light
        if white:foam_layer[faint]=white
        touched=strong|mild
    # Swell stays a reference field for shading; it must not overwrite the
    # colour layer with an extra glass band.
    swell_layer=np.zeros((rows,cols),np.uint8)
    emit('Building solid coverage and glass relief',image=np.clip(catalogue['rgb'][selection],0,255).astype(np.uint8).reshape(rows,cols,3))
    palette=[dict(id='minecraft:air',properties={}),dict(id='minecraft:'+s['block']+'_concrete',properties={})]
    def add(state):
        state={k:state[k] for k in ('id','properties')}
        if state not in palette: palette.append(state)
        return palette.index(state)
    base_indices=np.array([add(b) for b in chosen],dtype=np.uint8)
    glass_indices=np.array([0]+[add(b) for b in glass_catalogue()],dtype=np.uint8)
    extra=int(np.any(foam_layer>0))
    voxels=np.zeros((h+a['glass_layers']+extra,l,w),dtype=np.uint8)
    voxels[:h][owner==1]=1
    np.copyto(voxels[:h,1:-1,1:-1],np.broadcast_to(base_indices[base_selection],coat.shape),where=coat)
    zz,xx=np.indices((rows,cols))
    for i in range(a['glass_layers']):
        state=glass_indices[stacks[:,:,i]]
        voxels[base_y+1+i,zz+1,xx+1]=state
    base_ys=base_y+1+levels
    foam_mask=foam_layer>0
    if foam_mask.any():
        voxels[base_ys[foam_mask],zz[foam_mask]+1,xx[foam_mask]+1]=glass_indices[foam_layer[foam_mask]]
    falling_ids={i for i,b in enumerate(palette) if b['id'].endswith('_concrete_powder') or b['id'] in ('minecraft:sand','minecraft:red_sand','minecraft:gravel','minecraft:suspicious_sand','minecraft:suspicious_gravel','minecraft:dragon_egg')}
    support_count=0
    if falling_ids:
        floor=np.pad(np.asarray(f['heights']).reshape(rows,cols),1,constant_values=0)
        for y in range(1,len(voxels)):
            check();unsupported=np.isin(voxels[y],list(falling_ids)) & (voxels[y-1]==0)
            for below in range(y-1,-1,-1):
                put=unsupported & (voxels[below]==0) & (below>floor)
                if not put.any():break
                voxels[below][put]=1;support_count+=int(put.sum());unsupported=put
    counts=np.bincount(voxels.ravel(),minlength=len(palette))
    coat_weights=coat.sum(axis=0)
    selected_counts=np.bincount(base_selection.ravel(),weights=coat_weights.ravel(),minlength=len(chosen)).astype(int)
    surface_counts=np.bincount(base_selection.ravel(),minlength=len(chosen))
    glass_count=int(np.count_nonzero(stacks)+np.count_nonzero(foam_layer))
    composed=np.clip(catalogue['rgb'][selection],0,255).astype(np.uint8).reshape(rows,cols,3)
    rgb_glass=np.array([[0,0,0]]+[b['rgb'] for b in glass_states],np.float32)
    alpha=np.array([0]+[b['alpha'] for b in glass_states],np.float32)
    if touched.any():
        base=solid_rgb[touched].astype(np.float32);picked=stacks[touched]
        tint=np.zeros_like(base);trans=np.ones_like(base);prev=np.zeros(len(picked),np.uint8)
        for i in range(3):
            st=picked[:,i];op=(alpha[st]*(st!=prev))[:,None]
            tint=tint*(1-op)+rgb_glass[st]*op;trans*=1-op;prev=st
        composed[touched]=np.clip(base*trans+tint,0,255).astype(np.uint8)
    faint_mask=foam_layer>0
    if np.any(faint_mask) and white:
        op=float(alpha[white])
        base_col=composed[faint_mask].astype(np.float32)
        composed[faint_mask]=np.clip(base_col*(1-op)+rgb_glass[white]*op,0,255).astype(np.uint8)
    stats={**f['stats'], 'blocks':int(np.count_nonzero(voxels)), 'foundation_blocks':int(counts[1]),'support_blocks':support_count,
           'coating_blocks':int(coat.sum()), 'glass_blocks':glass_count,'height':voxels.shape[0],
           'volume':voxels.size,
           'max_y':s['base_y']+int(np.max(base_y+np.count_nonzero(stacks,axis=2)+(foam_layer>0)))}
    result={**f,'colour_settings':c,'appearance_settings':a,'voxels':voxels,'palette':palette,'stats':stats,
            'target_rgb':target,'block_rgb':composed,'solid_rgb':solid_rgb,
            'depth':masks[:,:,0]*128,
            'normal_rgb':np.clip(masks[:,:,4:7]*255,0,255).astype(np.uint8),
            'reflection_rgb':np.repeat(np.clip(masks[:,:,7:8]*255 if masks.shape[-1]>7 else np.zeros_like(masks[:,:,0:1]),0,255).astype(np.uint8),3,axis=2),
            'foam_rgb':np.repeat(np.clip(masks[:,:,2:3]*255,0,255).astype(np.uint8),3,axis=2),
            'selected_blocks':chosen,'selected_counts':selected_counts.tolist(),'surface_counts':surface_counts.tolist(),
            'automatic_blocks':automatic,
            'surface_relief':relief,
            'glass_counts':{b['id']:int(counts[idx]) for b,idx in zip(glass_catalogue(),glass_indices[1:])},
            'glass_stacks':stacks,'foam_glass':foam_layer,'surface_base_y':base_y,'export_offset':(-1,0,-1),
            'mean_colour_error':float(np.linalg.norm(colour.rgb_to_lab(composed)-target_lab,axis=-1).mean()),
            'preview_fields':dm,'preview_footprint':max(s['width']/draft_size[0],s['length']/draft_size[1]),
            'bake_backend':backend,'gpu_fallback':fallback,'procedural':True}
    del owner,coat
    emit('Preparing final 3D preview')
    build_preview(result,check)
    result['bake_seconds']=time.perf_counter()-started
    emit('Complete')
    return result


def layer(result,name):
    if name=='combined': return result
    v=result['voxels']; yy=np.arange(v.shape[0])[:,None,None]
    base=result['surface_base_y']
    if name=='foam':
        fg=np.asarray(result.get('foam_glass',0),dtype=np.uint8)>0
        levels=np.count_nonzero(result['glass_stacks'],axis=2)
        idx=np.indices(levels.shape);ys=base+1+levels
        out=np.zeros_like(v)
        if fg.any():out[ys[fg],idx[0][fg]+1,idx[1][fg]+1]=v[ys[fg],idx[0][fg]+1,idx[1][fg]+1]
        return {**result,'voxels':out,'stats':{**result['stats'],'blocks':int(np.count_nonzero(out))}}
    if name=='foundation': keep=v[:,1:-1,1:-1]==1
    elif name=='solid': keep=(yy<=base)&(v[:,1:-1,1:-1]!=1)
    elif name=='glass': keep=yy>base
    elif name in ('glass_1','glass_2','glass_3'): keep=yy==base+int(name[-1])
    else: raise ValueError('Unknown export layer.')
    out=np.zeros_like(v); out[:,1:-1,1:-1]=np.where(keep,v[:,1:-1,1:-1],0)
    return {**result,'voxels':out,'stats':{**result['stats'],'blocks':int(np.count_nonzero(out))}}


def inspection(result,name,cutaway=False):
    selected=layer(result,name);v=selected['voxels']
    if cutaway:
        v=v.copy();v[:,:v.shape[1]//2]=0
    samples={b['id']:b for b in colour.catalogue()}
    samples.update({b['id']:dict(top_rgb=b['rgb'],side_rgb=b['rgb']) for b in glass_catalogue()})
    top=np.array([samples.get(b['id'],{}).get('top_rgb',[0,0,0]) for b in result['palette']],np.float32)/255
    side=np.array([samples.get(b['id'],{}).get('side_rgb',[0,0,0]) for b in result['palette']],np.float32)/255
    h,l,w=v.shape
    if max(w,l)<=258:
        m=surface_mesh.layer_mesh(v,top,side_rgb=side)
    else:
        tops=h-np.argmax(v[::-1]!=0,axis=0);tops[~np.any(v!=0,axis=0)]=0
        zz,xx=np.indices(tops.shape);colors=top[v[np.maximum(0,tops-1),zz,xx]]*255
        step=max(2,int(np.ceil(max(w,l)/180)))
        m=surface_mesh.envelope(tops[::step,::step],colors[::step,::step],h)
        m['vertices'][:,:,[0,2]]*=step;m['centres']=m['vertices'].mean(axis=1)
        m.update(width=w,length=l,step=step,simplified=True)
    out={**result,'mesh':m,'gpu_vertices':mesh.triangle_data(m),'interaction_mesh':m,'preview_note':'Layer inspection · glass shown opaque; large geometry may be simplified'}
    out.pop('preview_texture',None)
    return out
