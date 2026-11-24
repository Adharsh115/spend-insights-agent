"""Minimal Mistral chat client using the REST API directly.

Calling the HTTP endpoint (instead of an SDK) keeps the agent loop easy to read
and avoids breaking when the SDK changes versions.
"""
import os
import time

import requests

API_URL = "https://api.mistral.ai/v1/chat/completions"
DEFAULT_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")


class MistralClient:
    def __init__(self, api_key=None, model=DEFAULT_MODEL):
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY")
        if not self.api_key:
            raise ValueError("Set MISTRAL_API_KEY (or pass api_key) to use the agent.")
        self.model = model

    def chat(self, messages, tools=None, json_mode=False, temperature=0.1):
        """Send one chat request and return the assistant message as a dict."""
        body = {"model": self.model, "messages": messages, "temperature": temperature}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        for attempt in range(4):  # simple retry for rate limits / brief outages
            r = requests.post(API_URL, json=body, timeout=60,
                              headers={"Authorization": f"Bearer {self.api_key}"})
            if r.status_code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]
