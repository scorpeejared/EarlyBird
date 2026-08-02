"""
Bring-your-own-AI: one image-plus-schema call, several possible backends.

The app never ships a key. The user picks a provider, supplies their own
credentials, and the rest of the app just asks for JSON matching a schema.

Three built-ins cover most of what people actually have:
  - "gemini"      Google's API, via google-genai
  - "openai"      OpenAI's API, via the openai SDK
  - "compatible"  anything speaking OpenAI's /chat/completions at a base URL
                  you supply - OpenRouter, Groq, Together, and local servers
                  like Ollama, LM Studio or vLLM

"compatible" is what makes "any AI" true, and a local endpoint is the one
configuration where the screenshot never leaves the machine at all.
"""
from __future__ import annotations

import base64
import copy
import json
from dataclasses import dataclass

from .logging_setup import get_logger

logger = get_logger()

GEMINI = "gemini"
OPENAI = "openai"
COMPATIBLE = "compatible"


class ProviderError(Exception):
    """A backend call failed. Message is written for the user."""


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    default_model: str
    key_label: str
    key_url: str
    # Local servers frequently accept any key, or none at all.
    key_required: bool
    needs_base_url: bool
    # What the user is agreeing to when they send an image here. Shown in the
    # privacy notice, so it must describe *that* provider honestly.
    privacy_note: str
    # OpenAI-style structured outputs demand additionalProperties:false on
    # every object; Gemini's schema subset does not accept it.
    strict_schema: bool


PROVIDERS: dict[str, Provider] = {
    GEMINI: Provider(
        id=GEMINI,
        label="Google Gemini",
        default_model="gemini-3.6-flash",
        key_label="Gemini API key",
        key_url="https://aistudio.google.com/apikey",
        key_required=True,
        needs_base_url=False,
        privacy_note=(
            "Google's free tier states that submitted content is used to "
            "improve their products. On a paid key it is not."
        ),
        strict_schema=False,
    ),
    OPENAI: Provider(
        id=OPENAI,
        label="OpenAI",
        default_model="gpt-5.6",
        key_label="OpenAI API key",
        key_url="https://platform.openai.com/api-keys",
        key_required=True,
        needs_base_url=False,
        privacy_note=(
            "OpenAI states that content sent through the API is not used to "
            "train their models by default."
        ),
        strict_schema=True,
    ),
    COMPATIBLE: Provider(
        id=COMPATIBLE,
        label="Other (OpenAI-compatible)",
        default_model="",
        key_label="API key (leave blank if your server doesn't need one)",
        key_url="",
        key_required=False,
        needs_base_url=True,
        privacy_note=(
            "The image goes to the server address you entered, under that "
            "provider's own terms. If it's a local address such as "
            "localhost, the image never leaves this computer."
        ),
        strict_schema=True,
    ),
}

DEFAULT_PROVIDER = GEMINI


def get(provider_id: str) -> Provider:
    return PROVIDERS.get(provider_id) or PROVIDERS[DEFAULT_PROVIDER]


def _strictify(schema: dict) -> dict:
    """Add additionalProperties:false to every object, as strict mode wants."""
    node = copy.deepcopy(schema)

    def walk(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "object":
                obj["additionalProperties"] = False
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(node)
    return node


def generate_json(
    provider_id: str,
    model: str,
    base_url: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    image_bytes: bytes,
    mime_type: str,
    schema: dict,
) -> dict:
    """Ask a vision model to describe an image as JSON matching `schema`.

    Returns the decoded object. Raises ProviderError with a user-facing
    message on any failure, including a response that isn't valid JSON.
    """
    provider = get(provider_id)
    model = (model or provider.default_model).strip()
    if not model:
        raise ProviderError("No model name is set for this provider.")
    if provider.key_required and not api_key:
        raise ProviderError(f"No {provider.key_label} is set.")
    if provider.needs_base_url and not base_url.strip():
        raise ProviderError("No server address is set for this provider.")

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    try:
        if provider.id == GEMINI:
            text = _call_gemini(model, api_key, system_prompt, user_prompt,
                                encoded, mime_type, schema)
        else:
            text = _call_openai_compatible(provider, model, base_url, api_key,
                                           system_prompt, user_prompt,
                                           encoded, mime_type, schema)
    except ProviderError:
        raise
    except Exception as e:  # noqa: BLE001 - SDKs raise widely; all are user-facing here
        logger.warning(f"{provider.id} request failed: {type(e).__name__}: {e}")
        raise ProviderError(friendly_error(e, provider)) from e

    if not text or not text.strip():
        raise ProviderError("The AI sent back an empty response. Please try again.")

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"{provider.id} returned non-JSON: {text[:200]!r}")
        raise ProviderError(
            "The AI's response wasn't valid JSON. If you're using a custom "
            "server, check that its model supports structured output."
        ) from e


def _call_gemini(model, api_key, system_prompt, user_prompt, encoded, mime_type, schema) -> str:
    try:
        from google import genai
    except ImportError:
        raise ProviderError(
            "The google-genai package isn't installed, so Gemini can't be used."
        ) from None

    client = genai.Client(api_key=api_key)
    interaction = client.interactions.create(
        model=model,
        system_instruction=system_prompt,
        input=[
            {"type": "text", "text": user_prompt},
            {"type": "image", "data": encoded, "mime_type": mime_type},
        ],
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": schema,
        },
        generation_config={"thinking_level": "low"},
    )
    return getattr(interaction, "output_text", "") or ""


def _call_openai_compatible(provider, model, base_url, api_key, system_prompt,
                            user_prompt, encoded, mime_type, schema) -> str:
    """One /chat/completions call.

    Deliberately the older chat-completions surface rather than OpenAI's newer
    Responses API: chat-completions is what every third-party and local server
    implements, and it is what makes one adapter serve all of them.
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ProviderError(
            "The openai package isn't installed, so this provider can't be used."
        ) from None

    client = OpenAI(
        # Local servers often ignore the key but the SDK insists on a string.
        api_key=api_key or "not-needed",
        base_url=base_url.strip() or None,
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": user_prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
        ]},
    ]

    strict_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "schedule",
            "schema": _strictify(schema) if provider.strict_schema else schema,
            "strict": True,
        },
    }

    try:
        response = client.chat.completions.create(
            model=model, messages=messages, response_format=strict_format,
        )
    except Exception as e:  # noqa: BLE001 - see fallback below
        if not _looks_like_schema_rejection(e):
            raise
        # Plenty of compatible servers implement plain JSON mode but not full
        # json_schema. Falling back keeps them usable; the caller sanitises
        # the result either way, so a looser response can't corrupt anything.
        logger.info(f"{provider.id} rejected json_schema; retrying in JSON mode")
        response = client.chat.completions.create(
            model=model, messages=messages,
            response_format={"type": "json_object"},
        )

    if not response.choices:
        return ""
    return response.choices[0].message.content or ""


def _looks_like_schema_rejection(error: Exception) -> bool:
    text = f"{type(error).__name__}: {error}".lower()
    if not any(w in text for w in ("json_schema", "response_format", "schema", "strict")):
        return False
    # Only retry on the server saying "I don't do that", never on auth,
    # rate-limit or connection failures.
    return any(w in text for w in ("unsupported", "not supported", "invalid", "unrecognized", "400"))


def friendly_error(error: Exception, provider: Provider) -> str:
    """Turn an SDK exception into something worth showing a student."""
    text = f"{type(error).__name__}: {error}".lower()
    if any(w in text for w in ("api key", "api_key", "unauthenticated", "unauthorized",
                               "permission", "401", "403")):
        return f"That {provider.label} key was rejected. Check the key and try again."
    if any(w in text for w in ("quota", "resource_exhausted", "rate limit",
                               "rate_limit", "insufficient_quota", "429")):
        return f"{provider.label} hit a rate limit or quota. Try again in a minute."
    if any(w in text for w in ("model_not_found", "does not exist", "unknown model", "404")):
        return f"{provider.label} doesn't recognise that model name. Check it in setup."
    if any(w in text for w in ("deadline", "timeout", "connection", "network", "dns",
                               "unavailable", "refused")):
        if provider.needs_base_url:
            return "Couldn't reach that server address. Check it's running and try again."
        return f"Couldn't reach {provider.label}. Check your internet connection."
    return "Couldn't read this screenshot. Please try again, or add the class by hand."
