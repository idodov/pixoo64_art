"""Classical analog clock overlay renderer for 64x64 pixel display."""
import math
from datetime import datetime
from PIL import Image, ImageDraw


class AnalogClockRenderer:
    """Renderer for classical analog clock on 64x64 pixel display with dimmed album art."""

    CENTER = (31.5, 31.5)
    RADIUS = 28.0

    COLOR_BEZEL = (90, 95, 105)
    COLOR_MAJOR_TICK = (255, 240, 200)
    COLOR_MINOR_TICK = (160, 165, 175)
    COLOR_OUTLINE = (0, 0, 0)
    COLOR_HOUR_HAND = (255, 255, 255)
    COLOR_MINUTE_HAND = (255, 205, 50)
    COLOR_PIN = (230, 230, 235)

    @classmethod
    def render(cls, album_art: Image.Image, now: datetime | None = None) -> Image.Image:
        """Draw an analog clock frame over album art."""
        if now is None:
            now = datetime.now()

        base = Image.new("RGB", (64, 64), (0, 0, 0))
        art_64 = album_art.convert("RGBA").resize((64, 64), Image.Resampling.BILINEAR)
        dim_layer = Image.new("RGBA", (64, 64), (0, 0, 0, 135))
        dimmed_art = Image.alpha_composite(art_64, dim_layer)

        circle_mask = Image.new("L", (64, 64), 0)
        cx, cy = cls.CENTER
        r = cls.RADIUS
        ImageDraw.Draw(circle_mask).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
        base.paste(dimmed_art.convert("RGB"), (0, 0), circle_mask)

        draw = ImageDraw.Draw(base)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=cls.COLOR_BEZEL, width=1)
        cls._draw_ticks(draw, cx, cy, r)

        minute = now.minute
        hour = now.hour % 12
        second = now.second
        min_angle = (minute + second / 60.0) * 6.0
        hour_angle = (hour + minute / 60.0) * 30.0

        cls._draw_hand(draw, cx, cy, hour_angle, length=13.0, width=2, color=cls.COLOR_HOUR_HAND, outline_color=cls.COLOR_OUTLINE)
        cls._draw_hand(draw, cx, cy, min_angle, length=22.0, width=1, color=cls.COLOR_MINUTE_HAND, outline_color=cls.COLOR_OUTLINE)

        draw.ellipse([cx - 1.5, cy - 1.5, cx + 1.5, cy + 1.5], fill=cls.COLOR_PIN)
        draw.point((int(cx), int(cy)), fill=cls.COLOR_OUTLINE)
        return base

    @classmethod
    def _draw_ticks(cls, draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float) -> None:
        for h in range(12):
            angle_rad = math.radians(h * 30.0 - 90.0)
            cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
            if h % 3 == 0:
                r_in, r_out = r - 3.5, r - 1.0
                draw.line(
                    [(cx + r_in * cos_a, cy + r_in * sin_a), (cx + r_out * cos_a, cy + r_out * sin_a)],
                    fill=cls.COLOR_MAJOR_TICK,
                    width=1,
                )
            else:
                r_dot = r - 2.0
                draw.point((int(round(cx + r_dot * cos_a)), int(round(cy + r_dot * sin_a))), fill=cls.COLOR_MINOR_TICK)

    @classmethod
    def _draw_hand(
        cls,
        draw: ImageDraw.ImageDraw,
        cx: float,
        cy: float,
        angle_deg: float,
        length: float,
        width: int,
        color: tuple[int, int, int],
        outline_color: tuple[int, int, int],
    ) -> None:
        angle_rad = math.radians(angle_deg - 90.0)
        tip_x = cx + length * math.cos(angle_rad)
        tip_y = cy + length * math.sin(angle_rad)
        draw.line([(cx, cy), (tip_x, tip_y)], fill=outline_color, width=width + 2)
        draw.line([(cx, cy), (tip_x, tip_y)], fill=color, width=width)
