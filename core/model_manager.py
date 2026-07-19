import json, os, sys, hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

MODEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'resources', 'models')

MODEL_SOURCES = {
    'sofa-3seat': {'url': '', 'source': 'builtin'},
    'sofa-2seat': {'url': '', 'source': 'builtin'},
    'sofa-lshape': {'url': '', 'source': 'builtin'},
    'bed-double-180': {'url': '', 'source': 'builtin'},
    'bed-double-150': {'url': '', 'source': 'builtin'},
    'table-dining-4': {'url': '', 'source': 'builtin'},
    'table-dining-6': {'url': '', 'source': 'builtin'},
    'table-coffee': {'url': '', 'source': 'builtin'},
    'chair-dining': {'url': '', 'source': 'builtin'},
    'cabinet-tv': {'url': '', 'source': 'builtin'},
    'cabinet-wardrobe-3door': {'url': '', 'source': 'builtin'},
    'desk-standard': {'url': '', 'source': 'builtin'},
}

class ModelManager:
    def __init__(self):
        self.model_dir = MODEL_DIR
        os.makedirs(self.model_dir, exist_ok=True)
        self._load_registry()

    def _load_registry(self):
        reg_path = os.path.join(self.model_dir, 'registry.json')
        if os.path.exists(reg_path):
            with open(reg_path, 'r', encoding='utf-8') as f:
                self.registry = json.load(f)
        else:
            self.registry = {}

    def _save_registry(self):
        with open(os.path.join(self.model_dir, 'registry.json'), 'w', encoding='utf-8') as f:
            json.dump(self.registry, f, ensure_ascii=False, indent=2)

    def resolve(self, spec_id):
        if spec_id in self.registry:
            path = self.registry[spec_id].get('local_path', '')
            if path and os.path.exists(path):
                return path
        source = MODEL_SOURCES.get(spec_id, {})
        if source.get('source') == 'builtin':
            return 'builtin'
        url = source.get('url', '')
        if url:
            try:
                return self._download(url, spec_id)
            except Exception as e:
                print(f'[Model] Download failed for {spec_id}: {e}')
        return 'builtin'

    def _download(self, url, spec_id):
        ext = url.rsplit('.', 1)[-1].split('?')[0] or 'glb'
        local_path = os.path.join(self.model_dir, f'{spec_id}.{ext}')
        if os.path.exists(local_path):
            self.registry[spec_id] = {'local_path': local_path, 'source_url': url}
            self._save_registry()
            return local_path
        import urllib.request
        print(f'[Model] Downloading {url} ...')
        urllib.request.urlretrieve(url, local_path)
        self.registry[spec_id] = {'local_path': local_path, 'source_url': url}
        self._save_registry()
        return local_path

    def list_models(self):
        models = []
        for spec_id in MODEL_SOURCES:
            path = self.resolve(spec_id)
            models.append({'spec_id': spec_id, 'path': path, 'available': path != 'builtin'})
        return models

    def generate_model_asset(self, spec_id):
        from core.furniture_library import get_library
        flib = get_library()
        spec = flib.get(spec_id)
        if not spec:
            return None
        w = spec.width_mm / 1000.0
        d = spec.depth_mm / 1000.0
        h = spec.height_mm / 1000.0
        return {
            'type': 'box',
            'dimensions': {'width': w, 'depth': d, 'height': h},
            'name': spec.name,
            'category': spec.category,
        }

print('model_manager v1 ready')
