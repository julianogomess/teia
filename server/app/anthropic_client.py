"""Chamada à API da Anthropic e estimativa de custo por evento."""

import os
import ssl
import time
from typing import List, Optional, Tuple

import httpx

from .config import settings
from .models import Organization

# Contexto SSL do sistema operacional (inclui CAs corporativas do Windows),
# em vez do bundle certifi do httpx — necessário em redes com inspeção TLS.
SSL_CONTEXT = ssl.create_default_context()

# US$ por milhão de tokens (entrada, saída) — validar contra
# platform.claude.com/docs/en/pricing antes de decisões de orçamento.
PRICING_USD_PER_MTOK = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),  # preço promocional até 31/08/2026
}
# fallback para modelos fora da tabela: assume o mais caro conhecido
_DEFAULT_PRICING = (2.0, 10.0)


class AnthropicError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def resolve_api_key(org: Organization) -> Optional[str]:
    """Chave do tenant (cobrança na conta do cliente) ou fallback global."""
    return os.environ.get(org.api_key_env) or os.environ.get("ANTHROPIC_API_KEY")


def estimate_cost_usd(model: str, usage: dict) -> float:
    """Custo estimado do evento. Cache: leitura ~10% e escrita ~125% do preço
    de entrada, conforme a documentação de prompt caching da Anthropic."""
    price_in, price_out = PRICING_USD_PER_MTOK.get(model, _DEFAULT_PRICING)
    input_tokens = usage.get("input_tokens", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    cache_write = usage.get("cache_creation_input_tokens", 0) or 0
    cost = (
        input_tokens * price_in
        + cache_write * price_in * 1.25
        + cache_read * price_in * 0.10
        + output_tokens * price_out
    ) / 1_000_000
    return round(cost, 6)


def send_message(
    api_key: str,
    system_blocks: List[dict],
    messages: List[dict],
    model: Optional[str] = None,
    tools: Optional[List[dict]] = None,
) -> Tuple[str, Optional[dict], dict, int]:
    """Envia a conversa ao modelo.

    Retorna (texto, tool_input, usage, latência_ms). `tool_input` é o input
    do primeiro bloco tool_use, quando `tools` for oferecido e o modelo
    chamar a ferramenta — canal de saída estruturada, sem loop de agente
    (nunca devolvemos tool_result).
    """
    model = model or settings.anthropic_model
    payload = {
        "model": model,
        "max_tokens": settings.max_reply_tokens,
        "system": system_blocks,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
    started = time.monotonic()
    try:
        response = httpx.post(
            settings.anthropic_api_url,
            json=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=settings.anthropic_timeout_seconds,
            verify=SSL_CONTEXT,
        )
    except httpx.HTTPError as exc:
        raise AnthropicError(502, f"Falha ao contatar a API Anthropic: {exc}")
    latency_ms = int((time.monotonic() - started) * 1000)

    if response.status_code != 200:
        raise AnthropicError(response.status_code, response.text[:500])

    data = response.json()
    reply = "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    )
    tool_input = next(
        (block.get("input") for block in data.get("content", [])
         if block.get("type") == "tool_use"),
        None,
    )
    return reply, tool_input, data.get("usage", {}), latency_ms
