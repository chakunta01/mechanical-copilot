"""LLM gateway: chat completions against any OpenAI-compatible endpoint.

Features:
- JSON-mode helper with schema validation + bounded self-repair retry
- Vision (image) messages
- Deterministic FakeLLM for offline dev and tests
- Never raises raw SDK errors: maps to UpstreamError
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.errors import UpstreamError
from app.core.logging import get_logger

logger = get_logger("llm")

T = TypeVar("T", bound=BaseModel)


class LLMResponse(BaseModel):
    content: str
    model: str
    finish_reason: str | None = None
    # Values may be ints (OpenAI) or nested dicts like prompt_tokens_details
    # (OpenAI detailed usage, mirrored by Ollama/vLLM) — keep permissive.
    usage: dict[str, Any] = {}


class BaseLLM(ABC):
    name: str = "base"

    @abstractmethod
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse: ...

    # ---------------- JSON mode with self-repair ---------------- #
    def complete_json(
        self,
        messages: list[dict[str, Any]],
        schema: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_repairs: int = 1,
    ) -> tuple[T, LLMResponse]:
        """Ask for JSON, validate against `schema`, and retry once with the validator's
        complaints fed back to the model. Returns (validated_model, raw_response)."""
        convo = list(messages)
        # Small models need the exact shape up front — append the JSON schema to
        # the final user message so attempt #1 already targets the right keys.
        # Multimodal messages carry a list content; append a text part instead
        # of string-interpolating (which would destroy the image reference).
        try:
            schema_hint = (
                "Output JSON with EXACTLY this structure — fill ALL required top-level keys, "
                "use the exact key names shown, no wrapper objects, no prose:\n"
                + json.dumps(schema.model_json_schema())[:3000]
            )
            if convo and convo[-1]["role"] == "user":
                content = convo[-1]["content"]
                if isinstance(content, list):
                    convo[-1] = {**convo[-1], "content": [*content, {"type": "text", "text": schema_hint}]}
                else:
                    convo[-1] = {**convo[-1], "content": f"{content}\n\n{schema_hint}"}
        except Exception:  # schema hint is best-effort; log and never block generation
            logger.debug("Could not attach schema hint to final user message", exc_info=True)
        last_err: str = ""

        for _attempt in range(1 + max_repairs):
            resp = self.complete(
                convo,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
                },
            )
            parsed = _extract_json(resp.content)
            if parsed is not None:
                try:
                    return schema.model_validate(parsed), resp
                except ValidationError as exc:
                    last_err = exc.errors(include_url=False).__str__()[:1500]
            else:
                last_err = "Response was not valid JSON"
            convo = list(messages) + [
                {"role": "assistant", "content": resp.content},
                {
                    "role": "user",
                    "content": (
                        "Your previous response failed schema validation. "
                        f"Validation errors: {last_err}. "
                        "Return ONLY corrected JSON matching EXACTLY this schema (top-level keys, no wrapper objects, no prose, no code fences): "
                        + json.dumps(schema.model_json_schema())[:2500]
                    ),
                },
            ]
        raise UpstreamError(
            f"LLM failed to produce schema-valid JSON after retries: {last_err}",
            details={"model": self.name},
        )


def _extract_json(text: str) -> Any | None:
    """Extract a JSON object from model output (handles code fences and prose wrappers).

    Also unwraps single-key wrapper objects like {"process_plan": {...}} or
    {"response": {...}} — small models love adding a narrative top-level key.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    parsed: Any | None = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        pass
    if parsed is None:
        # Fall back to first {...} or [...] block.
        for opener, closer in (("{", "}"), ("[", "]")):
            start = text.find(opener)
            end = text.rfind(closer)
            if start != -1 and end > start:
                try:
                    parsed = json.loads(text[start : end + 1])
                    break
                except json.JSONDecodeError:
                    continue
    # Unwrap narrative wrapper keys (max 2 levels to stay conservative).
    for _ in range(2):
        if (
            isinstance(parsed, dict)
            and len(parsed) == 1
            and isinstance(next(iter(parsed.values())), dict)
        ):
            parsed = next(iter(parsed.values()))
        else:
            break
    # Models sometimes emit a bare array (e.g. a defects list) instead of the
    # object — take the first object inside rather than failing outright.
    if isinstance(parsed, list):
        parsed = next((item for item in parsed if isinstance(item, dict) and item), None)
    return parsed


class OpenAICompatibleLLM(BaseLLM):
    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    def _post(self, payload: dict[str, Any]) -> LLMResponse:
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(
                f"LLM HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(f"LLM request failed: {exc}") from exc

        data = resp.json()
        choice = data["choices"][0]
        return LLMResponse(
            content=choice["message"].get("content") or "",
            model=data.get("model", self.model),
            usage=data.get("usage", {}) or {},
            finish_reason=choice.get("finish_reason"),
        )

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": settings.llm_temperature if temperature is None else temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if response_format:
            payload["response_format"] = response_format
        try:
            return self._post(payload)
        except UpstreamError as exc:
            # Structured-output support varies across OpenAI-compatible endpoints.
            if response_format and any(code in str(exc) for code in ("HTTP 400", "HTTP 404", "HTTP 422", "HTTP 500")):
                logger.warning("structured output rejected by endpoint, retrying without response_format: %s", str(exc)[:120])
                payload.pop("response_format", None)
                return self._post(payload)
            raise


class OpenAIResponsesLLM(BaseLLM):
    """OpenAI Responses API client for current first-party GPT models."""

    name = "openai"

    def __init__(self, api_key: str, model: str, timeout_s: int = 120) -> None:
        self.base_url = "https://api.openai.com/v1"
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    @staticmethod
    def _input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, list):
                parts: list[dict[str, Any]] = []
                for part in content:
                    if part.get("type") == "text":
                        parts.append({"type": "input_text", "text": part.get("text", "")})
                    elif part.get("type") == "image_url":
                        image = part.get("image_url", {})
                        image_url = image.get("url") if isinstance(image, dict) else image
                        if image_url:
                            parts.append({"type": "input_image", "image_url": image_url})
                content = parts
            converted.append({"role": message.get("role", "user"), "content": content})
        return converted

    @staticmethod
    def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
        """Normalize Pydantic JSON Schema to the strict subset used by Responses."""
        normalized = dict(schema)
        normalized.pop("default", None)
        normalized.pop("examples", None)
        properties = normalized.get("properties")
        if normalized.get("type") == "object" and isinstance(properties, dict):
            normalized["additionalProperties"] = False
            normalized["required"] = list(properties)
        for key, value in tuple(normalized.items()):
            if isinstance(value, dict):
                normalized[key] = OpenAIResponsesLLM._strict_schema(value)
            elif isinstance(value, list):
                normalized[key] = [
                    OpenAIResponsesLLM._strict_schema(item) if isinstance(item, dict) else item
                    for item in value
                ]
        return normalized

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        del temperature  # GPT-6 reasoning models control sampling through reasoning effort.
        payload: dict[str, Any] = {
            "model": self.model,
            "input": self._input(messages),
            "max_output_tokens": max_tokens or 1024,
            "reasoning": {"effort": "low"},
            "store": False,
        }
        if response_format and response_format.get("type") == "json_schema":
            format_spec = response_format.get("json_schema", {})
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": format_spec.get("name", "response"),
                    "strict": True,
                    "schema": self._strict_schema(format_spec.get("schema", {})),
                }
            }
        try:
            resp = httpx.post(
                f"{self.base_url}/responses",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(f"OpenAI API HTTP {exc.response.status_code}: {exc.response.text[:300]}") from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(f"OpenAI API request failed: {exc}") from exc

        data = resp.json()
        output_text = data.get("output_text")
        if not output_text:
            chunks = []
            for item in data.get("output", []):
                if item.get("type") == "message":
                    chunks.extend(
                        content.get("text", "")
                        for content in item.get("content", [])
                        if content.get("type") == "output_text"
                    )
            output_text = "".join(chunks)
        if not output_text:
            raise UpstreamError("OpenAI API returned no text output")
        return LLMResponse(
            content=output_text,
            model=data.get("model", self.model),
            usage=data.get("usage", {}) or {},
            finish_reason=(
                "length"
                if data.get("status") == "incomplete"
                and (data.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
                else data.get("status")
            ),
        )

class FakeLLM(BaseLLM):
    """Deterministic offline LLM. Produces plausible outputs so the entire system
    (planner, inspection, Q&A) runs with zero external dependencies."""

    name = "fake"

    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResponse:
        del response_format  # structured output is a no-op for the fake model
        prompt = json.dumps(messages, default=str)
        content = _fake_response_for(prompt)
        return LLMResponse(content=content, model="fake-1", usage={"prompt_tokens": 0, "completion_tokens": 0})


def _fake_response_for(prompt: str) -> str:
    """Route on stable prompt markers set by the planner/inspection/QA services."""
    if "QUALITY CONTEXT:" in prompt:
        return json.dumps(_FAKE_INSPECTION)
    if "REQUIREMENTS:" in prompt:
        return json.dumps(_FAKE_PLAN)
    return json.dumps(_FAKE_QA)


_FAKE_PLAN = {
    "plan_title": "Draft machining plan (offline mode)",
    "summary": "Deterministic draft generated without an external LLM. Replace with a real model for production use.",
    "operations": [
        {
            "op_number": 10,
            "name": "Face and turn OD",
            "machine": "CNC Lathe-1",
            "tooling": ["CNMG turning insert", "C-clamp fixture"],
            "parameters": {"spindle_rpm": 1800, "feed_mm_rev": 0.2, "depth_of_cut_mm": 1.5, "coolant": "flood"},
            "description": "Face the end and rough/finish turn the outer diameter to stock removal limits.",
            "inspection_checkpoints": ["Verify overall length ±0.1 mm", "Check surface finish Ra ≤ 1.6"],
        },
        {
            "op_number": 20,
            "name": "Mill keyway",
            "machine": "VMC-2",
            "tooling": ["6 mm carbide end mill", "V-block fixture"],
            "parameters": {"spindle_rpm": 6000, "feed_mm_min": 250, "coolant": "mist"},
            "description": "Mill keyway slot per drawing; deburr edges after cutting.",
            "inspection_checkpoints": ["Keyway width 6.0 +0.2/-0.0 mm", "Depth check with pin gauge"],
        },
        {
            "op_number": 30,
            "name": "Drill and tap holes",
            "machine": "VMC-2",
            "tooling": ["Ø5 drill", "M6 tap"],
            "parameters": {"peck_depth_mm": 2.0, "spindle_rpm": 3000},
            "description": "Drill and tap per hole pattern on drawing; chamfer both sides.",
            "inspection_checkpoints": ["Thread go/no-go gauge", "Hole count = 4"],
        },
        {
            "op_number": 40,
            "name": "Final inspection",
            "machine": "QC Bench",
            "tooling": ["CMM", "Surface plate"],
            "parameters": {},
            "description": "Full dimensional layout per control plan and visual inspection.",
            "inspection_checkpoints": ["Dimensional report", "Visual: no burrs, scratches, corrosion"],
        },
    ],
    "inspection_plan": [
        {
            "characteristic": "Overall length",
            "method": "CMM",
            "frequency": "First article + every 10th",
            "acceptance_criteria": "50.0 ± 0.1 mm",
            "references": ["Control Plan"],
        },
        {
            "characteristic": "Surface finish",
            "method": "Profilometer",
            "frequency": "First article",
            "acceptance_criteria": "Ra ≤ 1.6 µm",
            "references": ["Drawing note 3"],
        },
        {
            "characteristic": "Visual defects",
            "method": "Visual + VLM-assisted",
            "frequency": "100%",
            "acceptance_criteria": "No cracks, burrs, or corrosion",
            "references": ["QC Visual SOP"],
        },
    ],
    "assumptions": ["Material is free-cutting steel unless specified", "Standard tooling available in tool crib"],
    "risk_notes": ["Verify stock size availability before releasing to shop"],
}

_FAKE_INSPECTION = {
    "verdict": "pass",
    "confidence": 0.62,
    "defects": [
        {
            "defect_type": "minor_scratch",
            "confidence": 0.55,
            "severity": "low",
            "location": "upper-left quadrant",
            "bbox": [0.12, 0.18, 0.2, 0.12],
            "evidence": "Faint linear marks consistent with handling; within acceptance limits for Class B surface.",
        }
    ],
    "explanation": "Offline heuristic verdict. Visual features suggest a minor surface scratch only; no cracks or corrosion detected. Replace the fake LLM with a real VLM for production verdicts.",
    "recommended_disposition": "accept",
}

_FAKE_QA = {
    "answer": "Based on the retrieved knowledge base excerpts (offline mode): follow the documented SOP sequence for this part family, verify material certification before first operation, and apply the inspection frequency defined in the control plan. [Offline answer - connect a real LLM for full quality.]",
    "confidence": 0.4,
    "refused": False,
    "refusal_reason": "",
}


def get_llm() -> BaseLLM:
    if settings.llm_provider == "openai" and settings.llm_api_key:
        return OpenAIResponsesLLM(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_s=settings.llm_timeout_s,
        )
    if settings.llm_provider == "openai_compatible" and settings.llm_api_key:
        return OpenAICompatibleLLM(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_s=settings.llm_timeout_s,
        )
    return FakeLLM()
