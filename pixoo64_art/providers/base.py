"""Base provider interface, album matching helpers, and fallback image generators."""

import difflib
import re
from typing import TYPE_CHECKING, Optional

from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from ..image.processor import ImageProcessor
    from ..models import MediaData


class BaseProvider:
    """Base interface for upstream artwork and metadata providers."""


_ALBUM_NOISE_RE = re.compile(
    r"[\(\[][^)\]]*(?:remaster|deluxe|expanded|anniversary|special|edition|version|mono|stereo|explicit|clean|bonus|disc\s*\d+|cd\s*\d+)[^)\]]*[\)\]]"
    r"|\s*-\s*(?:remaster(?:ed)?|deluxe.*|single|ep|mono|stereo.*)$",
    re.IGNORECASE,
)


def _normalize_album_name(name: Optional[str]) -> str:
    """Strip edition noise, punctuation, and extra whitespace for comparison."""
    if not name or not isinstance(name, str):
        return ""
    cleaned = _ALBUM_NOISE_RE.sub("", name).strip().lower()
    cleaned = re.sub(r"[^\w\s\u0590-\u05ff]", " ", cleaned)
    return " ".join(cleaned.split())


def _album_match_score(
    target_album: Optional[str], candidate_album: Optional[str]
) -> float:
    """Return similarity score (0.0 to 1.0) between known playing album and candidate album."""
    norm_t = _normalize_album_name(target_album)
    norm_c = _normalize_album_name(candidate_album)
    if not norm_t or not norm_c or norm_t in ("unknown album", "unknown", "none"):
        return 0.0
    if norm_t == norm_c:
        return 1.0
    if len(norm_t) >= 3 and len(norm_c) >= 3 and (norm_t in norm_c or norm_c in norm_t):
        return 0.90
    return difflib.SequenceMatcher(None, norm_t, norm_c).ratio()


def _is_album_match(
    target_album: Optional[str], candidate_album: Optional[str], threshold: float = 0.76
) -> bool:
    """Check whether a candidate album name is a reasonable match for target_album."""
    return _album_match_score(target_album, candidate_album) >= threshold


def create_tv_icon_image() -> Image.Image:
    """Create a 64x64 retro TV test-bars icon image."""
    image_width = 300
    image_height = 300
    final_width = 64
    final_height = 64
    vertical_offset = 10
    black = (0, 0, 0)
    brown = (139, 69, 19)
    screen_bg = (240, 240, 240)
    white = (255, 255, 255)
    gray = (150, 150, 150)
    rainbow_colors = [
        (255, 0, 0),
        (255, 165, 0),
        (255, 255, 0),
        (0, 255, 0),
        (0, 0, 255),
        (75, 0, 130),
        (238, 130, 238),
    ]
    image = Image.new("RGB", (image_width, image_height), black)
    draw = ImageDraw.Draw(image)
    tv_body_padding = 60 + vertical_offset
    tv_body_rect = [
        tv_body_padding,
        tv_body_padding,
        image_width - tv_body_padding,
        image_height - tv_body_padding - 40,
    ]
    draw.rounded_rectangle(tv_body_rect, 20, fill=brown)
    screen_padding = tv_body_padding + 15
    screen_rect = [
        screen_padding,
        screen_padding,
        image_width - screen_padding,
        tv_body_rect[3] - 15,
    ]
    draw.rectangle(screen_rect, fill=screen_bg)
    num_bars = len(rainbow_colors)
    bar_width = (screen_rect[2] - screen_rect[0]) // num_bars
    start_x = screen_rect[0]
    for color in rainbow_colors:
        bar_rect = [start_x, screen_rect[1], start_x + bar_width, screen_rect[3]]
        draw.rectangle(bar_rect, fill=color)
        start_x += bar_width
    antenna_base_x1 = image_width // 2 - 30
    antenna_base_x2 = image_width // 2 + 30
    antenna_base_y = tv_body_padding
    draw.line(
        (antenna_base_x1, antenna_base_y, antenna_base_x1 - 20, antenna_base_y - 50),
        fill=gray,
        width=3,
    )
    draw.line(
        (antenna_base_x2, antenna_base_y, antenna_base_x2 + 20, antenna_base_y - 50),
        fill=gray,
        width=3,
    )
    draw.line(
        (tv_body_rect[0], tv_body_rect[1], tv_body_rect[0] + 20, tv_body_rect[1]),
        fill=white,
        width=4,
    )
    draw.line(
        (tv_body_rect[0], tv_body_rect[1], tv_body_rect[0], tv_body_rect[1] + 20),
        fill=white,
        width=4,
    )
    return image.resize((final_width, final_height), Image.Resampling.BILINEAR)


def create_fallback_black_image_data(
    image_processor: "ImageProcessor", media_data: Optional["MediaData"] = None
) -> dict:
    """Create a 64x64 fallback dark card with burned text or music note icon."""
    img = Image.new("RGB", (64, 64), (25, 25, 30))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 63, 63], outline=(50, 50, 60), width=1)

    if media_data:
        artist = getattr(media_data, "artist", "Unknown Artist")
        title = getattr(media_data, "title", "Unknown Track")

        if artist == "Unknown Artist" and title == "Unknown Track":
            draw.ellipse([24, 34, 32, 42], fill=(150, 150, 150))
            draw.ellipse([38, 30, 46, 38], fill=(150, 150, 150))
            draw.line([(32, 38), (32, 18)], fill=(150, 150, 150), width=2)
            draw.line([(46, 34), (46, 14)], fill=(150, 150, 150), width=2)
            draw.line([(32, 18), (46, 14)], fill=(150, 150, 150), width=2)
            draw.line([(32, 19), (46, 15)], fill=(150, 150, 150), width=2)
        else:
            img = image_processor._draw_burned_text(img, media_data, "#FFFFFF")

    return {
        "pil_image": img,
        "clean_image": img,
        "base64_image": image_processor.gbase64(img),
        "font_color": "#FFFFFF",
        "brightness_lower_part": 0.5,
        "background_color": "#19191E",
        "background_color_rgb": (25, 25, 30),
        "color1": "#19191E",
        "color2": "#19191E",
        "color3": "#19191E",
    }
