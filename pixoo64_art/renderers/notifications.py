"""Notification manager, queue controller, and full-screen display for Pixoo64."""
import asyncio
import base64
from io import BytesIO
import logging
import os
import re
import textwrap
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageSequence
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..models import get_bidi, has_bidi, is_arabic, prepare_bidi_text
from .notification_icons import NotificationIconRenderer

if TYPE_CHECKING:
    from ..device import PixooDevice
    from ..image.processor import ImageProcessor
    from ..models import Config

_LOGGER = logging.getLogger(__name__)


class LaMetricIconResolver:
    """Asynchronously fetches and caches LaMetric 8x8 pixel icons and multi-frame animations."""

    _mem_cache: Dict[str, Tuple[List[Image.Image], int]] = {}

    @classmethod
    async def async_resolve_icon(
        cls, hass: HomeAssistant, icon_ref: Optional[str]
    ) -> Optional[Tuple[List[Image.Image], int]]:
        """Resolve icon_ref (ID, URL, or data URI) into (frames, speed_ms)."""
        if not icon_ref:
            return None

        icon_ref = str(icon_ref).strip()
        if not icon_ref:
            return None

        # 1. Base64 data URI check
        if icon_ref.startswith("data:image/") and ";base64," in icon_ref:
            try:
                b64_data = icon_ref.split(";base64,")[1]
                raw_bytes = base64.b64decode(b64_data)
                with Image.open(BytesIO(raw_bytes)) as img:
                    return cls._extract_frames_and_speed(img)
            except Exception as e:
                _LOGGER.warning("Failed to decode base64 icon data: %s", e)
                return None

        clean_id = icon_ref.lstrip("#").strip().lower()
        if clean_id in cls._mem_cache:
            return cls._mem_cache[clean_id]

        storage_dir = hass.config.path(".storage", "pixoo64", "lametric_icons")
        os.makedirs(storage_dir, exist_ok=True)
        cached_file = os.path.join(storage_dir, f"{clean_id}.gif")

        # 2. Check persistent disk cache
        if os.path.isfile(cached_file):
            try:
                raw_bytes = await hass.async_add_executor_job(cls._read_file_bytes, cached_file)
                with Image.open(BytesIO(raw_bytes)) as img:
                    parsed = cls._extract_frames_and_speed(img)
                    if len(parsed[0]) > 1 or clean_id.startswith("a"):
                        cls._mem_cache[clean_id] = parsed
                        return parsed
            except Exception:
                pass

        # 3. Determine URLs (prioritizing animated 'a' prefix for numeric IDs)
        if clean_id.startswith("http://") or clean_id.startswith("https://"):
            urls = [clean_id]
        else:
            urls = []
            if clean_id.startswith("a") and len(clean_id) > 1 and clean_id[1:].isdigit():
                urls.append(f"https://developer.lametric.com/content/apps/icon_thumbs/{clean_id}")
                urls.append(f"https://developer.lametric.com/content/apps/icon_thumbs/{clean_id[1:]}")
            elif clean_id.isdigit():
                urls.append(f"https://developer.lametric.com/content/apps/icon_thumbs/a{clean_id}")
                urls.append(f"https://developer.lametric.com/content/apps/icon_thumbs/{clean_id}")
            else:
                urls.append(f"https://developer.lametric.com/content/apps/icon_thumbs/{clean_id}")

        websession = async_get_clientsession(hass)
        for url in urls:
            try:
                async with websession.get(url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        with Image.open(BytesIO(data)) as img:
                            parsed = cls._extract_frames_and_speed(img)
                            cls._mem_cache[clean_id] = parsed
                            await hass.async_add_executor_job(cls._write_file_bytes, cached_file, data)
                            return parsed
            except Exception as e:
                _LOGGER.debug("Could not fetch icon from '%s': %s", url, e)

        return None

    @staticmethod
    def _extract_frames_and_speed(img: Image.Image) -> Tuple[List[Image.Image], int]:
        frames: List[Image.Image] = []
        durations: List[int] = []
        try:
            for frame in ImageSequence.Iterator(img):
                frames.append(frame.copy().convert("RGBA"))
                d = frame.info.get("duration", 0)
                if d and d > 0:
                    durations.append(d)
        except Exception:
            pass
        if not frames:
            frames = [img.convert("RGBA")]

        speed = int(sum(durations) / len(durations)) if durations else 120
        if speed < 40 or speed > 3000:
            speed = 120
        return frames[:30], speed

    @staticmethod
    def _read_file_bytes(path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    @staticmethod
    def _write_file_bytes(path: str, data: bytes) -> None:
        with open(path, "wb") as f:
            f.write(data)


class NotificationManager:
    """Manages full-screen notifications on Pixoo64 with rock-solid hardware display and buzzer alerts."""

    THEMES = {
        # Core & Status
        "info": {"color": (0, 191, 255), "hex": "#00BFFF"},
        "success": {"color": (50, 220, 50), "hex": "#32CD32"},
        "warning": {"color": (255, 170, 0), "hex": "#FFA500"},
        "error": {"color": (255, 50, 50), "hex": "#FF3232"},
        "text": {"color": (255, 255, 255), "hex": "#FFFFFF"},
        "custom": {"color": (0, 229, 255), "hex": "#00E5FF"},
        "v": {"color": (50, 220, 50), "hex": "#32CD32"},
        "x": {"color": (255, 50, 50), "hex": "#FF3232"},
        "cancel": {"color": (255, 50, 50), "hex": "#FF3232"},
        "alert": {"color": (255, 200, 0), "hex": "#FFC800"},
        "alarm": {"color": (255, 40, 40), "hex": "#FF2828"},
        "siren": {"color": (255, 40, 40), "hex": "#FF2828"},
        # Climate & Smart Home
        "boiler": {"color": (255, 100, 40), "hex": "#FF6428"},
        "ac": {"color": (0, 220, 255), "hex": "#00DCFF"},
        "climate": {"color": (0, 220, 255), "hex": "#00DCFF"},
        "snowflake": {"color": (0, 220, 255), "hex": "#00DCFF"},
        "fan": {"color": (0, 180, 255), "hex": "#00B4FF"},
        "light": {"color": (255, 220, 60), "hex": "#FFDC3C"},
        "lamp": {"color": (255, 220, 60), "hex": "#FFDC3C"},
        "bulb": {"color": (255, 220, 60), "hex": "#FFDC3C"},
        "vacuum": {"color": (0, 230, 140), "hex": "#00E68C"},
        "robot_vacuum": {"color": (0, 230, 140), "hex": "#00E68C"},
        "shutter": {"color": (200, 210, 225), "hex": "#C8D2E1"},
        "car": {"color": (0, 170, 255), "hex": "#00AAFF"},
        "door": {"color": (240, 180, 80), "hex": "#F0B450"},
        "garage": {"color": (200, 70, 60), "hex": "#C8463C"},
        "gate": {"color": (200, 70, 60), "hex": "#C8463C"},
        "lock": {"color": (255, 200, 40), "hex": "#FFC828"},
        "washer": {"color": (0, 180, 255), "hex": "#00B4FF"},
        "dryer": {"color": (255, 140, 40), "hex": "#FF8C28"},
        "power": {"color": (255, 220, 0), "hex": "#FFDC00"},
        "plug": {"color": (255, 220, 0), "hex": "#FFDC00"},
        "energy": {"color": (255, 220, 0), "hex": "#FFDC00"},
        # Home Life & Utilities
        "home": {"color": (255, 120, 80), "hex": "#FF7850"},
        "presence": {"color": (255, 120, 80), "hex": "#FF7850"},
        "motion": {"color": (0, 240, 255), "hex": "#00F0FF"},
        "person": {"color": (0, 240, 255), "hex": "#00F0FF"},
        "coffee": {"color": (230, 100, 60), "hex": "#E6643C"},
        "package": {"color": (210, 155, 95), "hex": "#D29B5F"},
        "delivery": {"color": (210, 155, 95), "hex": "#D29B5F"},
        "mail": {"color": (240, 240, 250), "hex": "#F0F0FA"},
        "trash": {"color": (60, 180, 75), "hex": "#3CB44B"},
        "pet": {"color": (255, 170, 90), "hex": "#FFAA5A"},
        "dog": {"color": (255, 170, 90), "hex": "#FFAA5A"},
        "cat": {"color": (255, 170, 90), "hex": "#FFAA5A"},
        "plant": {"color": (60, 220, 90), "hex": "#3CDC5A"},
        "leaf": {"color": (60, 220, 90), "hex": "#3CDC5A"},
        # Environment & Devices
        "fire": {"color": (255, 70, 0), "hex": "#FF4600"},
        "water": {"color": (0, 150, 255), "hex": "#0096FF"},
        "leak": {"color": (0, 150, 255), "hex": "#0096FF"},
        "battery": {"color": (50, 220, 80), "hex": "#32DC50"},
        "wifi": {"color": (0, 230, 255), "hex": "#00E6FF"},
        "weather": {"color": (120, 200, 255), "hex": "#78C8FF"},
        "sun": {"color": (255, 210, 0), "hex": "#FFD200"},
        "moon": {"color": (210, 210, 255), "hex": "#D2D2FF"},
        "sleep": {"color": (170, 150, 240), "hex": "#AA96F0"},
        "music": {"color": (255, 90, 190), "hex": "#FF5ABE"},
        "phone": {"color": (0, 230, 120), "hex": "#00E678"},
        "calendar": {"color": (255, 215, 60), "hex": "#FFD73C"},
        "camera": {"color": (180, 190, 210), "hex": "#B4BED2"},
        "attack": {"color": (255, 40, 40), "hex": "#FF2828"},
        "rocket": {"color": (255, 40, 40), "hex": "#FF2828"},
        "timer": {"color": (240, 245, 255), "hex": "#F0F5FF"},
        "time": {"color": (240, 245, 255), "hex": "#F0F5FF"},
    }

    LAYOUTS = {
        1: {"icon_cy": 25, "text_start_y": 48},
        2: {"icon_cy": 20, "text_start_y": 40},
        3: {"icon_cy": 15, "text_start_y": 30},
        4: {"icon_cy": 12, "text_start_y": 20},
    }

    def __init__(self, config: "Config", pixoo: "PixooDevice", image_processor: "ImageProcessor", hass: HomeAssistant):
        self.config = config
        self.pixoo = pixoo
        self.proc = image_processor
        self.hass = hass
        self.is_active = False
        self._queue: asyncio.Queue = asyncio.Queue()
        self._queue_worker_task: Optional[asyncio.Task] = None

    async def enqueue(self, event_data: dict) -> None:
        """Enqueue a notification to ensure sequential display without clobbering."""
        await self._queue.put(event_data)
        if not self._queue_worker_task or self._queue_worker_task.done():
            self._queue_worker_task = self.hass.async_create_task(self._process_queue())

    async def _process_queue(self) -> None:
        while not self._queue.empty():
            item = await self._queue.get()
            try:
                await self.display(item)
            except Exception as e:
                _LOGGER.error("Error processing notification item: %s", e)
            finally:
                self._queue.task_done()

    async def display(self, event_data: dict) -> None:
        """Display a reliable notification with separated title/message, full duration, and proper BiDi."""
        try:
            self.is_active = True
            raw_msg = str(event_data.get("message", "")).strip()
            raw_title = str(event_data.get("title") or "").strip()
            notif_type = str(event_data.get("type", "text")).strip().lower()
            duration = max(1, min(60, int(event_data.get("duration", 5))))
            custom_color = event_data.get("color")
            icon_ref = event_data.get("icon") or event_data.get("lametric_icon") or event_data.get("icon_id")

            # Support LaMetric model.frames schema
            if "model" in event_data and isinstance(event_data["model"], dict):
                m_frames = event_data["model"].get("frames", [])
                if m_frames and isinstance(m_frames, list) and len(m_frames) > 0:
                    first_f = m_frames[0]
                    if not raw_msg and first_f.get("text"):
                        raw_msg = str(first_f.get("text")).strip()
                    if not icon_ref and first_f.get("icon"):
                        icon_ref = str(first_f.get("icon")).strip()

            # Automatic detection if notif_type looks like a custom icon ID (e.g. "a2710", "28340")
            if not icon_ref and notif_type not in self.THEMES:
                if re.match(r"^a?\d+$", notif_type) or notif_type.startswith("http"):
                    icon_ref = notif_type
                    notif_type = "custom"

            if not raw_msg and not raw_title:
                return

            await self._trigger_buzzer(event_data)

            # Resolve optional custom LaMetric icon
            lametric_frames: List[Image.Image] = []
            lametric_speed: int = 120
            if icon_ref:
                resolved = await LaMetricIconResolver.async_resolve_icon(self.hass, icon_ref)
                if resolved:
                    lametric_frames, lametric_speed = resolved

            theme = self.THEMES.get(notif_type, self.THEMES["info"])
            hex_color = str(custom_color).strip() if custom_color else theme["hex"]
            if not hex_color.startswith("#"):
                hex_color = f"#{hex_color}"
            rgb_color = self._hex_to_rgb(hex_color)

            # Separate Title and Message onto clean lines (no awkward colon concatenation)
            display_lines: List[str] = []
            has_title = False
            if raw_title:
                display_lines.append(raw_title)
                has_title = True
                if raw_msg:
                    wrap_w = 11 if (has_bidi(raw_msg) or is_arabic(raw_msg)) else 12
                    max_msg_lines = 3 if notif_type != "text" else 4
                    display_lines.extend(textwrap.wrap(raw_msg, width=wrap_w)[:max_msg_lines])
            else:
                wrap_w = 11 if (has_bidi(raw_msg) or is_arabic(raw_msg)) else 12
                max_lines = 6 if notif_type == "text" else 4
                display_lines.extend(textwrap.wrap(raw_msg, width=wrap_w)[:max_lines])

            if not display_lines:
                display_lines = [""]

            # Format each line with bidirectional display order unconditionally (prepare_bidi_text handles RTL/Arabic and preserves LTR)
            bidi_lines = [prepare_bidi_text(line) for line in display_lines]

            line_count = max(1, min(4, len(bidi_lines)))
            if notif_type == "text" and not lametric_frames:
                text_start_y = max(2, (64 - (line_count * 10)) // 2)
                icon_cy = 0
            else:
                layout = self.LAYOUTS.get(line_count, self.LAYOUTS[2])
                icon_cy, text_start_y = layout["icon_cy"], layout["text_start_y"]

            # Check if user requested burned text mode (defaults to True)
            raw_burned = event_data.get("burned_text")
            if raw_burned is None:
                use_burned_text = True
            elif isinstance(raw_burned, str):
                use_burned_text = raw_burned.lower() in ("true", "1", "yes", "on")
            else:
                use_burned_text = bool(raw_burned)

            # Generate composite 64x64 frames
            if lametric_frames:
                base_frames = [
                    self._draw_background(notif_type, rgb_color, icon_cy, icon_f)
                    for icon_f in lametric_frames
                ]
                anim_speed = lametric_speed
            else:
                base_frames = [
                    self._draw_background(notif_type, rgb_color, icon_cy, None)
                ]
                anim_speed = 10000

            if use_burned_text:
                # Burned Text Mode: render bold title and message directly onto each frame
                rendered_frames = [
                    self._burn_text_on_image(f.copy(), display_lines, rgb_color, text_start_y, has_title=has_title)
                    for f in base_frames
                ]
            else:
                # Live Pixoo Text Mode: animated background frame only
                rendered_frames = base_frames

            b64_frames = [self.proc.gbase64(f) for f in rendered_frames if f]
            if not b64_frames:
                return

            total_frames = len(b64_frames)

            await self.pixoo.send_command({"Command": "Channel/OnOffScreen", "OnOff": 1}, force=True)
            await self.pixoo.send_command({"Command": "Channel/SetIndex", "SelectIndex": 4}, force=True)
            await self.pixoo.send_command({
                "Command": "Draw/CommandList",
                "CommandList": [
                    {"Command": "Draw/ClearHttpText"},
                    {"Command": "Draw/ResetHttpGifId"},
                ],
            }, force=True)
            await asyncio.sleep(0.04)

            for offset, b64_frame in enumerate(b64_frames):
                await self.pixoo.send_command({
                    "Command": "Draw/SendHttpGif",
                    "PicNum": total_frames,
                    "PicWidth": 64,
                    "PicOffset": offset,
                    "PicID": 0,
                    "PicSpeed": anim_speed,
                    "PicData": b64_frame,
                }, force=True)
                if total_frames > 1 and offset < total_frames - 1:
                    await asyncio.sleep(0.02)

            if not use_burned_text:
                # Allow Pixoo firmware to initialize and start the animation loop before overlaying hardware text
                await asyncio.sleep(0.15 if total_frames > 1 else 0.04)
                text_items = self._create_text_items(bidi_lines, hex_color, text_start_y, has_title=has_title)
                if text_items:
                    await self.pixoo.send_command({"Command": "Draw/SendHttpItemList", "ItemList": text_items}, force=True)

            # Stay visible on screen for exact duration
            await asyncio.sleep(duration)
        except Exception as e:
            _LOGGER.error("Notification display error: %s", e)
        finally:
            self.is_active = False

    def _burn_text_on_image(
        self,
        img: Image.Image,
        lines: List[str],
        color: Tuple[int, int, int],
        start_y: int,
        has_title: bool = False,
    ) -> Image.Image:
        """Render text directly onto the PIL canvas using bundled freeware fonts."""
        draw = ImageDraw.Draw(img)
        comp_dir = os.path.dirname(os.path.dirname(__file__))
        fonts_dir = os.path.join(comp_dir, "fonts")

        def _load_font(text_sample: str, bold: bool = False, size: int = 8) -> Tuple[ImageFont.ImageFont, bool]:
            candidates: List[str] = []
            if is_arabic(text_sample):
                candidates.extend([
                    os.path.join(fonts_dir, "NotoSansArabic-Regular.ttf"),
                    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
                    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
                    "C:\\Windows\\Fonts\\arial.ttf",
                ])
            elif has_bidi(text_sample):
                candidates.extend([
                    os.path.join(fonts_dir, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/TTF/DejaVuSans.ttf",
                    os.path.join(comp_dir, "arial.ttf"),
                    "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
                ])
            else:
                candidates.extend([
                    os.path.join(fonts_dir, "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/TTF/DejaVuSans.ttf",
                    os.path.join(comp_dir, "arial.ttf"),
                    "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
                ])
            for p in candidates:
                if os.path.isfile(p):
                    try:
                        return ImageFont.truetype(p, size), False
                    except Exception:
                        pass
            return ImageFont.load_default(), True

        cur_y = start_y
        for i, line in enumerate(lines):
            if not line:
                continue
            is_title_line = (has_title and i == 0)
            fnt, is_def = _load_font(line, bold=is_title_line, size=8)
            line_color = (255, 255, 255) if is_title_line else color
            is_rtl = has_bidi(line) or is_arabic(line)

            # Check if Pillow has Raqm layout support (e.g. Home Assistant OS / Docker)
            use_raqm = False
            try:
                from PIL import features
                if features.check("raqm") and is_rtl:
                    use_raqm = True
            except Exception:
                use_raqm = False

            if use_raqm:
                try:
                    w = draw.textlength(line, font=fnt, direction="rtl")
                    x = max(1, int((64 - w) // 2))
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        draw.text((x + dx, cur_y + dy), line, font=fnt, fill=(0, 0, 0), direction="rtl")
                    draw.text((x, cur_y), line, font=fnt, fill=line_color, direction="rtl")
                    if is_title_line and is_def:
                        draw.text((x + 1, cur_y), line, font=fnt, fill=line_color, direction="rtl")
                    cur_y += 10
                    continue
                except Exception:
                    pass

            # Fallback when Raqm is unavailable: manually convert to visual order
            v_line = prepare_bidi_text(line) if is_rtl else line
            try:
                w = draw.textlength(v_line, font=fnt)
            except Exception:
                w = len(v_line) * 5.2
            x = max(1, int((64 - w) // 2))

            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                draw.text((x + dx, cur_y + dy), v_line, font=fnt, fill=(0, 0, 0))
            draw.text((x, cur_y), v_line, font=fnt, fill=line_color)
            if is_title_line and is_def:
                draw.text((x + 1, cur_y), v_line, font=fnt, fill=line_color)
            cur_y += 10

        return img

    async def _trigger_buzzer(self, data: dict) -> None:
        if not data.get("play_buzzer", False):
            return
        try:
            await self.pixoo.send_command({
                "Command": "Device/PlayBuzzer",
                "ActiveTimeInCycle": int(data.get("buzzer_active", 500)),
                "OffTimeInCycle": int(data.get("buzzer_off", 500)),
                "PlayTotalTime": int(data.get("buzzer_total", 3000)),
            })
        except Exception as e:
            _LOGGER.warning("Failed to play buzzer: %s", e)

    def _draw_background(
        self,
        n_type: str,
        color: tuple,
        cy: int,
        custom_icon: Optional[Image.Image] = None,
    ) -> Image.Image:
        """Create a 64x64 background canvas with outline border and pixel icon."""
        img = Image.new("RGB", (64, 64), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Rounded frame border
        draw.rectangle([0, 0, 63, 63], outline=color, width=1)
        if n_type == "text" and not custom_icon:
            return img

        if custom_icon:
            # Scale LaMetric icon to 16x16 with crisp nearest-neighbor sampling
            scaled = custom_icon.resize((16, 16), Image.Resampling.NEAREST)
            img.paste(scaled, (24, max(2, cy - 8)), scaled)
        else:
            cx = 32
            NotificationIconRenderer.render_icon(n_type, draw, cx, cy, color, frame_num=0)
        return img

    def _create_text_items(
        self, lines: list, color: str, start_y: int, has_title: bool = False
    ) -> list:
        """Generate Pixoo hardware text items with white header for title and RTL direction."""
        items = []
        line_ids = {25 + i for i in range(len(lines))}
        for tid in [1, 2, 3, 4, 5, 6, 10, 11, 20, 21, 22, 25, 26, 27, 28, 29, 30]:
            if tid not in line_ids:
                items.append({
                    "TextId": tid, "type": 22, "x": 0, "y": 64, "dir": 0, "font": 2,
                    "TextWidth": 64, "Textheight": 16, "speed": 0, "align": 1, "TextString": "", "color": "#000000",
                })
        for i, line in enumerate(lines):
            # Line 0 is white if title is provided; message lines follow in color
            line_color = "#FFFFFF" if (has_title and i == 0) else color
            is_rtl = 1 if (has_bidi(line) or is_arabic(line)) else 0
            items.append({
                "TextId": 25 + i, "type": 22, "x": 0, "y": start_y + (i * 10),
                "dir": is_rtl, "font": 190, "TextWidth": 64, "Textheight": 16,
                "speed": 100, "align": 2, "TextString": line, "color": line_color,
            })
        return items

    @staticmethod
    def _hex_to_rgb(hex_str: str) -> tuple:
        hex_str = hex_str.lstrip('#')
        if len(hex_str) == 3:
            hex_str = ''.join([c * 2 for c in hex_str])
        try:
            return tuple(int(hex_str[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return (255, 255, 255)
