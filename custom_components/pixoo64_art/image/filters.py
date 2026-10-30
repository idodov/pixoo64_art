"""Pre-scale and post-scale PIL pixel filter and overlay service for Pixoo64."""
import logging
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat
from ..models import is_arabic, is_hebrew, prepare_bidi_text

if TYPE_CHECKING:
    from ..models import Config, MediaData

_LOGGER = logging.getLogger(__name__)


class ImageFilterService:
    """Applies artistic pre-scale and post-scale pixel filters and overlays using PIL."""

    @staticmethod
    def apply_pre_scale(img: Image.Image, filter_mode: str) -> Image.Image:
        if not filter_mode or filter_mode == "None":
            return img
        try:
            if filter_mode == "Vibrant":
                img = ImageEnhance.Color(img).enhance(1.45)
                img = ImageEnhance.Contrast(img).enhance(1.15)
            elif filter_mode == "Retro Arcade":
                img = ImageEnhance.Color(img).enhance(1.25)
                img = ImageEnhance.Contrast(img).enhance(1.20)
            elif filter_mode == "Crisp & Sharp":
                img = ImageEnhance.Contrast(img).enhance(1.10)
            elif filter_mode == "Noir B&W":
                img = ImageOps.grayscale(img).convert("RGB")
                img = ImageEnhance.Contrast(img).enhance(1.35)
            elif filter_mode == "Cyberpunk Neon":
                img = ImageOps.autocontrast(img, cutoff=2)
                img = ImageEnhance.Color(img).enhance(1.80)
                img = ImageEnhance.Contrast(img).enhance(1.30)
        except Exception as e:
            _LOGGER.debug("Pre-scale filter error: %s", e)
        return img

    @staticmethod
    def apply_post_scale(img: Image.Image, filter_mode: str) -> Image.Image:
        if not filter_mode or filter_mode == "None":
            return img
        try:
            if filter_mode == "Vibrant":
                img = ImageEnhance.Sharpness(img).enhance(1.25)
            elif filter_mode == "Retro Arcade":
                img = ImageOps.posterize(img, bits=3)
            elif filter_mode == "Crisp & Sharp":
                img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=170, threshold=2))
            elif filter_mode == "Noir B&W":
                img = ImageEnhance.Sharpness(img).enhance(1.20)
            elif filter_mode == "Cyberpunk Neon":
                img = img.filter(ImageFilter.EDGE_ENHANCE)
        except Exception as e:
            _LOGGER.debug("Post-scale filter error: %s", e)
        return img

    @staticmethod
    def fixed_size(image: Image.Image) -> Image.Image:
        width, height = image.size
        if width == height:
            return image
        if height < width:
            border_size = (width - height) // 2
            try:
                background_color = image.getpixel((0, 0))
            except Exception:
                background_color = (0, 0, 0)
            new_img = Image.new("RGB", (width, width), background_color)
            new_img.paste(image, (0, border_size))
            return new_img
        new_size = min(width, height)
        left = (width - new_size) // 2
        top = (height - new_size) // 2
        return image.crop((left, top, left + new_size, top + new_size))

    @staticmethod
    def special_mode(image: Image.Image, config: "Config") -> Image.Image:
        if image is None:
            return None
        output_size = (64, 64)
        album_size = (34, 34) if getattr(config, "show_text", False) else (56, 56)
        album_art = image.resize(album_size, Image.Resampling.BILINEAR)
        try:
            left_color = album_art.getpixel((0, album_size[1] // 2))
            right_color = album_art.getpixel((album_size[0] - 1, album_size[1] // 2))
        except Exception:
            left_color, right_color = (100, 100, 100), (150, 150, 150)

        if album_size == (34, 34):
            gradient_source = Image.new("RGB", (2, 1))
            gradient_source.putpixel((0, 0), left_color)
            gradient_source.putpixel((1, 0), right_color)
            background = gradient_source.resize(output_size, Image.Resampling.BILINEAR)
        else:
            dark_bg = (
                min(left_color[0], right_color[0]) // 2,
                min(left_color[1], right_color[1]) // 2,
                min(left_color[2], right_color[2]) // 2,
            )
            background = Image.new("RGB", output_size, dark_bg)

        x = (output_size[0] - album_size[0]) // 2
        background.paste(album_art, (x, 8))
        return background

    @staticmethod
    def draw_burned_text(
        image: Image.Image,
        media_data: "MediaData",
        font_color_hex: str,
        font_cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont],
    ) -> Image.Image:
        img = image.copy()
        draw = ImageDraw.Draw(img)
        artist = getattr(media_data, "artist", "")
        title = getattr(media_data, "title", "")
        if not artist and not title:
            return img

        comp_dir = os.path.dirname(os.path.dirname(__file__))
        fonts_dir = os.path.join(comp_dir, "fonts")

        def get_font(text: str, size: int = 8, bold: bool = False):
            candidates = []
            if is_arabic(text):
                candidates.extend([
                    os.path.join(fonts_dir, "NotoSansArabic-Regular.ttf"),
                    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
                    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                    "C:\\Windows\\Fonts\\arial.ttf",
                ])
            elif is_hebrew(text):
                candidates.extend([
                    os.path.join(fonts_dir, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/TTF/DejaVuSans.ttf",
                    os.path.join(comp_dir, "arial.ttf"),
                    "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
                ])
            else:
                candidates.extend(
                    [
                        os.path.join(fonts_dir, "DejaVuSans-Bold.ttf"),
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                        "C:\\Windows\\Fonts\\arialbd.ttf",
                        os.path.join(fonts_dir, "DejaVuSans.ttf"),
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                        "/usr/share/fonts/TTF/DejaVuSans.ttf",
                        "C:\\Windows\\Fonts\\arial.ttf",
                        os.path.join(comp_dir, "arial.ttf"),
                    ]
                    if bold
                    else [
                        os.path.join(fonts_dir, "DejaVuSans.ttf"),
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                        "/usr/share/fonts/TTF/DejaVuSans.ttf",
                        "C:\\Windows\\Fonts\\arial.ttf",
                        os.path.join(comp_dir, "arial.ttf"),
                    ]
                )
            for p in candidates:
                key = (p, size)
                if key in font_cache:
                    if font_cache[key] is not None:
                        return font_cache[key]
                    continue
                if os.path.isfile(p):
                    try:
                        font = ImageFont.truetype(p, size)
                        font_cache[key] = font
                        return font
                    except Exception:
                        pass
                font_cache[key] = None
            return ImageFont.load_default()

        def format_text(text: str) -> str:
            if not text:
                return ""
            return prepare_bidi_text(text)

        def measure_text(text: str, font) -> float:
            if not text:
                return 0.0
            is_rtl = is_hebrew(text) or is_arabic(text)
            try:
                from PIL import features
                if features.check("raqm") and is_rtl:
                    return draw.textlength(text, font=font, direction="rtl")
            except Exception:
                pass
            f_text = format_text(text) if is_rtl else text
            try:
                return draw.textlength(f_text, font=font)
            except Exception:
                return len(f_text) * 5.5

        def wrap_to_lines(raw_text: str, font, max_w: int = 60) -> list[str]:
            if not raw_text:
                return []
            words = raw_text.strip().split()
            if not words:
                return []
            lines: list[str] = []
            cur_words: list[str] = []
            for w in words:
                test_str = " ".join(cur_words + [w])
                w_len = measure_text(test_str, font=font)
                if w_len <= max_w:
                    cur_words.append(w)
                else:
                    if cur_words:
                        lines.append(" ".join(cur_words))
                        cur_words = []
                    single_w_len = measure_text(w, font=font)
                    if single_w_len <= max_w:
                        cur_words = [w]
                    else:
                        chunk = ""
                        for ch in w:
                            test_c = chunk + ch
                            c_len = measure_text(test_c, font=font)
                            if c_len <= max_w:
                                chunk = test_c
                            else:
                                if chunk:
                                    lines.append(chunk)
                                chunk = ch
                        if chunk:
                            cur_words = [chunk]
            if cur_words:
                lines.append(" ".join(cur_words))
            return lines

        best_t_lines: list[str] = []
        best_a_lines: list[str] = []
        font_t = None
        font_a = None
        line_h = 9

        for sz in (8, 7, 6):
            f_t = get_font(title, sz, bold=True)
            f_a = get_font(artist, sz, bold=False)
            t_lines = wrap_to_lines(title, f_t, max_w=60)
            a_lines = wrap_to_lines(artist, f_a, max_w=60)
            total_l = len(t_lines) + len(a_lines)
            l_h = 10 if sz == 8 else (9 if sz == 7 else 8)
            t_h = total_l * l_h + (2 if t_lines and a_lines else 0)
            if sz == 8 and total_l <= 2 and t_h <= 24:
                best_t_lines, best_a_lines = t_lines, a_lines
                font_t, font_a, line_h = f_t, f_a, l_h
                break
            elif sz == 7 and t_h <= 50:
                best_t_lines, best_a_lines = t_lines, a_lines
                font_t, font_a, line_h = f_t, f_a, l_h
                break
            elif sz == 6:
                best_t_lines, best_a_lines = t_lines, a_lines
                font_t, font_a, line_h = f_t, f_a, l_h

        gap = 2 if (best_t_lines and best_a_lines) else 0
        total_h = (len(best_t_lines) + len(best_a_lines)) * line_h + gap
        start_y = max(1, int((64 - total_h) // 2))

        scrim_y0 = max(0, start_y - 3)
        scrim_y1 = min(63, start_y + total_h + 3)
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ov_draw = ImageDraw.Draw(overlay)
        for sy in range(scrim_y0, scrim_y1 + 1):
            dist = min(sy - scrim_y0, scrim_y1 - sy)
            alpha = int(145 * min(1.0, dist / 2.5))
            ov_draw.line([(0, sy), (63, sy)], fill=(0, 0, 0, alpha))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        try:
            fc = font_color_hex.lstrip("#")
            rgb_color = tuple(int(fc[i : i + 2], 16) for i in (0, 2, 4))
        except Exception:
            rgb_color = (0, 255, 204)

        lum = 0.299 * rgb_color[0] + 0.587 * rgb_color[1] + 0.114 * rgb_color[2]
        if lum < 90:
            rgb_color = (0, 255, 204)

        def draw_line(raw_line: str, y_pos: int, font, color):
            if not raw_line:
                return
            is_rtl = is_hebrew(raw_line) or is_arabic(raw_line)

            # Check if Pillow has Raqm layout support
            use_raqm = False
            try:
                from PIL import features
                if features.check("raqm") and is_rtl:
                    use_raqm = True
            except Exception:
                use_raqm = False

            if use_raqm:
                try:
                    w = draw.textlength(raw_line, font=font, direction="rtl")
                    x_pos = max(1, int((64 - w) // 2))
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)]:
                        draw.text((x_pos + dx, y_pos + dy), raw_line, font=font, fill=(0, 0, 0), direction="rtl")
                    draw.text((x_pos, y_pos), raw_line, font=font, fill=color, direction="rtl")
                    return
                except Exception:
                    pass

            formatted = format_text(raw_line) if is_rtl else raw_line
            try:
                w = draw.textlength(formatted, font=font)
            except Exception:
                w = len(formatted) * 5
            x_pos = max(1, int((64 - w) // 2))
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)]:
                draw.text((x_pos + dx, y_pos + dy), formatted, font=font, fill=(0, 0, 0))
            draw.text((x_pos, y_pos), formatted, font=font, fill=color)

        cur_y = start_y
        for t_line in best_t_lines:
            draw_line(t_line, cur_y, font_t, (255, 255, 255))
            cur_y += line_h

        if best_t_lines and best_a_lines:
            cur_y += gap

        for a_line in best_a_lines:
            draw_line(a_line, cur_y, font_a, rgb_color)
            cur_y += line_h

        return img

    @staticmethod
    def text_clock_img(
        image: Image.Image,
        img_info: dict,
        media_data: "MediaData",
        config: "Config",
        font_cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont],
    ) -> Image.Image:
        img = image.copy()
        if getattr(config, "special_mode", False):
            return img

        is_burned = getattr(config, "burned", False) or getattr(config, "burned_text", False)
        if is_burned and not getattr(media_data, "playing_tv", False):
            font_color = img_info.get("font_color", getattr(media_data, "font_color", "#FFFFFF"))
            img = ImageFilterService.draw_burned_text(img, media_data, font_color, font_cache)

        if getattr(config, "show_lyrics", False) and len(getattr(media_data, "lyrics", [])) > 0 and not getattr(media_data, "playing_tv", False):
            if getattr(config, "text_bg", False) and not getattr(media_data, "playing_radio", False):
                stat = ImageStat.Stat(img.convert("L"))
                mean_lum = stat.mean[0] if stat.mean else 100.0
                factor = max(0.25, min(0.55, 1.0 - (mean_lum / 220.0)))
                img = ImageEnhance.Brightness(img).enhance(factor)
                img = ImageEnhance.Contrast(img).enhance(0.65)
            return img

        is_top = getattr(config, "overlay_top", True)
        if getattr(config, "cassette_mode", False):
            is_top = False

        y_start, y_end = (2, 9) if is_top else (55, 62)
        align_mode = getattr(config, "overlay_align", "Clock Right, Temp Left")
        show_clk = bool(getattr(config, "show_clock", False))
        show_tmp = bool(getattr(config, "temperature", False))
        has_text_bg = bool(getattr(config, "text_bg", False))

        if show_clk and has_text_bg:
            if align_mode == "Clock Left, Temp Right":
                lpc_clock = (2, y_start, 21, y_end)
            elif align_mode == "Centered" and not show_tmp:
                lpc_clock = (21, y_start, 43, y_end)
            elif align_mode == "Centered":
                lpc_clock = (35, y_start, 62, y_end)
            else:
                lpc_clock = (43, y_start, 62, y_end)

            clock_crop = img.crop(lpc_clock)
            stat = ImageStat.Stat(clock_crop.convert("L"))
            factor = max(0.12, min(0.35, 1.0 - ((stat.mean[0] if stat.mean else 100.0) / 180.0)))
            img.paste(ImageEnhance.Brightness(clock_crop).enhance(factor), lpc_clock)

        if show_tmp and has_text_bg:
            if align_mode == "Clock Left, Temp Right":
                lpc_temp = (47, y_start, 63, y_end)
            elif align_mode == "Centered" and not show_clk:
                lpc_temp = (23, y_start, 40, y_end)
            elif align_mode == "Centered":
                lpc_temp = (2, y_start, 18, y_end)
            else:
                lpc_temp = (2, y_start, 18, y_end)

            temp_crop = img.crop(lpc_temp)
            stat = ImageStat.Stat(temp_crop.convert("L"))
            factor = max(0.12, min(0.35, 1.0 - ((stat.mean[0] if stat.mean else 100.0) / 180.0)))
            img.paste(ImageEnhance.Brightness(temp_crop).enhance(factor), lpc_temp)

        if getattr(config, "text_bg", False) and getattr(config, "show_text", False) and not getattr(media_data, "playing_tv", False) and not is_burned and not getattr(config, "cassette_mode", False):
            lpc = (0, 0, 64, 16) if getattr(config, "top_text", False) else (0, 48, 64, 64)
            lower_part_img = img.crop(lpc)
            stat = ImageStat.Stat(lower_part_img.convert("L"))
            mean_lum = stat.mean[0] if stat.mean else 100.0
            factor = max(0.1, min(0.35, 1.0 - (mean_lum / 180.0)))
            img.paste(ImageEnhance.Brightness(lower_part_img).enhance(factor), lpc)

        return img
