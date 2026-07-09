# -*- coding: utf-8 -*-
"""scene_utils - Shared helpers for Scene3D access across all modules"""
import math

def normalize(obj):
    """Convert any Scene3D object to a dict with all relevant fields including properties.
    Handles: Room, Wall, Opening, Furniture, Beam, Column, or plain dicts."""
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, '__dict__'):
        d = {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        # Extract common properties
        for prop in ['length_mm', 'width_mm', 'height_mm', 'area_m2', 'perimeter_mm', 'direction', 'normal']:
            if hasattr(obj, prop):
                try:
                    val = getattr(obj, prop)
                    if prop not in d or d.get(prop) is None or d.get(prop) == 0:
                        d[prop] = val
                except:
                    pass
        return d
    return {}

def coord(p, axis=0):
    """Get coordinate from list/tuple/dict/Point3D"""
    if isinstance(p, (list, tuple)):
        return p[axis] if len(p) > axis else 0
    if isinstance(p, dict):
        return p.get(('x', 'y', 'z')[axis], 0)
    if hasattr(p, ('x', 'y', 'z')[axis]):
        return getattr(p, ('x', 'y', 'z')[axis])
    return 0

def wall_length(w):
    """Get wall length in mm from any format"""
    d = normalize(w)
    if d.get('length_mm'):
        return d['length_mm']
    s = d.get('start', [0, 0, 0])
    e = d.get('end', [0, 0, 0])
    return math.hypot(coord(e, 0) - coord(s, 0), coord(e, 2) - coord(s, 2))

def wall_height(w):
    """Get wall height in mm"""
    d = normalize(w)
    return d.get('height', d.get('height_mm', 2800))
def get_rooms(scene):
    """Get rooms as list from any Scene3D format (handles dict->list conversion)"""
    rooms = getattr(scene, 'rooms', None)
    if rooms is None:
        return []
    if isinstance(rooms, dict):
        return list(rooms.values())
    if isinstance(rooms, list):
        return rooms
    return []

def get_walls(scene):
    """Get walls as list"""
    walls = getattr(scene, 'walls', None)
    if walls is None:
        return []
    if isinstance(walls, list):
        return walls
    return []

def get_doors(scene):
    doors = getattr(scene, 'doors', None)
    if doors is None: return []
    if isinstance(doors, list): return doors
    return []

def get_windows(scene):
    windows = getattr(scene, 'windows', None)
    if windows is None: return []
    if isinstance(windows, list): return windows
    return []