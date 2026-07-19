import json, os, sys, base64
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

class VLMImageAnalyzer:
    def __init__(self, provider='deepseek'):
        self.provider = provider

    def analyze_room_photo(self, image_path):
        if not os.path.exists(image_path):
            return {'error': 'File not found', 'room_type': 'unknown'}
        try:
            return self._vlm_analyze(image_path)
        except Exception as e:
            print(f'[VLM] VLM failed ({e}), using heuristic')
            return self._heuristic_analyze(image_path)

    def _vlm_analyze(self, image_path):
        from core.ai_client import get_client
        client = get_client()
        if not client.available:
            return self._heuristic_analyze(image_path)
        with open(image_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode()
        prompt = '''Analyze this interior room photo. Return ONLY valid JSON:
{
  "room_type": "living_room",
  "estimated_length_m": 5.0,
  "estimated_width_m": 4.0,
  "estimated_height_m": 2.8,
  "confidence": "medium",
  "visible_elements": [
    {"type": "door", "direction": "front", "estimated_width_m": 0.9, "estimated_height_m": 2.1}
  ],
  "floor_material": "tile",
  "wall_color": "white",
  "lighting_condition": "mixed",
  "notes": ""
}
Standard Chinese apartment: height 2.8m, door 0.9x2.1m.'''
        resp = client.vision(image_b64=img_b64, prompt=prompt, max_tokens=1000)
        import re
        m = re.search(r'\{.*\}', resp, re.DOTALL)
        if m:
            result = json.loads(m.group())
            result['source'] = 'vlm'
            return result
        return self._heuristic_analyze(image_path)

    def _heuristic_analyze(self, image_path):
        name = os.path.basename(image_path).lower()
        rtype = 'living_room'
        for kw, rt in [('bed','bedroom'),('kitchen','kitchen'),('bath','bathroom'),('dining','dining'),('study','study')]:
            if kw in name: rtype = rt; break
        return {
            'room_type': rtype, 'estimated_length_m': 4.5, 'estimated_width_m': 3.5,
            'estimated_height_m': 2.8, 'confidence': 'low',
            'visible_elements': [{'type':'door','direction':'front','estimated_width_m':0.9,'estimated_height_m':2.1}],
            'floor_material': 'tile', 'wall_color': 'white', 'lighting_condition': 'mixed',
            'notes': 'Heuristic estimate', 'source': 'heuristic',
        }

    def analysis_to_room_desc(self, analysis):
        rt = analysis.get('room_type','living_room').replace('_room','')
        if rt not in ['living','bedroom','kitchen','bathroom','dining','study','entry']: rt = 'living'
        l = int(analysis.get('estimated_length_m',4.0)*1000)
        w = int(analysis.get('estimated_width_m',3.5)*1000)
        h = int(analysis.get('estimated_height_m',2.8)*1000)
        doors = []; windows = []
        for el in analysis.get('visible_elements',[]):
            d = int(el.get('estimated_width_m',0.9)*1000)
            hh = int(el.get('estimated_height_m',2.1)*1000)
            direction = el.get('direction','front')
            wmap = {'front':1,'back':0,'left':2,'right':3}
            wi = wmap.get(direction,0)
            if el.get('type') == 'door':
                doors.append({'wall':wi,'offset':l/2-d/2,'width':d,'height':hh})
            elif el.get('type') == 'window':
                windows.append({'wall':wi,'offset':l/2-d/2,'width':d,'height':hh,'sill_height':900})
        nmap = {'living':'客厅','bedroom':'卧室','kitchen':'厨房','bathroom':'卫生间','dining':'餐厅','study':'书房','entry':'玄关'}
        return {'name':nmap.get(rt,'房间'),'type':rt,'length_mm':l,'width_mm':w,'height_mm':h,'doors':doors,'windows':windows}

    def photos_to_scene(self, photo_paths, output_path=None):
        from core.image2scene_enhanced import text_to_scene
        descs = []
        for i,path in enumerate(photo_paths):
            a = self.analyze_room_photo(path)
            d = self.analysis_to_room_desc(a)
            d['name'] = f'{d["name"]}_{i+1}'
            descs.append(d)
        scene = text_to_scene(descs, name='Photo Import')
        if output_path:
            json.dump(scene.to_dict(), open(output_path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
        return scene

print('vlm_analyzer v1 ready')
