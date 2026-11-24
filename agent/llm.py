"""Minimal Mistral chat client using the REST API directly.

Calling the HTTP endpoint (instead of an SDK) keeps the agent loop easy to read
and avoids breaking when the SDK changes versions.
"""
import os
import time

import requests

API_URL = "https://api.mistral.ai/v1/chat/completions"
DEFAULT_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
MAX_RETRIES = 6  # waits of 1, 2, 4, 8, 16, 30 seconds


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

        # Free-tier keys are rate limited, and new keys can take a few minutes to activate.
        # Wait and retry, honouring the server's Retry-After header when it sends one.
        for attempt in range(MAX_RETRIES + 1):
            r = requests.post(API_URL, json=body, timeout=60,
                              headers={"Authorization": f"Bearer {self.api_key}"})
            if r.status_code in (429, 500, 502, 503) and attempt < MAX_RETRIES:
                try:
                    wait = float(r.headers.get("Retry-After"))
                except (TypeError, ValueError):
                    wait = min(2 ** attempt, 30)
                print(f"Mistral returned {r.status_code}; retrying in {wait:.0f}s "
                      f"({attempt + 1}/{MAX_RETRIES})...")
                time.sleep(wait)
                continue
            if not r.ok:
                raise RuntimeError(
                    f"Mistral API error {r.status_code}: {r.text[:300]}\n"
                    "If this is 401, check the key. If it is 429, the key may still be activating "
                    "(wait a few minutes) or the free-tier limit was hit (wait a minute and retry)."
                )
            return r.json()["choices"][0]["message"]
