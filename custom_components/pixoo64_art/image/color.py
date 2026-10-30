"""Color science and LED-optimized palette extraction for Pixoo64 and WLED."""
import colorsys
import math
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple
from PIL import Image

if TYPE_CHECKING:
    from ..models import Config


class ColorAnalyzer:
    """Extracts dominant LED-optimized color palettes and high-contrast font colors."""

    def __init__(self, config: Optional["Config"] = None) -> None:
        self.config = config

    MONO_PALETTE_DARK = [
        (30, 60, 210),    # Deep Midnight Blue
        (110, 35, 200),   # Atmospheric Violet (WLED 2)
        (20, 150, 220),   # Cyber Teal/Cyan (WLED 3)
    ]
    MONO_PALETTE_BRIGHT = [
        (65, 105, 225),   # Royal Steel Blue
        (135, 80, 215),   # Soft Electric Purple (WLED 2)
        (255, 140, 40),   # Rich Amber Accent (WLED 3 - deeper punch)
    ]

    @classmethod
    def _optimize_for_led(cls, h: float, s: float, v: float) -> Tuple[int, int, int]:
        """LED bulbs require higher saturation than displays to avoid looking washed out."""
        opt_s = min(1.0, max(0.72, s ** 0.75 * 1.25))
        opt_v = min(0.95, max(0.65, v))
        r, g, b = colorsys.hsv_to_rgb(h, opt_s, opt_v)
        return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))

    @classmethod
    def get_image_palette(cls, img: Image.Image) -> list:
        if not img:
            return list(cls.MONO_PALETTE_DARK)

        proxy = img.convert("RGB").resize((48, 48), Image.Resampling.BILINEAR)
        pixels = list(proxy.getdata())

        buckets: Dict[Tuple[int, int, int], dict] = {}
        total_lum = 0.0
        chromatic_pixels = 0

        for r, g, b in pixels:
            rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
            h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)
            total_lum += v
            if v < 0.14:
                continue
            if (v > 0.60 and s < 0.32) or (v > 0.85 and s < 0.45) or s < 0.20:
                continue

            chromatic_pixels += 1
            key = (r >> 4, g >> 4, b >> 4)
            if key not in buckets:
                buckets[key] = {"count": 0, "r": 0, "g": 0, "b": 0}
            b_data = buckets[key]
            b_data["count"] += 1
            b_data["r"] += r
            b_data["g"] += g
            b_data["b"] += b

        avg_lum = total_lum / max(1, len(pixels))
        chromatic_ratio = chromatic_pixels / max(1, len(pixels))

        if chromatic_ratio < 0.035 or not buckets:
            return list(cls.MONO_PALETTE_BRIGHT if avg_lum > 0.55 else cls.MONO_PALETTE_DARK)

        scored_candidates = []
        for b_data in buckets.values():
            cnt = b_data["count"]
            avg_r = b_data["r"] // cnt
            avg_g = b_data["g"] // cnt
            avg_b = b_data["b"] // cnt
            h, s, v = colorsys.rgb_to_hsv(avg_r / 255.0, avg_g / 255.0, avg_b / 255.0)
            if s < 0.30:
                continue

            freq_weight = cnt ** 0.45
            sat_weight = s ** 2.2
            val_weight = 1.0 if 0.30 <= v <= 0.90 else 0.65
            whiteness_penalty = max(0.1, 1.0 - max(0.0, (v - s) * 0.8))
            scored_candidates.append({
                "hsv": (h, s, v),
                "score": freq_weight * sat_weight * val_weight * whiteness_penalty,
            })

        if not scored_candidates:
            return list(cls.MONO_PALETTE_BRIGHT if avg_lum > 0.55 else cls.MONO_PALETTE_DARK)

        scored_candidates.sort(key=lambda c: c["score"], reverse=True)
        selected_hsv: List[Tuple[float, float, float]] = []
        selected_rgb: List[Tuple[int, int, int]] = []

        for cand in scored_candidates:
            h, s, v = cand["hsv"]
            is_distinct = True
            for sh, ss, sv in selected_hsv:
                hue_dist = min(abs(h - sh), 1.0 - abs(h - sh))
                if hue_dist < 0.09 and (abs(s - ss) + abs(v - sv)) < 0.35:
                    is_distinct = False
                    break
            if is_distinct:
                selected_hsv.append((h, s, v))
                selected_rgb.append(cls._optimize_for_led(h, s, v))
                if len(selected_rgb) == 3:
                    break

        while len(selected_rgb) < 3:
            base_h, base_s, base_v = selected_hsv[0]
            if len(selected_rgb) == 1:
                new_h = (base_h + 0.085) % 1.0
                new_s = min(1.0, max(0.80, base_s * 1.15))
                new_v = max(0.60, base_v * 0.85)
            else:
                new_h = (base_h - 0.095) % 1.0
                new_s = min(1.0, max(0.85, base_s * 1.10))
                new_v = min(0.95, max(0.70, base_v * 1.05))
            selected_hsv.append((new_h, new_s, new_v))
            selected_rgb.append(cls._optimize_for_led(new_h, new_s, new_v))

        return selected_rgb

    @classmethod
    def get_optimal_font_color(cls, img: Image.Image, config: "Config") -> str:
        if getattr(config, 'force_font_color', None):
            return config.force_font_color

        small_thumb = img.resize((25, 25), Image.Resampling.NEAREST)
        colors_raw = small_thumb.getcolors(maxcolors=625) or []

        def vibrancy_score(item):
            count, rgb = item
            r, g, b = rgb[:3]
            _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            return (s * v * v) * (math.log(count) + 1)

        sorted_vibrant = sorted(colors_raw, key=vibrancy_score, reverse=True)
        chosen_dominant_color = None
        for _, color in sorted_vibrant:
            rgb = color[:3]
            _, s, v = colorsys.rgb_to_hsv(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)
            if s > 0.28 and 0.20 < v < 0.95:
                chosen_dominant_color = rgb
                break

        if not chosen_dominant_color and colors_raw:
            for _, color in sorted(colors_raw, key=lambda x: x[0], reverse=True):
                if sum(color[:3]) > 60:
                    chosen_dominant_color = color[:3]
                    break

        if getattr(config, 'text_bg', False):
            if chosen_dominant_color:
                r, g, b = chosen_dominant_color
                h, s, _ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                nr, ng, nb = colorsys.hsv_to_rgb(h, max(0.65, min(s, 1.0)), 1.0)
                return f'#{int(nr * 255):02x}{int(ng * 255):02x}{int(nb * 255):02x}'
            return "#00ffff"
        return "#ffffff"

    @classmethod
    def extract_image_values(
        cls,
        img: Image.Image,
        config: "Config",
        cropped_img: Optional[Image.Image] = None,
    ) -> dict:
        display_target = cropped_img if cropped_img is not None else img
        palette = cls.get_image_palette(img)
        prime_color = palette[0] if palette else (30, 60, 210)

        if getattr(config, 'text_bg', False):
            hex_color = f'#{prime_color[0]:02x}{prime_color[1]:02x}{prime_color[2]:02x}'
            most_common_color_alternative_rgb = prime_color
        else:
            most_common_color_alternative_rgb = prime_color
            hex_color = '#ffffff'

        brightness = int(sum(most_common_color_alternative_rgb) / 3)
        brightness_lower_part = round(1 - brightness / 255, 2) if 0 <= brightness <= 255 else 0

        analysis_display = display_target.resize((50, 50), Image.Resampling.NEAREST)
        font_color = cls.get_optimal_font_color(analysis_display, config)

        def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
            return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

        c1 = _rgb_to_hex(palette[0]) if len(palette) > 0 else "#1e3cd2"
        c2 = _rgb_to_hex(palette[1]) if len(palette) > 1 else c1
        c3 = _rgb_to_hex(palette[2]) if len(palette) > 2 else c2

        return {
            'font_color': font_color,
            'brightness': round(brightness / 255.0, 2),
            'brightness_lower_part': brightness_lower_part,
            'background_color_rgb': most_common_color_alternative_rgb,
            'background_color': hex_color,
            'color1': c1,
            'color2': c2,
            'color3': c3,
            'palette': palette,
        }

    def extract_info(
        self,
        img: Image.Image,
        media_data=None,
        cropped_img: Optional[Image.Image] = None,
    ) -> dict:
        return self.extract_image_values(img, self.config, cropped_img=cropped_img)
