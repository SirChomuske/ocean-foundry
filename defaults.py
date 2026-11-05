"""Canonical application defaults, read from the shipped ``default_settings.json``.

That JSON file is the single source of truth for fresh-install values. The
appearance, colour and ocean modules read their sections from here instead of
keeping private copies that can drift from what a new installation receives.
When frozen, a bundled copy is preferred, then the file beside the executable.
"""
import json
import sys
from functools import lru_cache
from pathlib import Path

NAME = 'default_settings.json'


def _candidates():
    executable = Path(sys.executable).parent
    if getattr(sys, 'frozen', False):
        yield Path(getattr(sys, '_MEIPASS', executable)) / NAME
        yield executable / NAME
    yield Path(__file__).resolve().parent / NAME


@lru_cache(maxsize=1)
def load():
    """Parsed contents of the shipped defaults file."""
    for path in _candidates():
        try:
            with path.open(encoding='utf-8') as stream:
                data = json.load(stream)
            break
        except FileNotFoundError:
            continue
    else:
        raise RuntimeError(f'{NAME} is missing; it supplies the application defaults.')
    if not isinstance(data, dict):
        raise ValueError(f'{NAME} must contain a JSON object.')
    return data


def section(name):
    """A fresh copy of one section so callers may keep or extend it."""
    data = load()
    try:
        values = data[name]
    except KeyError:
        raise RuntimeError(f'{NAME} has no "{name}" section.') from None
    if not isinstance(values, dict):
        raise ValueError(f'{NAME} section "{name}" must be a JSON object.')
    return dict(values)
