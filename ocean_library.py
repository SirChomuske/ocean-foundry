"""Bundled Ocean normal maps; sampling is shared with Lava and imported maps."""
from pathlib import Path
import sys
import json
import normal_maps

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'ocean_normals'
BASELINES=tuple(tuple(item) for item in json.loads((ROOT/'catalogue.json').read_text()))


def baseline(name):
    if name not in dict(BASELINES):raise ValueError('Unknown ocean normal map.')
    return normal_maps.load(str(ROOT/(name+'.png')))
