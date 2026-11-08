"""Hardware communication driver for Divoom Pixoo64 HTTP API."""
import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Optional

import aiohttp

from .const import DEFAULT_PIXOO_ENDPOINTS

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
        self._last_completed_send_time: float = 0.0
        self._send_lock = asyncio.Lock()
        self._frame_seq: int = 0
        self._endpoint: Optional[str] = None
        self._base_url: Optional[str] = None
        self._probe_lock = asyncio.Lock()
        self._discovered: bool = False

    @property
    def is_busy(self) -> bool:
        """True while a command is in flight or queued on the device lock."""
        return self._send_lock.locked()

    @property
    def host(self) -> Optional[str]:
        """Clean host/IP of the Pixoo device."""
        raw = getattr(self.config, "pixoo_ip", None) or getattr(self.config, "pixoo_url", None)
        if not raw:
            return None
        s = str(raw).strip()
        if "://" in s:
            s = s.split("://", 1)[1]
        s = s.split("/", 1)[0]
        if ":" in s:
            s = s.split(":", 1)[0]
        return s.strip() or None

    @property
    def candidate_endpoints(self) -> list[str]:
        """Return candidate URLs to connect to the Pixoo device."""
        h = self.host
        if not h:
            return []
        return [ep.format(host=h) for ep in DEFAULT_PIXOO_ENDPOINTS]

    @property
    def endpoint(self) -> Optional[str]:
        """The active, working Pixoo endpoint URL."""
        if self._endpoint:
            return self._endpoint
        if getattr(self.config, "pixoo_url", None):
            return self.config.pixoo_url
        cands = self.candidate_endpoints
        return cands[0] if cands else None

    @property
    def base_url(self) -> Optional[str]:
        """Alias for endpoint."""
        return self.endpoint

    def _set_active_endpoint(self, url: str) -> None:
        """Store the active endpoint and keep config in sync."""
        self._endpoint = url
        self._base_url = url
        if self.config:
            self.config.pixoo_url = url

    def get_alternate_endpoint(self, current_url: Optional[str] = None) -> Optional[str]:
        """Return the alternative candidate endpoint from the configured list."""
        cands = self.candidate_endpoints
        if len(cands) < 2:
            return None
        cur = current_url or self.endpoint
        for cand in cands:
            if cand != cur:
                return cand
        return None

    async def async_detect_endpoint(self, timeout: float = 2.5) -> Optional[str]:
        """Probe candidate endpoints with Channel/GetAllConf and cache the working URL."""
        if self.session.closed:
            return None

        candidates = self.candidate_endpoints
        if not candidates:
            return self.endpoint

        cur = self._endpoint or getattr(self.config, "pixoo_url", None)
        if cur and cur in candidates:
            candidates = [cur] + [c for c in candidates if c != cur]

        async with self._probe_lock:
            for cand in candidates:
                try:
                    async with self.session.post(
                        cand,
                        headers=self.headers,
                        json={"Command": "Channel/GetAllConf"},
                        timeout=aiohttp.ClientTimeout(total=timeout),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            if isinstance(data, dict):
                                _LOGGER.info("Pixoo endpoint detected: %s", cand)
                                self._set_active_endpoint(cand)
                                self._discovered = True
                                return cand
                except Exception as ex:
                    _LOGGER.debug("Pixoo probe failed for %s: %s", cand, ex)

        fallback = cur or (candidates[0] if candidates else None)
        if fallback:
            self._set_active_endpoint(fallback)
        return fallback

    @staticmethod
    def _is_frame_payload(payload: dict) -> bool:
        if payload.get("Command") == "Draw/SendHttpGif":
            return True
        if payload.get("Command") == "Draw/CommandList":
            return any(c.get("Command") == "Draw/SendHttpGif" for c in payload.get("CommandList", []) if isinstance(c, dict))
        return False

    async def send_command(self, payload_command: dict, retries: int = 2, force: bool = False) -> bool:
        if self.session.closed or not self.endpoint:
            return False

        # Frame sequencing: a newer frame makes older queued/retrying frames stale (dropped instead of sent late)
        is_frame = self._is_frame_payload(payload_command)
        my_seq = 0
        if is_frame:
            self._frame_seq += 1
            my_seq = self._frame_seq

        async with self._send_lock:
            if is_frame and my_seq != self._frame_seq and payload_command.get("Command") == "Draw/CommandList":
                _LOGGER.debug("Pixoo dropping stale frame batch (seq %s < %s)", my_seq, self._frame_seq)
                return False
            try:
                current_payload_str = json.dumps(payload_command)
                now = time.monotonic()
                if not force and (current_payload_str == self._last_payload_str) and (now - self._last_send_time < 0.5):
                    return True
                self._last_payload_str = current_payload_str
                self._last_send_time = now
            except Exception:
                current_payload_str = None

            elapsed = time.monotonic() - self._last_completed_send_time
            if not force and elapsed < 0.025:
                await asyncio.sleep(0.025 - elapsed)

            target_url = self.endpoint
            fallback_attempted = False

            for attempt in range(1, retries + 1):
                if attempt > 1 and is_frame and my_seq != self._frame_seq:
                    _LOGGER.debug("Pixoo abandoning retry of stale frame (seq %s < %s)", my_seq, self._frame_seq)
                    return False
                try:
                    post_kwargs = (
                        {"data": current_payload_str}
                        if current_payload_str is not None
                        else {"json": payload_command}
                    )
                    async with self.session.post(
                        target_url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=3), **post_kwargs
                    ) as response:
                        self._last_completed_send_time = time.monotonic()
                        if response.status == 200:
                            if target_url != self.endpoint:
                                _LOGGER.info("Pixoo switched active endpoint to %s", target_url)
                                self._set_active_endpoint(target_url)
                            try:
                                data = await response.json(content_type=None)
                                if isinstance(data, dict) and data.get("error_code", 0) != 0:
                                    _LOGGER.warning("Pixoo rejected %s: %s", payload_command.get("Command"), data)
                            except Exception:
                                pass
                            return True
                except Exception as ex:
                    _LOGGER.debug("Pixoo send_command error (%s) on %s: %s", payload_command.get("Command"), target_url, ex)
                    if not fallback_attempted:
                        alt = self.get_alternate_endpoint(target_url)
                        if alt:
                            target_url = alt
                            fallback_attempted = True
                            continue
                    if attempt < retries:
                        await asyncio.sleep(0.15 * attempt)
            return False

    async def send_frame_and_text(
        self, frame_command: dict, text_command: Optional[dict] = None, retries: int = 2
    ) -> tuple[bool, bool]:
        """Dispatch a frame CommandList and its HTTP text ItemList back-to-back under a single lock."""
        if self.session.closed or not self.endpoint:
            return False, False

        frame_str = json.dumps(frame_command)
        text_str = json.dumps(text_command) if text_command else None

        self._frame_seq += 1
        my_seq = self._frame_seq

        async with self._send_lock:
            if my_seq != self._frame_seq:
                _LOGGER.debug("Pixoo dropping stale frame+text pair (seq %s < %s)", my_seq, self._frame_seq)
                return False, False

            self._last_payload_str = text_str or frame_str
            self._last_send_time = time.monotonic()

            target_url = self.endpoint
            fallback_attempted = False

            frame_ok = False
            for attempt in range(1, retries + 1):
                if attempt > 1 and my_seq != self._frame_seq:
                    return False, False
                try:
                    async with self.session.post(
                        target_url, headers=self.headers, data=frame_str, timeout=aiohttp.ClientTimeout(total=3)
                    ) as response:
                        self._last_completed_send_time = time.monotonic()
                        if response.status == 200:
                            if target_url != self.endpoint:
                                _LOGGER.info("Pixoo switched active endpoint to %s", target_url)
                                self._set_active_endpoint(target_url)
                            try:
                                data = await response.json(content_type=None)
                                if isinstance(data, dict) and data.get("error_code", 0) != 0:
                                    _LOGGER.warning("Pixoo rejected frame CommandList: %s", data)
                            except Exception:
                                pass
                            frame_ok = True
                            break
                except Exception as ex:
                    _LOGGER.debug("Pixoo send_frame_and_text frame error on %s: %s", target_url, ex)
                    if not fallback_attempted:
                        alt = self.get_alternate_endpoint(target_url)
                        if alt:
                            target_url = alt
                            fallback_attempted = True
                            continue
                    if attempt < retries:
                        await asyncio.sleep(0.10 * attempt)

            if not frame_ok:
                return False, False

            if not text_str:
                return True, True

            # Allow the Pixoo GIF renderer a brief settling window (100ms) before
            # sending the text overlay layer to ensure the text isn't swallowed by
            # the hardware GIF decoder initialization.
            await asyncio.sleep(0.10)

            text_ok = False
            for attempt in range(1, retries + 1):
                if my_seq != self._frame_seq:
                    return True, False
                try:
                    async with self.session.post(
                        target_url, headers=self.headers, data=text_str, timeout=aiohttp.ClientTimeout(total=3)
                    ) as response:
                        now_done = time.monotonic()
                        self._last_completed_send_time = now_done
                        self._last_send_time = now_done
                        if response.status == 200:
                            if target_url != self.endpoint:
                                _LOGGER.info("Pixoo switched active endpoint to %s", target_url)
                                self._set_active_endpoint(target_url)
                            try:
                                data = await response.json(content_type=None)
                                if isinstance(data, dict) and data.get("error_code", 0) != 0:
                                    _LOGGER.warning("Pixoo rejected SendHttpItemList: %s", data)
                            except Exception:
                                pass
                            text_ok = True
                            break
                except Exception as ex:
                    _LOGGER.debug("Pixoo send_frame_and_text text error on %s: %s", target_url, ex)
                    if not fallback_attempted:
                        alt = self.get_alternate_endpoint(target_url)
                        if alt:
                            target_url = alt
                            fallback_attempted = True
                            continue
                    if attempt < retries:
                        await asyncio.sleep(0.08 * attempt)

            return True, text_ok

    async def _locked_query(self, command: str, timeout: float = 3) -> Optional[dict]:
        """Status queries share the send lock so they never collide with an in-flight frame upload."""
        if self.session.closed or not self.endpoint:
            return None
        async with self._send_lock:
            target_url = self.endpoint
            fallback_attempted = False
            for attempt in range(2):
                try:
                    async with self.session.post(
                        target_url,
                        headers=self.headers,
                        json={"Command": command},
                        timeout=aiohttp.ClientTimeout(total=timeout),
                    ) as response:
                        self._last_completed_send_time = time.monotonic()
                        if response.status == 200:
                            if target_url != self.endpoint:
                                _LOGGER.info("Pixoo switched active endpoint to %s", target_url)
                                self._set_active_endpoint(target_url)
                            data = await response.json(content_type=None)
                            if isinstance(data, dict):
                                return data
                except Exception as e:
                    _LOGGER.debug("Pixoo query %s failed on %s: %s", command, target_url, e)
                    if not fallback_attempted:
                        alt = self.get_alternate_endpoint(target_url)
                        if alt:
                            target_url = alt
                            fallback_attempted = True
                            continue
        return None

    async def get_current_channel_index(self) -> Optional[int]:
        response_data = await self._locked_query("Channel/GetIndex")
        if isinstance(response_data, dict) and "SelectIndex" in response_data:
            try:
                return int(response_data["SelectIndex"])
            except (TypeError, ValueError):
                return None
        return None

    async def get_all_conf(self) -> dict:
        return await self._locked_query("Channel/GetAllConf") or {}

    async def get_screen_on_state(self) -> bool:
        conf = await self.get_all_conf()
        if conf and "LightSwitch" in conf:
            return conf.get("LightSwitch", 1) == 1
        return True
