"""Pollinations AI prompt and URL generator provider."""

import logging
from typing import TYPE_CHECKING, Optional
import urllib.parse

from .base import BaseProvider

if TYPE_CHECKING:
    from ..models import Config

_LOGGER = logging.getLogger(__name__)


class AiArtProvider(BaseProvider):
    """Generates AI artwork prompts and Pollinations.ai URLs."""

    def __init__(self, config: "Config") -> None:
        self.config = config

    def format_prompt_url(self, artist: Optional[str], title: str) -> Optional[str]:
        """Format a deterministic Pollinations AI URL for the given artist and title."""
        api_key = getattr(self.config, "pollinations", "")
        if not api_key or not isinstance(api_key, str) or len(api_key.strip()) <= 5:
            _LOGGER.warning("Skipping AI Art generation: 'pollinations_key' is missing or invalid.")
            return None

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
        else:
            model = user_model

        url_params = f"?model={model}&width=512&height=512&seed={seed}&nologo=true&key={api_key.strip()}"
        return f"https://gen.pollinations.ai/image/{encoded_prompt}{url_params}"
