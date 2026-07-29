from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from .types import AgentAdapter, ToolExecutor


@dataclass(slots=True)
class OpenAICompatibleAdapterConfig:
    model: str
    base_url: str = "https://api.openai.com"
    api_key: str | None = None
    endpoint: str = "/v1/chat/completions"
    max_turns: int = 8
    temperature: float | None = None
    timeout_seconds: float = 60.0
    system_prompt: str | None = None


def _normalize_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    if not schema or not isinstance(schema, dict):
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }

    if schema.get("type") != "object":
        return {
            "type": "object",
            "properties": {"input": schema},
            "additionalProperties": True,
        }

    return schema


def _build_tools_from_context(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not context:
        return []
    raw_tools = context.get("tools", [])
    if not isinstance(raw_tools, list):
        return []

    tools: list[dict[str, Any]] = []
    for item in raw_tools:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            continue
        schema = _normalize_schema(item.get("schema"))
        description = item.get("description")
        if not isinstance(description, str):
            description = f"Execute {name} and return structured JSON output."
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": schema,
                },
            }
        )
    return tools


def _tool_result_to_content(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True)
    except TypeError:
        return json.dumps({"value": str(value)}, ensure_ascii=True)


def _parse_tool_arguments(raw_args: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw_args is None:
        return {}
    if isinstance(raw_args, dict):
        return raw_args
    if not isinstance(raw_args, str):
        return {}

    text = raw_args.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def make_openai_tool_loop_adapter(config: OpenAICompatibleAdapterConfig) -> AgentAdapter:
    api_key = config.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OpenAI-compatible adapter requires api_key or OPENAI_API_KEY")

    base_url = config.base_url.rstrip("/")
    endpoint = config.endpoint if config.endpoint.startswith("/") else f"/{config.endpoint}"

    def run(prompt: str, tool_executor: ToolExecutor, context: dict[str, Any] | None = None) -> dict[str, Any]:
        tools = _build_tools_from_context(context)

        messages: list[dict[str, Any]] = []
        if config.system_prompt:
            messages.append({"role": "system", "content": config.system_prompt})

        if context and isinstance(context.get("constraints"), list) and context["constraints"]:
            constraints = "\n".join(f"- {item}" for item in context["constraints"])
            messages.append(
                {
                    "role": "system",
                    "content": f"Task constraints:\n{constraints}",
                }
            )

        messages.append({"role": "user", "content": prompt})

        request_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        usage: dict[str, Any] | None = None

        with httpx.Client(base_url=base_url, timeout=config.timeout_seconds) as client:
            for _ in range(config.max_turns):
                body: dict[str, Any] = {
                    "model": config.model,
                    "messages": messages,
                    "stream": False,
                }
                if tools:
                    body["tools"] = tools
                    body["tool_choice"] = "auto"
                if config.temperature is not None:
                    body["temperature"] = config.temperature

                response = client.post(endpoint, json=body, headers=request_headers)
                response.raise_for_status()
                payload = response.json()

                choices = payload.get("choices") or []
                if not choices:
                    raise RuntimeError("OpenAI-compatible response missing choices")

                message = choices[0].get("message") or {}
                usage_payload = payload.get("usage")
                if isinstance(usage_payload, dict):
                    usage = {
                        "prompt_tokens": int(usage_payload.get("prompt_tokens", 0)),
                        "completion_tokens": int(usage_payload.get("completion_tokens", 0)),
                    }

                tool_calls = message.get("tool_calls") or []
                if tool_calls:
                    assistant_message = {
                        "role": "assistant",
                        "content": message.get("content"),
                        "tool_calls": tool_calls,
                    }
                    messages.append(assistant_message)

                    for call in tool_calls:
                        if not isinstance(call, dict):
                            continue
                        function_payload = call.get("function") or {}
                        tool_name = function_payload.get("name")
                        if not isinstance(tool_name, str) or not tool_name:
                            continue
                        arguments = _parse_tool_arguments(function_payload.get("arguments"))
                        result = tool_executor(tool_name, arguments)
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.get("id", ""),
                                "name": tool_name,
                                "content": _tool_result_to_content(result),
                            }
                        )
                    continue

                content = message.get("content")
                if content is None:
                    content = ""
                if isinstance(content, list):
                    text_parts: list[str] = []
                    for part in content:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            text_parts.append(part["text"])
                    content = "\n".join(text_parts)

                return {
                    "output": str(content),
                    "usage": usage,
                }

        return {
            "output": "Reached max_turns without final assistant response.",
            "usage": usage,
        }

    return run
