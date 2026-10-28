"""Smooth spinning vinyl turntable animation renderer (16 or 32 frames)."""
import logging
import math
from typing import TYPE_CHECKING, List
from PIL import Image, ImageDraw

if TYPE_CHECKING:
    from ..image.processor import ImageProcessor
    from ..models import MediaData

_LOGGER = logging.getLogger(__name__)


class VinylRenderer:
    """Generates a smooth spinning vinyl turntable animation
    with 16 frames (standard) or 32 frames (Extra Crop) for ultimate smoothness."""

    @classmethod
    def render_frames(cls, base_img: Image.Image, image_processor: "ImageProcessor", media_data: "MediaData") -> List[str]:
        frames_b64 = []
        pil_frames = []
        try:
            crop_mode = getattr(image_processor.config, 'crop_mode', None)
            if not crop_mode:
                if getattr(image_processor.config, 'crop_extra', False):
                    crop_mode = "Extra Crop"
                elif getattr(image_processor.config, 'crop_borders', False):
                    crop_mode = "Crop"
                else:
                    crop_mode = "No Crop"

            total_frames = 32 if crop_mode == "Extra Crop" else 16
            filter_mode = getattr(image_processor.config, 'image_filter', 'None')
            filtered_base = image_processor.filter_service.apply_post_scale(base_img.copy(), filter_mode)

            if crop_mode == "Extra Crop":
                cx, cy, record_radius = 32, 32, 32
                deck_bg, show_arm, sheen_r1, sheen_r2 = (8, 8, 10), False, 30, 21
                art_full = filtered_base.resize((64, 64), Image.Resampling.BILINEAR)
                disc_mask = Image.new("L", (64, 64), 0)
                ImageDraw.Draw(disc_mask).ellipse([0, 0, 63, 63], fill=255)
                groove_overlay = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                g_draw = ImageDraw.Draw(groove_overlay)
                g_draw.ellipse([0, 0, 63, 63], outline=(0, 0, 0, 70), width=1)
                for r in [28, 24, 20, 16, 12]:
                    g_draw.ellipse([32 - r, 32 - r, 32 + r, 32 + r], outline=(0, 0, 0, 45), width=1)
                g_draw.ellipse([25, 25, 39, 39], outline=(0, 0, 0, 60), width=1)
            elif crop_mode == "Crop":
                cx, cy, record_radius, label_diam = 32, 32, 29, 26
                deck_bg, show_arm = (14, 14, 16), False
                grooves, sheen_r1, sheen_r2 = [28, 26, 24, 22, 20, 18, 16, 14], 27, 18
                center_crop = filtered_base.resize((label_diam, label_diam), Image.Resampling.BILINEAR)
                label_mask = Image.new("L", (label_diam, label_diam), 0)
                ImageDraw.Draw(label_mask).ellipse([0, 0, label_diam - 1, label_diam - 1], fill=255)
            else:
                cx, cy, record_radius, label_diam = 30, 32, 27, 24
                deck_bg, show_arm = (14, 14, 16), True
                grooves, sheen_r1, sheen_r2 = [26, 24, 22, 20, 18, 16, 14], 25, 19
                center_crop = filtered_base.resize((label_diam, label_diam), Image.Resampling.BILINEAR)
                label_mask = Image.new("L", (label_diam, label_diam), 0)
                ImageDraw.Draw(label_mask).ellipse([0, 0, label_diam - 1, label_diam - 1], fill=255)

            track_num = getattr(media_data, 'track_number', 1) or 1
            queue_total = getattr(media_data, 'queue_total', 0) or 0
            if queue_total > 1:
                progress = max(0.0, min(1.0, (track_num - 1) / max(1, queue_total - 1)))
                side_index = min(4, max(0, int(progress * 5)))
            else:
                side_index = 0

            base_needle_x = 51 - (side_index * 2)
            base_needle_y = 31 + int(round(side_index * 0.5))

            for i in range(total_frames):
                angle = i * (360.0 / total_frames)
                canvas = Image.new("RGB", (64, 64), deck_bg)
                sheen_wobble = math.sin(i * 2.0 * math.pi / total_frames) * 6.0

                if crop_mode == "Extra Crop":
                    rotated_art = art_full.rotate(-angle, resample=Image.Resampling.BILINEAR).convert("RGBA")
                    rotated_art.alpha_composite(groove_overlay)
                    sheen_layer = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                    s_draw = ImageDraw.Draw(sheen_layer)
                    sheen_alpha_main = int(85 + math.sin(i * math.pi / (total_frames / 2.0)) * 25)
                    sheen_alpha_sub = int(45 + math.sin(i * math.pi / (total_frames / 2.0)) * 15)
                    color_main, color_sub = (255, 255, 255, sheen_alpha_main), (230, 240, 255, sheen_alpha_sub)
                    s_draw.arc([cx - sheen_r1, cy - sheen_r1, cx + sheen_r1, cy + sheen_r1], int(118 + sheen_wobble), int(152 + sheen_wobble), fill=color_main, width=2)
                    s_draw.arc([cx - sheen_r1, cy - sheen_r1, cx + sheen_r1, cy + sheen_r1], int(298 + sheen_wobble), int(332 + sheen_wobble), fill=color_main, width=2)
                    s_draw.arc([cx - sheen_r2, cy - sheen_r2, cx + sheen_r2, cy + sheen_r2], int(124 - sheen_wobble), int(146 - sheen_wobble), fill=color_sub, width=2)
                    s_draw.arc([cx - sheen_r2, cy - sheen_r2, cx + sheen_r2, cy + sheen_r2], int(304 - sheen_wobble), int(326 - sheen_wobble), fill=color_sub, width=2)
                    rotated_art.alpha_composite(sheen_layer)
                    canvas.paste(rotated_art.convert("RGB"), (0, 0), disc_mask)
                else:
                    draw = ImageDraw.Draw(canvas)
                    draw.ellipse([cx - record_radius - 1, cy - record_radius - 1, cx + record_radius + 1, cy + record_radius + 1], fill=(28, 28, 32))
                    draw.ellipse([cx - record_radius, cy - record_radius, cx + record_radius, cy + record_radius], fill=(16, 16, 18))
                    for r in grooves:
                        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(25, 25, 28), width=1)
                    rotated_label = center_crop.rotate(-angle, resample=Image.Resampling.BILINEAR)
                    canvas.paste(rotated_label, (cx - (label_diam // 2), cy - (label_diam // 2)), label_mask)
                    sheen_brightness = int(50 + math.sin(i * math.pi / (total_frames / 2.0)) * 12)
                    sheen_color_main = (sheen_brightness, sheen_brightness, sheen_brightness + 8)
                    sheen_color_sub = (sheen_brightness - 12, sheen_brightness - 12, sheen_brightness - 6)
                    draw.arc([cx - sheen_r1, cy - sheen_r1, cx + sheen_r1, cy + sheen_r1], int(118 + sheen_wobble), int(152 + sheen_wobble), fill=sheen_color_main, width=2)
                    draw.arc([cx - sheen_r1, cy - sheen_r1, cx + sheen_r1, cy + sheen_r1], int(298 + sheen_wobble), int(332 + sheen_wobble), fill=sheen_color_main, width=2)
                    draw.arc([cx - sheen_r2, cy - sheen_r2, cx + sheen_r2, cy + sheen_r2], int(124 - sheen_wobble), int(146 - sheen_wobble), fill=sheen_color_sub, width=2)
                    draw.arc([cx - sheen_r2, cy - sheen_r2, cx + sheen_r2, cy + sheen_r2], int(304 - sheen_wobble), int(326 - sheen_wobble), fill=sheen_color_sub, width=2)

                draw = ImageDraw.Draw(canvas)
                draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(10, 10, 12), outline=(180, 180, 190))

                if show_arm:
                    arm_wobble_x = int(round(math.sin(i * 2.0 * math.pi / total_frames) * 0.6))
                    arm_wobble_y = int(round(math.cos(i * 2.0 * math.pi / total_frames) * 0.4))
                    needle_x, needle_y = base_needle_x + arm_wobble_x, base_needle_y + arm_wobble_y
                    draw.ellipse([55, 6, 61, 12], fill=(80, 80, 90), outline=(160, 160, 170))
                    draw.point((58, 9), fill=(220, 220, 230))
                    joint_x = int(round(54 - (side_index * 1.0))) + (arm_wobble_x // 2)
                    joint_y = int(round(20 + (side_index * 0.8)))
                    draw.line([(57, 11), (joint_x, joint_y)], fill=(170, 170, 180), width=1)
                    draw.line([(joint_x, joint_y), (needle_x + 1, needle_y - 1)], fill=(190, 190, 200), width=1)
                    draw.rectangle([needle_x - 1, needle_y - 2, needle_x + 2, needle_y + 2], fill=(210, 210, 220))
                    draw.point((needle_x, needle_y + 1), fill=(235, 45, 45))

                canvas = image_processor.text_clock_img(canvas, {}, media_data)
                pil_frames.append(canvas.copy())
                b64 = image_processor.gbase64(canvas)
                if b64:
                    frames_b64.append(b64)

            if pil_frames:
                speed_ms = 70 if len(pil_frames) > 16 else 140
                v_key = f"vinyl_{media_data.artist}_{media_data.title}_{crop_mode}"
                media_data.live_display_url = image_processor.save_live_display_gif(pil_frames, speed_ms, v_key)
        except Exception as e:
            _LOGGER.error("Error generating enhanced vinyl animation frames: %s", e)
        return frames_b64
