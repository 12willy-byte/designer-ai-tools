"""
统一 AI 客户端 - 支持多模型提供商
VLM: SenseNova-SI / GPT-4o (视觉空间推理)
LLM: DeepSeek (文案生成)
"""
import os, sys, time, json, base64, logging
from typing import Optional
from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from modules.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

logger = logging.getLogger(__name__)


class AIClient:
    """LLM - DeepSeek"""
    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.base_url = base_url or DEEPSEEK_BASE_URL
        self.model = model or DEEPSEEK_MODEL
        self._client = None
        self.total_tokens = 0
        self.call_count = 0

    @property
    def client(self):
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def chat(self, system_prompt, user_prompt, temperature=0.7, max_tokens=2000, max_retries=3):
        if not self.api_key:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY")
        for attempt in range(max_retries):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature, max_tokens=max_tokens,
                )
                self.call_count += 1
                if resp.usage:
                    self.total_tokens += resp.usage.total_tokens
                return resp.choices[0].message.content
            except Exception as e:
                logger.warning("AI retry %d/%d: %s", attempt+1, max_retries, e)
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

    def chat_json(self, system_prompt, user_prompt, temperature=0.3, max_tokens=2000):
        import re
        raw = self.chat(system_prompt, user_prompt, temperature, max_tokens)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if m:
                return json.loads(m.group(1))
            m = re.search(r"(\{.*\})", raw, re.DOTALL)
            if m:
                return json.loads(m.group(1))
            raise ValueError("无法解析 JSON")

    @property
    def stats(self):
        return {"calls": self.call_count, "tokens": self.total_tokens}
