"""
Unified AI client for MVP concept generation.

Supports multiple OpenAI-compatible providers (deepseek / openai / moonshot)
selected via the AI_PROVIDER environment variable. Production mode requires an
API key (AI_API_KEY or the provider-specific variable). Demo mode is explicit
via AI_DEMO_MODE=1, so mock output cannot be mistaken for a real model result.

Configuration priority (highest first):
  AI_API_KEY / AI_BASE_URL / AI_MODEL  (generic)
  <PROVIDER>_API_KEY / <PROVIDER>_BASE_URL / <PROVIDER>_MODEL  (e.g. DEEPSEEK_API_KEY)
  built-in provider presets
"""
import json
import os
import re
import urllib.request

# Built-in provider presets: base_url, default model, provider-specific env prefix.
PROVIDER_PRESETS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "key_env": "OPENAI_API_KEY",
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "key_env": "MOONSHOT_API_KEY",
    },
}

DEFAULT_PROVIDER = "deepseek"


class AIClient:
    def __init__(self, provider=None, demo_mode=None):
        provider = (provider or os.environ.get("AI_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
        if provider not in PROVIDER_PRESETS:
            raise ValueError(
                f"Unknown AI provider: {provider!r}. "
                f"Supported: {', '.join(sorted(PROVIDER_PRESETS))}"
            )
        preset = PROVIDER_PRESETS[provider]
        prefix = provider.upper()
        self.provider = provider
        self.api_key = (
            os.environ.get("AI_API_KEY")
            or os.environ.get(preset["key_env"])
            or os.environ.get(f"{prefix}_API_KEY", "")
        )
        self.base_url = (
            os.environ.get("AI_BASE_URL")
            or os.environ.get(f"{prefix}_BASE_URL")
            or preset["base_url"]
        )
        self.model = (
            os.environ.get("AI_MODEL")
            or os.environ.get(f"{prefix}_MODEL")
            or preset["model"]
        )
        self.timeout = int(os.environ.get("AI_TIMEOUT", "60"))
        if demo_mode is None:
            demo_mode = os.environ.get("AI_DEMO_MODE", "").lower() in {"1", "true", "yes"}
        self.demo_mode = bool(demo_mode)

    @property
    def available(self):
        return bool(self.api_key)

    def _not_configured_error(self):
        key_env = PROVIDER_PRESETS[self.provider]["key_env"]
        return RuntimeError(
            f"AI API key for provider '{self.provider}' is not configured. "
            f"Set AI_API_KEY or {key_env}, or set AI_DEMO_MODE=1 for demo output."
        )

    def chat(self, system_prompt, user_prompt=None, temperature=0.3, max_tokens=2000):
        if user_prompt is None:
            messages = [{"role": "user", "content": system_prompt}]
            prompt_for_mock = system_prompt
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            prompt_for_mock = f"{system_prompt}\n\n{user_prompt}"

        if self.demo_mode:
            return self._mock_chat(prompt_for_mock)
        if not self.available:
            raise self._not_configured_error()

        url = self.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        })
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]

    def chat_json(self, system_prompt, user_prompt=None, temperature=0.3, max_tokens=2000):
        raw = self.chat(system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens)
        return _parse_json_object(raw)

    def vision(self, image_b64, prompt, max_tokens=1000):
        if self.demo_mode:
            return json.dumps({
                "demo": True,
                "provider": self.provider,
                "room_type": "living_room",
                "estimated_length_m": 5.0,
                "estimated_width_m": 4.0,
                "estimated_height_m": 2.8,
                "confidence": "low",
                "visible_elements": [],
            }, ensure_ascii=False)
        if not self.available:
            raise self._not_configured_error()
        return self.chat(prompt, max_tokens=max_tokens)

    def _mock_chat(self, prompt):
        lower = prompt.lower()
        if "色彩" in prompt or "color" in lower:
            return json.dumps({
                "demo": True,
                "provider": self.provider,
                "scheme_name": "演示色彩方案",
                "description": "暖白、木色与低饱和点缀色组成的稳妥初稿",
                "base_color": {"name": "暖白", "hex": "#F5F0E8", "rgb": [245, 240, 232], "ratio": 60, "usage": "墙面、顶面"},
                "secondary_color": {"name": "浅橡木", "hex": "#D8B98C", "rgb": [216, 185, 140], "ratio": 30, "usage": "地面、柜体"},
                "accent_color": {"name": "雾蓝灰", "hex": "#7F9AA8", "rgb": [127, 154, 168], "ratio": 10, "usage": "软装、单椅、装饰画"},
                "wood_tone": "浅橡木或白橡木",
                "room_suggestions": [{"room": "客厅", "base": "#F5F0E8", "accent": "#7F9AA8", "note": "保持明亮通透"}],
            }, ensure_ascii=False)
        if "材质" in prompt or "material" in lower:
            return json.dumps({
                "demo": True,
                "provider": self.provider,
                "design_concept": "以耐用、易维护的基础材质建立安静背景，再用木色提升温度。",
                "materials": [{
                    "room": "客厅",
                    "floor": {"type": "橡木地板", "color": "浅原木色", "finish": "哑光", "code": "demo"},
                    "wall": {"type": "乳胶漆", "color": "暖白色", "finish": "哑光", "code": "demo"},
                    "feature_wall": {"type": "木饰面", "color": "浅橡木", "finish": "开放漆", "code": "demo"},
                    "ceiling": {"type": "乳胶漆", "color": "白色", "finish": "哑光", "code": "demo"},
                    "notes": "演示数据，需设计师复核品牌和预算。",
                }],
                "global_recommendations": {
                    "door_material": {"type": "平板门", "color": "暖白", "finish": "烤漆"},
                    "door_hardware": "黑色哑光",
                    "baseboard": "同门套或墙面同色",
                },
            }, ensure_ascii=False)
        if "布局" in prompt or "layout" in lower:
            return json.dumps({
                "demo": True,
                "provider": self.provider,
                "layout_name": "演示布局方案",
                "description": "保留主要动线，以客餐厅连续界面提升空间感。",
                "rooms": [{
                    "name": "客厅",
                    "analysis": "作为家庭公共活动核心，需要兼顾会客、观影和收纳。",
                    "layout_suggestions": ["沙发靠长墙布置", "电视墙整合收纳", "餐客厅之间保留连续通道"],
                    "furniture_suggestions": [{"item": "三人沙发", "suggested_size": "2200x900", "material": "布艺"}],
                    "notes": "演示数据，需结合实际结构复核。",
                }],
                "circulation_analysis": "主通道保持连续，避免大件家具压缩入口。",
                "design_highlights": ["通透动线", "集成收纳"],
            }, ensure_ascii=False)
        if "room" in lower and ("furniture" in lower or "place" in lower):
            return json.dumps([{
                "demo": True,
                "provider": self.provider,
                "spec_id": "sofa-3seat",
                "name": "Sofa",
                "category": "sofa",
                "position": [1500, 0, 800],
                "rotation": 0,
                "width_mm": 2200,
                "depth_mm": 900,
                "height_mm": 850,
            }], ensure_ascii=False)
        return (
            f"【演示模式·provider={self.provider}】这是自动生成的设计定位初稿：以客户生活方式为核心，"
            "优先建立清晰动线、充足收纳与稳定的材料基调。真实项目中应由设计师结合现场条件、预算和客户偏好继续深化。"
        )


def _parse_json_object(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    match = re.search(r"(\{.*\})", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Tolerance for real-LLM output: extract the outermost balanced {...} block,
    # which survives trailing commentary and non-greedy brace mismatches.
    start = raw.find("{")
    if start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(raw)):
            ch = raw[i]
            if escape:
                escape = False
                continue
            if ch == "\\" and in_str:
                escape = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start:i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError("AI response did not contain a JSON object")


_client = None


def get_client(provider=None, demo_mode=None):
    global _client
    if _client is None:
        _client = AIClient(provider=provider, demo_mode=demo_mode)
    return _client


def reset_client():
    global _client
    _client = None
