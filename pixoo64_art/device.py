"""Hardware communication driver for Divoom Pixoo64 HTTP API."""
import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Optional

import aiohttp

if TYPE_CHECKING:
    from .models import Config

_LOGGER = logging.getLogger(__name__)


class PixooDevice:
    """Manages HTTP post commands, deduplication, retry logic, and hardware status queries."""

    def __init__(self, config: "Config", session: aiohttp.ClientSession):
        self.config = config
        self.session = session
        self.select_index: Optional[int] = None
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Connection": "keep-alive",
            "User-Agent": "PixooClient/1.0",
        }
        self._last_payload_str: Optional[str] = None
        self._last_send_time: float = 0.0
        self._send_lock = asyncio.Lock()

    async def send_command(self, payload_command: dict, retries: int = 3, force: bool = False) -> bool:
        if self.session.closed or not self.config.pixoo_url:
            return False

        async with self._send_lock:
            try:
                current_payload_str = json.dumps(payload_command, sort_keys=True)
                now = time.monotonic()
                if not force and (current_payload_str == self._last_payload_str) and (now - self._last_send_time < 0.5):
                    return True
                self._last_payload_str = current_payload_str
                self._last_send_time = now
            except Exception:
                pass

            for attempt in range(1, retries + 1):
                try:
                    async with self.session.post(
                        self.config.pixoo_url, headers=self.headers, json=payload_command, timeout=5
                    ) as response:
                        if response.status == 200:
                            try:
                                data = await response.json(content_type=None)
                                if isinstance(data, dict) and data.get("error_code", 0) != 0:
                                    _LOGGER.warning("Pixoo rejected %s: %s", payload_command.get("Command"), data)
                            except Exception:
                                pass
                            await asyncio.sleep(0.08)
                            return True
                except Exception as ex:
                    _LOGGER.debug("Pixoo send_command error (%s): %s", payload_command.get("Command"), ex)
                    if attempt < retries:
                        await asyncio.sleep(0.15 * attempt)
            return False

    async def get_current_channel_index(self) -> Optional[int]:
        if self.session.closed or not self.config.pixoo_url:
            return None
        try:
            async with self.session.post(
                self.config.pixoo_url,
                headers=self.headers,
                json={"Command": "Channel/GetIndex"},
                timeout=4,
            ) as response:
                if response.status == 200:
                    response_data = await response.json(content_type=None)
                    if isinstance(response_data, dict) and "SelectIndex" in response_data:
                        return int(response_data["SelectIndex"])
        except Exception as e:
            _LOGGER.debug("Failed to get current channel index: %s", e)
        return None

    async def get_all_conf(self) -> dict:
        if self.session.closed or not self.config.pixoo_url:
            return {}
        try:
            async with self.session.post(
                self.config.pixoo_url,
                headers=self.headers,
                json={"Command": "Channel/GetAllConf"},
                timeout=4,
            ) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    if isinstance(data, dict):
                        return data
        except Exception as e:
            _LOGGER.debug("Failed to fetch device config: %s", e)
        return {}

    async def get_screen_on_state(self) -> bool:
        conf = await self.get_all_conf()
        if conf and "LightSwitch" in conf:
            return conf.get("LightSwitch", 1) == 1
        return True
