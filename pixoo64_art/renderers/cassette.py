"""Vintage audio cassette tape animation renderer and MicroPixelFont bitmap engine."""
import logging
import math
import re
from typing import TYPE_CHECKING, List
from PIL import Image, ImageDraw

from ..models import unidecode

if TYPE_CHECKING:
    from ..image.processor import ImageProcessor
    from ..models import MediaData

_LOGGER = logging.getLogger(__name__)


class MicroPixelFont:
    """Ultra-compact proportional 5px high font bitmap engine."""

    GLYPHS = {
        ' ': [0, 0],
        'A': [0x1E, 0x05, 0x1E], 'B': [0x1F, 0x15, 0x0A], 'C': [0x0E, 0x11, 0x11],
        'D': [0x1F, 0x11, 0x0E], 'E': [0x1F, 0x15, 0x11], 'F': [0x1F, 0x05, 0x01],
        'G': [0x0E, 0x11, 0x1D], 'H': [0x1F, 0x04, 0x1F], 'I': [0x1F],
        'J': [0x08, 0x10, 0x0F], 'K': [0x1F, 0x04, 0x1B], 'L': [0x1F, 0x10, 0x10],
        'M': [0x1F, 0x02, 0x1F], 'N': [0x1F, 0x06, 0x1F], 'O': [0x0E, 0x11, 0x0E],
        'P': [0x1F, 0x05, 0x02], 'Q': [0x0E, 0x11, 0x1E], 'R': [0x1F, 0x05, 0x1A],
        'S': [0x12, 0x15, 0x09], 'T': [0x01, 0x1F, 0x01], 'U': [0x0F, 0x10, 0x0F],
        'V': [0x07, 0x18, 0x07], 'W': [0x1F, 0x08, 0x1F], 'X': [0x1B, 0x04, 0x1B],
        'Y': [0x03, 0x1C, 0x03], 'Z': [0x19, 0x15, 0x13],
        '0': [0x0E, 0x15, 0x0E], '1': [0x08, 0x1F],
        '2': [0x19, 0x15, 0x12], '3': [0x11, 0x15, 0x0A], '4': [0x07, 0x04, 0x1F],
        '5': [0x17, 0x15, 0x09], '6': [0x0E, 0x15, 0x09], '7': [0x01, 0x1D, 0x03],
        '8': [0x0A, 0x15, 0x0A], '9': [0x02, 0x15, 0x0E],
        '-': [0x04, 0x04], '.': [0x10], "'": [0x03], '&': [0x0A, 0x15, 0x12],
        '/': [0x10, 0x0C, 0x03], ':': [0x0A], '(': [0x0E, 0x11], ')': [0x11, 0x0E],
        '!': [0x17], '?': [0x01, 0x15, 0x02], '#': [0x0A, 0x1F, 0x0A, 0x1F, 0x0A],
        '★': [0x04, 0x1E, 0x0F, 0x1E, 0x04], '*': [0x04, 0x1E, 0x0F, 0x1E, 0x04],
        ',': [0x10, 0x08],
    }

    @classmethod
    def get_text_width(cls, text: str) -> int:
        if not text:
            return 0
        width = 0
        for ch in text.upper():
            glyph = cls.GLYPHS.get(ch, cls.GLYPHS.get('?'))
            width += len(glyph) + 1
        return width - 1

    @classmethod
    def draw_text(cls, draw: ImageDraw.ImageDraw, x: int, y: int, text: str, color: tuple):
        cur_x = x
        for ch in text.upper():
            glyph = cls.GLYPHS.get(ch, cls.GLYPHS.get('?'))
            if glyph:
                for col_idx, col_bits in enumerate(glyph):
                    for row_idx in range(5):
                        if (col_bits >> row_idx) & 1:
                            draw.point((cur_x + col_idx, y + row_idx), fill=color)
            cur_x += len(glyph) + 1


class CassetteRenderer:
    """Generates an authentic 6-frame looping vintage audio cassette animation."""

    @classmethod
    def render_frames(cls, base_img: Image.Image, image_processor: "ImageProcessor", media_data: "MediaData") -> List[str]:
        frames_b64 = []
        pil_frames = []
        try:
            palette = image_processor.get_image_palette(base_img)
            accent_color = palette[0] if palette else (185, 148, 62)

            shell_color = (20, 20, 22)
            label_bg = (242, 240, 232)
            window_bg = (14, 14, 16)
            spool_outer = (225, 225, 225)
            left_cx, right_cx, spool_cy, r_spool, total_frames = 22, 33, 32, 6, 6

            max_px = 52
            title_text = cls._prepare_text(media_data.title, max_px)
            artist_text = cls._prepare_text(media_data.artist, max_px)

            base_canvas = Image.new("RGB", (64, 64), (6, 6, 8))
            draw = ImageDraw.Draw(base_canvas)
            draw.rectangle([1, 1, 62, 62], fill=shell_color)
            for sx, sy in [(3, 3), (60, 3), (3, 60), (60, 60)]:
                draw.point((sx, sy), fill=(160, 160, 170))
                draw.point((sx + 1, sy), fill=(100, 100, 110))

            draw.rectangle([4, 3, 59, 18], fill=label_bg)
            draw.line([(4, 10), (59, 10)], fill=(210, 45, 45), width=1)
            MicroPixelFont.draw_text(draw, 6, 4, title_text, (20, 45, 110))
            MicroPixelFont.draw_text(draw, 6, 12, artist_text, (35, 35, 40))

            draw.rectangle([13, 21, 50, 42], fill=window_bg)
            draw.rectangle([13, 21, 50, 42], outline=(40, 40, 45), width=1)
            for mx in [29, 31, 33, 35]:
                draw.line([(mx, 26), (mx, 37)], fill=(75, 75, 80), width=1)

            draw.rectangle([4, 45, 59, 49], fill=accent_color)
            MicroPixelFont.draw_text(draw, 6, 45, "MIX", (255, 255, 255))
            MicroPixelFont.draw_text(draw, 49, 45, "90", (255, 255, 255))

            draw.polygon([(11, 62), (18, 52), (45, 52), (52, 62)], fill=(28, 28, 32))
            draw.line([(18, 52), (45, 52)], fill=(45, 45, 50), width=1)
            draw.ellipse([23, 55, 27, 59], fill=(6, 6, 8))
            draw.ellipse([36, 55, 40, 59], fill=(6, 6, 8))
            draw.point((32, 57), fill=(120, 120, 125))

            filter_mode = getattr(image_processor.config, 'image_filter', 'None')
            base_canvas = image_processor.filter_service.apply_post_scale(base_canvas, filter_mode)
            base_canvas = image_processor.text_clock_img(base_canvas, {}, media_data)

            for f in range(total_frames):
                canvas = base_canvas.copy()
                draw = ImageDraw.Draw(canvas)
                rad = math.radians(f * 10.0)
                for scx in [left_cx, right_cx + 9]:
                    draw.ellipse([scx - r_spool, spool_cy - r_spool, scx + r_spool, spool_cy + r_spool], fill=spool_outer)
                    draw.ellipse([scx - 3, spool_cy - 3, scx + 3, spool_cy + 3], fill=(8, 8, 10))
                    for tooth_idx in range(6):
                        t_angle = rad + (tooth_idx * math.pi / 3.0)
                        tx = scx + int(round(math.cos(t_angle) * 4.5))
                        ty = spool_cy + int(round(math.sin(t_angle) * 4.5))
                        draw.point((tx, ty), fill=(30, 30, 35))

                pil_frames.append(canvas.copy())
                b64 = image_processor.gbase64(canvas)
                if b64:
                    frames_b64.append(b64)

            if pil_frames:
                c_key = f"cassette_{media_data.artist}_{media_data.title}"
                media_data.live_display_url = image_processor.save_live_display_gif(pil_frames, 100, c_key)
        except Exception as e:
            _LOGGER.error("Error generating vintage cassette animation frames: %s", e)
        return frames_b64

    @staticmethod
    def _prepare_text(raw_text: str, max_px: int) -> str:
        if not raw_text:
            return ""
        translit = re.sub(r'[^a-zA-Z0-9\s\-\.\'\&\/\:\(\)\!\?]', '', unidecode(str(raw_text)).strip())
        if MicroPixelFont.get_text_width(translit) <= max_px:
            return translit

        allowed_width = max_px - MicroPixelFont.get_text_width("..")
        truncated, current_width = "", 0
        for char in translit:
            char_w = MicroPixelFont.get_text_width(char)
            if current_width + char_w > allowed_width:
                break
            truncated += char
            current_width += char_w + 1
        return f"{truncated.strip()}.."
