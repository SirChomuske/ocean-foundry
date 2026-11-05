"""Portable named settings profiles, including local normal-map assets."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
from PIL import Image
import normal_maps


def map_paths(value,visitor):
    if isinstance(value,dict):
        return {k:visitor(v) if k=='normal_map_path' and v else map_paths(v,visitor) for k,v in value.items()}
    if isinstance(value,list):return [map_paths(v,visitor) for v in value]
    return value


def write(path,settings):
    assets={}
    def include(value):
        data=normal_maps.resolve_path(value).read_bytes()
        key=hashlib.sha256(data).hexdigest()+'.png'
        assets[key]=base64.b64encode(data).decode('ascii');return key
    payload=dict(format='Ocean Foundry profile',version=1,settings=map_paths(settings,include),assets=assets)
    path=Path(path);temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(payload,indent=2),encoding='utf-8');os.replace(temp,path)


def read(path,asset_folder):
    path=Path(path)
    if path.stat().st_size>100*1024*1024:raise ValueError('Profile exceeds 100 MiB.')
    payload=json.loads(path.read_text(encoding='utf-8'))
    if payload.get('format')!='Ocean Foundry profile':raise ValueError('Not an Ocean Foundry profile.')
    folder=Path(asset_folder);folder.mkdir(exist_ok=True,parents=True);restored={}
    for key,encoded in payload.get('assets',{}).items():
        data=base64.b64decode(encoded,validate=True)
        with Image.open(io.BytesIO(data)) as image:
            if image.mode not in ('RGB','RGBA') or image.width*image.height>16777216:raise ValueError('Invalid profile normal map.')
            image.verify()
        name=hashlib.sha256(data).hexdigest()+'.png';destination=folder/name
        if not destination.exists():destination.write_bytes(data)
        restored[key]=normal_maps.portable_path(destination)
    return map_paths(payload['settings'],lambda key:restored.get(key,key))
