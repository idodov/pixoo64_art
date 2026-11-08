"""Pollinations AI prompt and URL generator provider."""

import logging
import time
from typing import TYPE_CHECKING, Optional
import urllib.parse
import aiohttp

from .base import BaseProvider

if TYPE_CHECKING:
    from ..models import Config

_LOGGER = logging.getLogger(__name__)


POLLINATIONS_CLIENT_ID = "pk_BGuQDoVvDvRQ4k8T"

MODEL_PRICING_MAP: dict[str, dict] = {
    "black-forest-labs/flux.1-schnell": {"cost": 0.0, "cost_display": "Free"},
    "flux": {"cost": 0.0, "cost_display": "Free"},
    "turbo": {"cost": 0.0, "cost_display": "Free"},
    "flux-realism": {"cost": 0.0, "cost_display": "Free"},
    "community/scriptsnsenses-sys/flux-2-dev-free": {"cost": 0.0, "cost_display": "Free"},
    "black-forest-labs/flux.1-dev": {"cost": 0.003125, "cost_display": "0.003125"},
    "recraft/recraft-v4.1-vector": {"cost": 0.00625, "cost_display": "0.00625"},
}


def get_model_cost(model_name: Optional[str]) -> tuple[float, str]:
    """Return (cost, cost_display) for a model name with 20% developer fee included."""
    if not model_name:
        return 0.0, "Free"
    m_clean = str(model_name).strip().lower()
    if m_clean in MODEL_PRICING_MAP:
        info = MODEL_PRICING_MAP[m_clean]
        return float(info["cost"]), str(info["cost_display"])
    for k, v in MODEL_PRICING_MAP.items():
        if k.lower() == m_clean or k.split("/")[-1].lower() == m_clean:
            return float(v["cost"]), str(v["cost_display"])
    if any(s in m_clean for s in ("free", "schnell", "turbo", "lightning")):
        return 0.0, "Free"
    return 0.0, "Free"


_MODELS_CACHE: dict[tuple[str, bool], tuple[float, list]] = {}


async def async_fetch_pollinations_models(session: aiohttp.ClientSession, api_key: str = None, is_login: bool = False) -> list:
    """Fetch available AI models dynamically and update pricing lookup table."""
    clean_key = str(api_key or "").strip()
    cache_key = (clean_key[:12], bool(is_login))
    now = time.monotonic()
    cached = _MODELS_CACHE.get(cache_key)
    if cached and (now - cached[0]) < 3600.0:
        return cached[1]

    multiplier = 1.25 if is_login else 1.0
    fallback_models = [
        {"id": "black-forest-labs/flux.1-schnell", "label": "FLUX.1 Schnell (Black Forest Labs) | 🪙 Free", "cost": 0.0},
        {"id": "flux", "label": "FLUX (Classic) | 🪙 Free", "cost": 0.0},
        {"id": "turbo", "label": "Turbo / Lightning (Fast) | 🪙 Free", "cost": 0.0},
        {"id": "flux-realism", "label": "FLUX Realism | 🪙 Free", "cost": 0.0},
        {"id": "recraft/recraft-v4.1-vector", "label": f"Recraft V4.1 Vector | 🪙 {round(0.005 * multiplier, 6)}", "cost": round(0.005 * multiplier, 6)},
        {"id": "black-forest-labs/flux.1-dev", "label": f"FLUX.1 Dev | 🪙 {round(0.0025 * multiplier, 6)}", "cost": round(0.0025 * multiplier, 6)},
    ]
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        if clean_key.startswith("sk_"):
            headers["Authorization"] = f"Bearer {clean_key}"

        async def _fetch(hdrs):
            async with session.get("https://gen.pollinations.ai/models", headers=hdrs, timeout=8) as response:
                if response.status == 200:
                    return await response.json(content_type=None)
                return None

        data = await _fetch(headers)
        if data is None and "Authorization" in headers:
            data = await _fetch({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

        if data and isinstance(data, list):
            parsed_models = []
            for model in data:
                if not isinstance(model, dict):
                    continue
                if model.get("category") == "image" or "image" in model.get("output_modalities", []):
                    model_id = model.get("name")
                    if not model_id:
                        continue
                    title = model.get("title", model_id)
                    publisher = model.get("publisher", "Unknown")
                    try:
                        base_cost = float(model.get("pricing", {}).get("completionImageTokens", 0))
                    except (ValueError, TypeError):
                        base_cost = 0.0
                    cost = round(base_cost * multiplier, 8)
                    cost_display = "Free" if cost == 0 else f"{cost:.8f}".rstrip("0").rstrip(".")
                    MODEL_PRICING_MAP[model_id.lower()] = {"cost": cost, "cost_display": cost_display}
                    parsed_models.append({"id": model_id, "label": f"{title} ({publisher}) | 🪙 {cost_display}", "cost": cost})
            parsed_models.sort(key=lambda x: x["cost"])
            if parsed_models:
                _MODELS_CACHE[cache_key] = (now, parsed_models)
                return parsed_models
    except Exception as e:
        _LOGGER.warning("Failed to fetch dynamic AI models: %s", e)
    return fallback_models


class AiArtProvider(BaseProvider):
    """Generates AI artwork prompts and Pollinations.ai URLs."""

    def __init__(self, config: "Config") -> None:
        self.config = config

    def _get_prompt_and_seed(self, artist: Optional[str], title: str) -> tuple[str, int, str]:
        artist_name = artist if artist else "Music"
        clean_artist = artist_name.replace("/", " ").replace("\\", " ").strip()
        clean_title = title.replace("/", " ").replace("\\", " ").strip()

        prompts = [
            f"Vibrant pop art portrait of the musician {clean_artist} inspired by the song '{clean_title}', edge-to-edge full bleed, borderless, bold neon colors, high contrast flat colors for pixel display, strictly no text, no words, zero frames",
            f"Edge-to-edge vibrant surreal artwork literally depicting the concept of '{clean_title}' by {clean_artist}, vivid high contrast colors, thick outlines, borderless full bleed, strictly no text, no letters, no frames",
            f"Retro synthwave portrait of {clean_artist} performing '{clean_title}', neon magenta and cyan, edge-to-edge borderless, pitch black background, high contrast lighting, absolutely no typography, no words, full bleed, no borders",
            f"Borderless minimalist illustration of the literal meaning of '{clean_title}' (by {clean_artist}), flat bold vibrant colors, edge-to-edge composition, zero borders, clear focal point suited for low resolution display, strictly no text, no typography",
            f"Moody graphic novel style portrait of the artist {clean_artist} singing '{clean_title}', vivid high contrast flat colors, edge-to-edge full bleed, borderless frame, strictly no text, no speech bubbles, zero typography",
            f"Colorful 16-bit style crisp illustration literally showing '{clean_title}' by {clean_artist}, vivid nostalgic palette, edge-to-edge borderless composition, zero text, no borders, no frames, strictly no typography, perfectly cropped",
            f"Luminous stained glass mosaic showing the literal meaning of '{clean_title}' by {clean_artist}, edge-to-edge borderless, saturated jewel tones, thick black outlines, full bleed, absolutely no text, no letters, zero frames",
            f"Vibrant vector portrait of {clean_artist} with elements from '{clean_title}', flat bold geometric shapes, edge-to-edge borderless design, high contrast palette for LED displays, strictly no text, no words, no borders",
            f"Japanese anime style vibrant scenery depicting '{clean_title}' by {clean_artist}, edge-to-edge borderless full bleed composition, highly saturated colors, high contrast, zero typography, no text, no borders, no letters",
            f"Bold colorful representation of {clean_artist} and the vibe of '{clean_title}', edge-to-edge borderless canvas, thick lines, neon and primary colors, flat design for pixel grid, strictly no text, no frames, zero words",
        ]

        song_signature = f"{clean_artist}_{clean_title}".lower()
        prompt_index = abs(hash(song_signature)) % len(prompts)
        selected_prompt = prompts[prompt_index]
        encoded_prompt = urllib.parse.quote(selected_prompt, safe="")

        seed = abs(hash(song_signature)) % 2147483647
        user_model = (
            str(
                getattr(self.config, "ai_fallback", "black-forest-labs/flux.1-schnell")
                or "black-forest-labs/flux.1-schnell"
            )
            .lower()
            .strip()
        )

        if user_model in ["turbo", "lightning"]:
            model = "inferenceport-ai/lightning-image-turbo"
        elif user_model in ["flux", "schnell"]:
            model = "black-forest-labs/flux.1-schnell"
        elif user_model == "vector":
            model = "recraft/recraft-v4.1-vector"
        elif "/" not in user_model:
            # Resolve bare model name to publisher/model canonical ID if known
            canonical = None
            for full_id in MODEL_PRICING_MAP:
                if full_id.split("/")[-1].lower() == user_model:
                    canonical = full_id
                    break
            model = canonical or user_model
        else:
            model = user_model

        return encoded_prompt, seed, model

    def format_free_prompt_url(self, artist: Optional[str], title: str) -> Optional[str]:
        """Format a free Pollinations AI URL (image.pollinations.ai) without requiring an API key."""
        encoded_prompt, seed, model = self._get_prompt_and_seed(artist, title)
        free_model = "turbo" if any(k in str(model).lower() for k in ("turbo", "lightning")) else "flux"
        return f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=512&height=512&model={free_model}&seed={seed}&nologo=true"

    def format_prompt_url(self, artist: Optional[str], title: str) -> Optional[str]:
        """Format a deterministic Pollinations AI URL for the given artist and title."""
        ai_tier = str(getattr(self.config, "ai_tier", "free")).lower()
        api_key = str(getattr(self.config, "pollinations", "") or getattr(self.config, "pollinations_key", "") or "").strip()

        # If on Free Tier or no valid secret key, ALWAYS use the free tier endpoint
        if ai_tier == "free" or not api_key.startswith("sk_"):
            return self.format_free_prompt_url(artist, title)

        encoded_prompt, seed, model = self._get_prompt_and_seed(artist, title)
        # Authenticated via Bearer token in HTTP headers and query param key
        url_params = f"?model={model}&width=512&height=512&seed={seed}&nologo=true&key={api_key}"
        return f"https://gen.pollinations.ai/image/{encoded_prompt}{url_params}"


async def async_request_device_code(session: aiohttp.ClientSession) -> Optional[dict]:
    """Request a new OAuth device authorization code from Pollinations."""
    try:
        url = "https://enter.pollinations.ai/api/device/code"
        payload = {"client_id": POLLINATIONS_CLIENT_ID}
        headers = {"Content-Type": "application/json", "User-Agent": "Pixoo64-HA-Integration"}
        async with session.post(url, json=payload, headers=headers, timeout=10) as resp:
            if resp.status == 200:
                return await resp.json()
            _LOGGER.warning("Pollinations device code request failed with HTTP %s", resp.status)
    except Exception as err:
        _LOGGER.warning("Error requesting Pollinations device code: %s", err)
    return None


async def async_exchange_device_token(session: aiohttp.ClientSession, device_code: str) -> tuple[Optional[str], Optional[str]]:
    """Poll or exchange device code for an access token (sk_...) from Pollinations."""
    try:
        url = "https://enter.pollinations.ai/api/device/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Pixoo64-HA-Integration",
        }
        data = {
            "device_code": device_code,
            "client_id": POLLINATIONS_CLIENT_ID,
        }
        async with session.post(url, data=data, headers=headers, timeout=10) as resp:
            resp_data = await resp.json(content_type=None)
            if resp.status == 200 and "access_token" in resp_data:
                return resp_data["access_token"], None
            err_code = resp_data.get("error", "unknown_error")
            return None, err_code
    except Exception as err:
        _LOGGER.warning("Error exchanging Pollinations device token: %s", err)
        return None, "network_error"


async def async_get_pollen_balance(session: aiohttp.ClientSession, api_key: str) -> Optional[dict]:
    """Fetch current Pollen balance from Pollinations API for a secret key."""
    if not api_key or not api_key.startswith("sk_"):
        return None
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Client-Id": POLLINATIONS_CLIENT_ID,
            "User-Agent": "Pixoo64-HA-Integration",
        }
        async with session.get("https://gen.pollinations.ai/account/balance", headers=headers, timeout=5) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data
    except Exception as err:
        _LOGGER.debug("Could not fetch Pollinations account balance: %s", err)
    return None
