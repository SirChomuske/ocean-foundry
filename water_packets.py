"""Static wave-train synthesis with overlapping compact envelopes and analytic slopes.
Inspired by wave-packet representations; not the Jeschke/Wojtan propagation solver."""
import numpy as np


def random_grid(ix,iz,seed,band,salt):
    h=ix.astype(np.uint32)*np.uint32(0x8da6b343)^iz.astype(np.uint32)*np.uint32(0xd8163841)^np.uint32(seed)^np.uint32(band*741103597)^np.uint32(salt)
    h^=h>>16;h*=np.uint32(0x7feb352d);h^=h>>15;h*=np.uint32(0x846ca68b);h^=h>>16
    return (h&np.uint32(0xffffff)).astype(np.float32)/16777216


def fields(x,z,scale,angle,disorder,seed,micro=.45,footprint=1):
    ca,sa=np.float32(np.cos(angle)),np.float32(np.sin(angle));u=x*ca+z*sa;v=-x*sa+z*ca
    elevation=np.zeros_like(x);gu=elevation.copy();gv=elevation.copy();curv=elevation.copy()
    for band,ratio,weight in ((0,1.,1.),(1,.42,.28),(2,.12,micro*.35)):
        if weight==0:continue
        length=scale*ratio;cell=length*2.4
        weight*=np.exp(-.08*(2*np.pi/length*footprint)**2)
        bx=np.floor(u/cell).astype(np.int32);bz=np.floor(v/cell).astype(np.int32)
        # Hash each packet once per batch, not once for every covered pixel.
        xmin,zmin=int(bx.min())-2,int(bz.min())-2
        iz,ix=np.mgrid[zmin:int(bz.max())+3,xmin:int(bx.max())+3].astype(np.int32)
        r1=random_grid(ix,iz,seed,band,13);r2=random_grid(ix,iz,seed,band,721)
        r3=random_grid(ix,iz,seed,band,8191);r4=random_grid(ix,iz,seed,band,65537)
        r5=random_grid(ix,iz,seed,band,104729);r6=random_grid(ix,iz,seed,band,131071)
        wl=length*(.75+.65*r5)
        # Donelan-Banner directional spreading (Horvath 2015), sampled from the
        # sech^2 distribution by inverse CDF. Short waves spread more than the peak.
        rel=np.sqrt(length/np.maximum(wl,1e-6))
        beta=np.where(rel<.95,2.61*rel**1.3,np.where(rel<1.6,2.28*rel**-1.3,
            10**(.8393*np.exp(-.567*np.log(np.maximum(rel,1.6)**2))-.4)))
        beta*=.65+.14*np.clip(18-12*float(np.clip(disorder,0,1)),4,24)
        sample=(2*r6-1)*np.tanh(beta*np.pi)
        theta=np.arctanh(np.clip(sample,-.999999,.999999))/beta
        tables=((ix+.15+.7*r1)*cell,(iz+.15+.7*r2)*cell,np.cos(theta),np.sin(theta),
                wl,(r1-.5)*(.15+.25*disorder),r4*(2*np.pi),weight*1.36*(.7+.6*r3))
        for j in range(-2,3):
            for i in range(-2,3):
                at=(bz+j-zmin,bx+i-xmin)
                cx,cz,ct,st,wl,curve,phase0,amp0=[t[at] for t in tables]
                du=u-cx;dv=v-cz;p=du*ct+dv*st;q=-du*st+dv*ct
                ru=np.full_like(wl,length*2.4);rv=np.full_like(wl,length*3.36)
                inside=(np.abs(p)<ru)&(np.abs(q)<rv)
                if not inside.any():continue
                # No trigonometry or derivative evaluation outside compact support.
                p,q,ru,rv,wl,curve,phase0,amp0,ct,st=[t[inside] for t in (p,q,ru,rv,wl,curve,phase0,amp0,ct,st)]
                # Several crests per group; C1 separable windows avoid round radial caps.
                up=np.pi*p/ru;vq=np.pi*q/rv
                eu=.5*(1+np.cos(up));ev=.5*(1+np.cos(vq))
                envelope=eu*ev;ep=-.5*np.pi/ru*np.sin(up)*ev;eq=-.5*np.pi/rv*np.sin(vq)*eu
                k=2*np.pi/wl;phase=k*p+curve*(q/wl)**2+phase0
                sn=np.sin(phase);cs=np.cos(phase);amp=amp0/k
                hp=amp*(ep*cs-envelope*sn*k);hq=amp*(eq*cs-envelope*sn*2*curve*q/(wl*wl))
                elevation[inside]+=amp*envelope*cs;gu[inside]+=hp*ct-hq*st;gv[inside]+=hp*st+hq*ct
                curv[inside]+=amp*envelope*k*k*cs
    return elevation,gu*ca-gv*sa,gu*sa+gv*ca,curv


GLSL='''
float randGrid(ivec2 cell,int band,uint salt){
uint h=uint(cell.x)*0x8da6b343u^uint(cell.y)*0xd8163841u^uint(patternSeed)^uint(band)*741103597u^salt;
h^=h>>16;h*=0x7feb352du;h^=h>>15;h*=0x846ca68bu;h^=h>>16;
return float(h&0xffffffu)/16777216.;}
vec4 packets(vec2 pos){
float ca=cos(surfaceAngle),sa=sin(surfaceAngle);vec2 uv=vec2(pos.x*ca+pos.y*sa,-pos.x*sa+pos.y*ca);
float height=0.,gu=0.,gv=0.,curvature=0.;
for(int band=0;band<3;band++){
float len=climate.z*(band==0?1.:band==1?.42:.12),weight=band==0?1.:band==1?.28:microDetail*.35,cellSize=len*2.4;
float fp=max(dims.x/dims.z,dims.y/dims.w);weight*=exp(-.08*pow(6.28318530718/len*fp,2.));
ivec2 cell=ivec2(floor(uv/cellSize));
for(int j=-2;j<=2;j++)for(int i=-2;i<=2;i++){
ivec2 id=cell+ivec2(i,j);float r1=randGrid(id,band,13u),r2=randGrid(id,band,721u),r3=randGrid(id,band,8191u),r4=randGrid(id,band,65537u);
vec2 delta=uv-(vec2(id)+.15+.7*vec2(r1,r2))*cellSize;
float r5=randGrid(id,band,104729u),r6=randGrid(id,band,131071u);
float wl=len*(.75+.65*r5);
float rel=sqrt(len/max(wl,1e-6));
float beta=rel<.95?2.61*pow(rel,1.3):(rel<1.6?2.28*pow(rel,-1.3):pow(10.,.8393*exp(-.567*pow(log(max(rel,1.6))*2.,2.))-.4));
beta*=.65+.14*clamp(18.-12.*climate.w,4.,24.);
float uu=(2.*r6-1.)*tanh(beta*3.14159265359);uu=clamp(uu,-.999999,.999999);
float angle=.5*log((1.+uu)/(1.-uu))/beta,ct=cos(angle),st=sin(angle);
float p=delta.x*ct+delta.y*st,q=-delta.x*st+delta.y*ct;
float ru=len*2.4,rv=len*3.36;
if(abs(p)>=ru||abs(q)>=rv)continue;
float up=3.14159265359*p/ru,vq=3.14159265359*q/rv;
float eu=.5*(1.+cos(up)),ev=.5*(1.+cos(vq));
float envelope=eu*ev,ep=-.5*3.14159265359/ru*sin(up)*ev,eq=-.5*3.14159265359/rv*sin(vq)*eu;
float k=6.28318530718/wl,curve=(r1-.5)*(.15+.25*climate.w),phase=k*p+curve*(q/wl)*(q/wl)+r4*6.28318530718;
float sn=sin(phase),cs=cos(phase),amp=weight*1.36*(.7+.6*r3)/k;
float hp=amp*(ep*cs-envelope*sn*k),hq=amp*(eq*cs-envelope*sn*2.*curve*q/(wl*wl));
height+=amp*envelope*cs;gu+=hp*ct-hq*st;gv+=hp*st+hq*ct;curvature+=amp*envelope*k*k*cs;
}}
return vec4(height,gu*ca-gv*sa,gu*sa+gv*ca,curvature);
}
'''
