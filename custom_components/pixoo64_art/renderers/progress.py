"""Playback progress bar renderer and timing scheduler for Pixoo64."""
from typing import TYPE_CHECKING, Optional
from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from ..models import Config, MediaData


class ProgressBarManager:
    """Calculates visual progress bar characters and next update delay."""

    def __init__(self, config: "Config", hass: HomeAssistant):
        self.config = config
        self.hass = hass
        self.current_bar_str = ""

    def calculate(self, position: float, duration: float) -> tuple[str, Optional[float]]:
        if duration <= 0:
            return "", None
        max_chars = self.config.progress_bar_resolution
        effective_duration = max(duration - 5.0, 1.0)
        ratio = min(position / effective_duration, 1.0)
        chars_needed = max(int(ratio * max_chars), 1)
        self.current_bar_str = self.config.progress_bar_character * chars_needed

        next_char_index = chars_needed + 1
        delay = None
        if next_char_index <= max_chars:
            target_time = (next_char_index / max_chars) * effective_duration
            delay = max(target_time - position, 0.2)
        return self.current_bar_str, delay

    async def get_payload_item(self, media_data: "MediaData") -> list:
        if not self.config.progress_bar_enabled or not getattr(media_data, 'show_progress_bar', False) or not self.current_bar_str:
            return []
        color = (
            getattr(media_data, 'lyrics_font_color', "#FFFFFF")
            if self.config.progress_bar_color == 'match'
            else self.config.progress_bar_color
        )
        y_pos = self.config.progress_bar_y_offset - 7
        return [
            {
                "TextId": tid, "type": 22, "x": x_off, "y": y_pos, "dir": 0,
                "font": self.config.progress_bar_font, "TextWidth": 64, "Textheight": 10,
                "speed": 0, "align": 1, "TextString": self.current_bar_str, "color": color,
            }
            for tid, x_off in ((19, 0), (20, 1), (21, 2))
        ]
