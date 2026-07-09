"""
AI Client - 支持 DeepSeek / OpenAI / 本地模型
"""
import os, json, time

class AIClient:
    def __init__(self, provider="deepseek"):
        self.provider = provider
        self.api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = os.environ.get("AI_MODEL", "deepseek-chat")
        self.timeout = 60

    @property
    def available(self):
        return bool(self.api_key)

    def chat(self, prompt, temperature=0.3, max_tokens=2000):
        if not self.available:
            return self._mock_chat(prompt)
        import urllib.request
        url = f"{self.base_url}/v1/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": [{"role":"user","content":prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[AI] API error: {e}")
            return self._mock_chat(prompt)

    def vision(self, image_b64, prompt, max_tokens=1000):
        if not self.available:
            return self._mock_vision()
        import urllib.request
        url = f"{self.base_url}/v1/chat/completions"
        body = json.dumps({
            "model": self.model.replace("chat", "vision") if "chat" in self.model else "deepseek-vision",
            "messages": [{"role":"user","content":[
                {"type":"text","text":prompt},
                {"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{image_b64}"}}
            ]}],
            "max_tokens": max_tokens,
        }).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[AI Vision] Error: {e}")
            return self._mock_vision()

    def _mock_chat(self, prompt):
        """Mock response for offline testing"""
        if "furniture" in prompt.lower() or "place" in prompt.lower():
            return json.dumps([{"spec_id":"sofa-3seat","name":"Sofa","category":"sofa","position":[1500,0,800],"rotation":0,"width_mm":2200,"depth_mm":900,"height_mm":850}])
        if "room" in prompt.lower():
            return json.dumps({"room_type":"living_room","estimated_length_m":5.0,"estimated_width_m":4.0,"estimated_height_m":2.8,"confidence":"medium","visible_elements":[]})
        return "{}"

    def _mock_vision(self):
        return json.dumps({"room_type":"living_room","estimated_length_m":5.0,"estimated_width_m":4.0,"estimated_height_m":2.8,"confidence":"low","visible_elements":[{"type":"door","direction":"front","estimated_width_m":0.9,"estimated_height_m":2.1}],"floor_material":"tile","wall_color":"white"})


_client = None
def get_client(provider="deepseek"):
    global _client
    if _client is None:
        _client = AIClient(provider)
    return _client

print("ai_client v2 ready")
