"""Azure OpenAI client singleton and low-level LLM utilities.

All LLM calls in the application route through call_llm() so that
client management, logging, and error handling are centralised.
"""

import json
import re

from app.config import (
    AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY,
    AZURE_OPENAI_API_VERSION, FAST_MODEL,
)

_azure_client = None


def _get_client():
    """Return a singleton AzureOpenAI client."""
    global _azure_client
    if _azure_client is None:
        import httpx
        import ssl
        from openai import AzureOpenAI
        ssl_ctx = ssl.create_default_context()
        http_client = httpx.Client(verify=ssl_ctx)
        _azure_client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
            http_client=http_client,
        )
    return _azure_client


def call_llm(system: str, user: str, model: str = None,
             max_tokens: int = 4096) -> str:
    """Call Azure OpenAI and return the response text.

    This is the single point of contact for all LLM interactions.
    """
    model = model or FAST_MODEL
    client = _get_client()
    print(f"[LLM] Calling {model} ({len(user)} chars input)...")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_completion_tokens=max_tokens,
    )
    print(f"[LLM] {model} responded OK")
    return resp.choices[0].message.content.strip()


def parse_json(raw: str) -> dict:
    """Parse JSON from LLM output, stripping markdown code fences."""
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
