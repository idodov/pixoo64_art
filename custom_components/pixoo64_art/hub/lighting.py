"""Ambient lighting controller and background queue/track prefetch mixin for PixooHub."""
import asyncio
import logging
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple
from homeassistant.helpers.event import async_call_later
from ..models import MediaData

if TYPE_CHECKING:
    import aiohttp
    from homeassistant.core import HomeAssistant
    from ..models import Config

_LOGGER = logging.getLogger(__name__)


class AmbientLightingController:
    """Controls synchronized Home Assistant light entities and WLED LED strips."""

    def __init__(self, hass: "HomeAssistant", websession: "aiohttp.ClientSession", config: "Config") -> None:
        self.hass, self.websession, self.config = hass, websession, config

    async def control_light(self, action: str, rgb_color: Optional[tuple] = None, is_night: bool = True) -> None:
        if not is_night and getattr(self.config, "only_at_night", False):
            return
        raw_entities = getattr(self.config, "light_entity", [])
        if not raw_entities:
            return
        entities: List[str] = []
        if isinstance(raw_entities, str):
            entities = [e.strip() for e in raw_entities.split(",") if e.strip()]
        elif isinstance(raw_entities, (list, tuple, set)):
            for item in raw_entities:
                if isinstance(item, str):
                    for sub in item.split(","):
                        if sub.strip():
                            entities.append(sub.strip())
        else:
            entities = [str(raw_entities).strip()]

        if not entities:
            return

        service_data = {"entity_id": entities}
        if action == "on" and rgb_color:
            r, g, b = int(rgb_color[0]), int(rgb_color[1]), int(rgb_color[2])
            service_data["rgb_color"] = [255, 255, 255] if (r == 0 and g == 0 and b == 0) else [r, g, b]
            service_data["transition"] = 1

        try:
            await self.hass.services.async_call("light", f"turn_{action}", service_data, blocking=True)
        except Exception as e:
            _LOGGER.debug("Batch light control error, trying individually: %s", e)
            for entity_id in entities:
                indiv_data = {"entity_id": entity_id}
                if action == "on" and rgb_color:
                    indiv_data["rgb_color"] = service_data["rgb_color"]
                    indiv_data["transition"] = 1
                try:
                    await self.hass.services.async_call("light", f"turn_{action}", indiv_data, blocking=True)
                except Exception as ind_err:
                    _LOGGER.error("Failed to control light %s (%s): %s", entity_id, action, ind_err)

        if action == "off":
            pending_retry = [
                eid for eid in entities
                if not self.hass.states.get(eid) or self.hass.states.get(eid).state in ("unavailable", "unknown")
            ]
            if pending_retry:
                async def _retry_off(_now=None):
                    for eid in pending_retry:
                        try:
                            st = self.hass.states.get(eid)
                            if st and st.state not in ("unavailable", "unknown", "off"):
                                await self.hass.services.async_call("light", "turn_off", {"entity_id": eid}, blocking=True)
                        except Exception as err:
                            _LOGGER.debug("Retry turn_off failed for %s: %s", eid, err)

                async_call_later(self.hass, 5.0, _retry_off)
                async_call_later(self.hass, 12.0, _retry_off)

    async def control_wled_light(self, action: str, colors: Optional[list] = None, is_night: bool = True) -> None:
        if not is_night and getattr(self.config, "only_at_night", False):
            return
        wled_ip = getattr(self.config, "wled_ip", None)
        if not wled_ip:
            return
        payload: dict = {"on": (action == "on")}
        if action == "on" and colors:
            clean_colors = [c.lstrip("#") for c in colors if c]
            if clean_colors:
                payload["bri"] = getattr(self.config, "brightness", 255)
                payload["seg"] = [{"fx": getattr(self.config, "effect", 38), "col": clean_colors}]
        try:
            async with self.websession.post(f"http://{wled_ip}/json/state", json=payload, timeout=5) as resp:
                resp.raise_for_status()
        except Exception as e:
            _LOGGER.debug("Failed to control WLED at %s (%s): %s", wled_ip, action, e)


class HubPrefetchMixin:
    """Mixin for PixooHub managing next-track prefetching, early frame delivery, and playlist window caching."""

    def _schedule_prefetch(self) -> None:
        self._cleanup_timers(["_prefetch_timer_unsub"])
        if not self.media_data or getattr(self.media_data, "media_duration", 0) <= 0:
            return
        is_anim_mode = any(getattr(self.config, k, False) for k in ("spotify_slide", "artist_slide", "vinyl_mode", "cassette_mode", "force_ai"))
        prefetch_offset = 25.0 if is_anim_mode else 10.0
        delay = (float(self.media_data.media_duration) - self._get_current_media_position()) - prefetch_offset
        if delay > 0:
            self._prefetch_timer_unsub = async_call_later(self.hass, delay, self._execute_prefetch)
        elif delay > -prefetch_offset:
            self.hass.async_create_task(self._execute_prefetch_task())

    async def _execute_prefetch(self, now=None) -> None:
        self._prefetch_timer_unsub = None
        await self._execute_prefetch_task()

    async def _execute_prefetch_task(self) -> None:
        try:
            self.prefetch_status = "Querying Next Song..."
            self._update_prefetch_sensor_state()
            next_info = await self._get_next_song_info()
            if next_info:
                artist, title_clean, album, url, title_original, duration = next_info
                if artist and title_clean:
                    self.prefetch_next_artist, self.prefetch_next_title = artist, title_clean
                    if getattr(self.config, "show_lyrics", False):
                        self.prefetch_status = "Downloading Art & Lyrics..."
                        self.hass.async_create_task(self.media_data.lyrics_provider.prefetch_lyrics(artist, title_original, duration))
                    else:
                        self.prefetch_status = "Downloading Art..."
                    if getattr(self.config, "spotify_slide", False) or getattr(self.config, "artist_slide", False):
                        self.spotify_slider_status, self.spotify_slider_artist = f"Prefetching for {artist}...", artist
                    self._update_prefetch_sensor_state()
                    dummy = MediaData(self.hass, self.config, self.image_processor, self.websession)
                    dummy.artist, dummy.title, dummy.title_original, dummy.album, dummy.picture = artist, title_clean, title_original, album, url
                    dummy.queue_total = getattr(self.media_data, "queue_total", 0)
                    dummy.track_number = getattr(self.media_data, "track_number", 1) + 1
                    self._cancel_tasks(["_prefetch_task"])
                    self._prefetch_task = self.hass.async_create_task(self._run_prefetch_and_update_status(url, dummy))
                    return
            self.prefetch_status, self.prefetch_next_artist, self.prefetch_next_title = "No next song detected", None, None
            if (getattr(self.config, "spotify_slide", False) or getattr(self.config, "artist_slide", False)) and self.spotify_slider_status not in ["Active Live", "Slider Sent Early"]:
                self.spotify_slider_status = "No next queue detected"
            self._update_prefetch_sensor_state()
        except Exception as e:
            self.prefetch_status = f"Prefetch error: {e}"
            self._update_prefetch_sensor_state()

    async def _run_prefetch_and_update_status(self, url: str, dummy_media: MediaData) -> None:
        try:
            proc_img = await self.fallback_service.get_final_url(url, dummy_media) or await self.hass.async_add_executor_job(self.fallback_service._get_fallback_black_image_data, dummy_media)
            dummy_media.processed_data = proc_img
            self.prefetch_status = "Ready in RAM"

            is_slider = getattr(self.config, "spotify_slide", False)
            is_artist_slider = getattr(self.config, "artist_slide", False)
            is_vinyl = getattr(self.config, "vinyl_mode", False)
            is_cassette = getattr(self.config, "cassette_mode", False)

            if is_slider and not getattr(dummy_media, "radio_logo", False):
                await self.spotify_service.prepare_slider_for_media(dummy_media)
                if getattr(self.config, "special_mode_spotify_slider", False):
                    await self.spotify_service.spotify_album_art_animation(None, dummy_media, self.select_index)
                else:
                    await self.spotify_service.spotify_albums_slide(None, dummy_media, self.select_index, send_to_device=False)
                frames = getattr(dummy_media, "slider_frames", 0)
                self.spotify_slider_frames = frames
                self.spotify_slider_status = f"Ready in RAM ({frames} frames)" if frames >= 2 else f"Prefetch: {dummy_media.slider_error or 'No albums found'}"
                if frames >= 2:
                    self.prefetch_status = f"Slider Ready ({frames} frames)"
            elif is_artist_slider and not getattr(dummy_media, "radio_logo", False):
                await self.fallback_service.play_artist_gallery_slide(None, dummy_media, send_to_device=False)
                frames = getattr(dummy_media, "slider_frames", 0)
                self.spotify_slider_frames = frames
                self.spotify_slider_status = f"Ready in RAM ({frames} artist frames)" if frames >= 2 else f"Prefetch: {dummy_media.slider_error or 'No artist images found'}"
                if frames >= 2:
                    self.prefetch_status = f"Gallery Ready ({frames} frames)"
            elif is_vinyl and not getattr(dummy_media, "radio_logo", False) and proc_img and "pil_image" in proc_img:
                dummy_media.vinyl_frames_b64 = await self.hass.async_add_executor_job(self.image_processor.generate_vinyl_frames, proc_img["pil_image"], dummy_media)
                if dummy_media.vinyl_frames_b64:
                    self.prefetch_status = f"Vinyl Ready ({len(dummy_media.vinyl_frames_b64)} frames)"
            elif is_cassette and not getattr(dummy_media, "radio_logo", False) and proc_img and "pil_image" in proc_img:
                dummy_media.cassette_frames_b64 = await self.hass.async_add_executor_job(self.image_processor.generate_cassette_frames, proc_img["pil_image"], dummy_media)
                if dummy_media.cassette_frames_b64:
                    self.prefetch_status = f"Cassette Ready ({len(dummy_media.cassette_frames_b64)} frames)"

            self._prefetched_media = dummy_media
            self._update_prefetch_sensor_state()

            if (is_slider or is_artist_slider or is_vinyl or is_cassette) and not getattr(dummy_media, "radio_logo", False):
                has_frames = (
                    (len(getattr(dummy_media, "slider_frames_b64", [])) >= 2) if (is_slider or is_artist_slider)
                    else bool(dummy_media.vinyl_frames_b64) if is_vinyl else bool(dummy_media.cassette_frames_b64)
                )
                if has_frames:
                    pos = self._get_current_media_position()
                    dur = float(self.media_data.media_duration)
                    early_offset = 10 if is_vinyl else (3 if is_cassette else 5)
                    time_to_early = (dur - pos) - early_offset

                    async def _trigger_early(now=None):
                        self._early_send_timer_unsub = None
                        self._cancel_tasks(["_early_send_task"])
                        if getattr(self.config, "spotify_slide", False) or getattr(self.config, "artist_slide", False):
                            self._early_send_task = self.hass.async_create_task(self._do_early_slider_send(dummy_media))
                        elif getattr(self.config, "vinyl_mode", False):
                            self._early_send_task = self.hass.async_create_task(self._do_early_vinyl_send(dummy_media))
                        elif getattr(self.config, "cassette_mode", False):
                            self._early_send_task = self.hass.async_create_task(self._do_early_cassette_send(dummy_media))

                    if time_to_early > 0:
                        self._cleanup_timers(["_early_send_timer_unsub"])
                        self._early_send_timer_unsub = async_call_later(self.hass, time_to_early, _trigger_early)
                    elif time_to_early > -early_offset:
                        await _trigger_early()
        except asyncio.CancelledError:
            self.prefetch_status = "Cancelled"
            self.spotify_slider_status = "Prefetch Cancelled"
            self._update_prefetch_sensor_state()
        except Exception as e:
            self.prefetch_status = f"Failed: {e}"
            self.spotify_slider_status = f"Prefetch Error: {e}"
            self.spotify_slider_last_error = str(e)
            self._update_prefetch_sensor_state()

    async def _do_early_slider_send(self, dummy_media: MediaData) -> None:
        if not dummy_media:
            return
        self._is_processing_image = True
        self.prefetch_status = "Sending Slider Early..."
        self.spotify_slider_status = "Sending Early Slider to Pixoo..."
        self._update_prefetch_sensor_state()
        self._early_slider_sent_for = f"slider_{dummy_media.artist}_{dummy_media.title}".strip().lower()
        try:
            if getattr(self.config, "artist_slide", False):
                await self.fallback_service.play_artist_gallery_slide(self.pixoo_device, dummy_media, send_to_device=True)
                pass_flag = getattr(dummy_media, "artist_slide_pass", False)
            else:
                if getattr(self.config, "special_mode_spotify_slider", False):
                    await self.spotify_service.spotify_album_art_animation(self.pixoo_device, dummy_media, self.select_index)
                else:
                    await self.spotify_service.spotify_albums_slide(self.pixoo_device, dummy_media, self.select_index, send_to_device=True)
                pass_flag = getattr(dummy_media, "spotify_slide_pass", False)
            if pass_flag:
                self.prefetch_status = "Slider Sent Early"
                self.spotify_slider_status = f"Slider Sent Early ({dummy_media.slider_frames} frames)"
                self.spotify_slider_frames = dummy_media.slider_frames
                self.spotify_slider_artist = dummy_media.artist
            else:
                self.prefetch_status = "Early Slider Failed"
                self.spotify_slider_status = f"Early Slider Failed: {dummy_media.slider_error or 'Unknown'}"
                self.spotify_slider_last_error = dummy_media.slider_error
        except Exception as e:
            self.prefetch_status = f"Early Slider Error: {e}"
            self.spotify_slider_last_error = str(e)
        finally:
            self._is_processing_image = False
            self._update_prefetch_sensor_state()

    async def _do_early_vinyl_send(self, dummy_media: MediaData) -> None:
        if dummy_media and dummy_media.vinyl_frames_b64:
            await self._send_early_frames(
                dummy_media.vinyl_frames_b64,
                70 if len(dummy_media.vinyl_frames_b64) > 16 else 140,
                f"vinyl_{dummy_media.artist}_{dummy_media.title}".strip().lower(),
                "Vinyl",
            )

    async def _do_early_cassette_send(self, dummy_media: MediaData) -> None:
        if dummy_media and dummy_media.cassette_frames_b64:
            await self._send_early_frames(
                dummy_media.cassette_frames_b64, 100, f"cassette_{dummy_media.artist}_{dummy_media.title}".strip().lower(), "Cassette"
            )

    async def _send_early_frames(self, frames: list[str], speed: int, tag: str, label: str) -> None:
        self._is_processing_image = True
        self.prefetch_status = f"Sending Early {label}..."
        self._update_prefetch_sensor_state()
        self._early_slider_sent_for = tag
        try:
            await self.pixoo_device.send_command({"Command": "Channel/OnOffScreen", "OnOff": 1}, force=True)
            await self.pixoo_device.send_command({"Command": "Channel/SetIndex", "SelectIndex": 4}, force=True)
            await self.pixoo_device.send_command({"Command": "Draw/ResetHttpGifId"}, force=True)
            await asyncio.sleep(0.05)
            for offset, b64_frame in enumerate(frames):
                await self.pixoo_device.send_command({
                    "Command": "Draw/SendHttpGif", "PicNum": len(frames), "PicWidth": 64, "PicOffset": offset, "PicID": 0, "PicSpeed": speed, "PicData": b64_frame
                })
            self.prefetch_status = f"{label} Sent Early"
            if len(frames) > 1:
                self._is_animation_active = True
        except Exception as e:
            self.prefetch_status = f"Early {label} Error: {e}"
        finally:
            self._is_processing_image = False
            self._update_prefetch_sensor_state()

    async def _fetch_player_queue(self) -> Tuple[List[Dict], Optional[int]]:
        state = self.hass.states.get(self.media_player)
        if not state:
            return [], None
        attrs = state.attributes
        queue = attrs.get("queue") or attrs.get("queue_items") or attrs.get("media_queue") or attrs.get("tracks") or attrs.get("playlist") or []
        queue_pos = attrs.get("queue_position") or attrs.get("queue_index") or attrs.get("media_track")
        if not queue and self.hass.services.has_service("sonos", "get_queue"):
            try:
                resp = await self.hass.services.async_call("sonos", "get_queue", {"entity_id": self.media_player}, blocking=True, return_response=True)
                if resp and self.media_player in resp:
                    queue = resp[self.media_player]
            except Exception as e:
                _LOGGER.debug("Failed to fetch Sonos queue: %s", e)
        if not isinstance(queue, list) or not queue:
            return [], None
        curr_title = (self.media_data.title or "").strip().lower()
        curr_artist = (self.media_data.artist or "").strip().lower()
        if curr_title:
            for idx, item in enumerate(queue):
                if isinstance(item, dict):
                    t = str(item.get("title") or item.get("name") or item.get("media_title") or "").strip().lower()
                    a = str(item.get("artist") or item.get("media_artist") or "").strip().lower()
                    if (curr_title in t or t in curr_title) and (not curr_artist or curr_artist in a or a in curr_artist):
                        return queue, idx
        if isinstance(queue_pos, int) and 0 <= queue_pos - 1 < len(queue):
            return queue, queue_pos - 1
        return queue, 0

    async def _get_next_song_info(self) -> Optional[Tuple[str, str, str, str, str, int]]:
        queue, current_idx = await self._fetch_player_queue()
        if queue and current_idx is not None and 0 <= current_idx + 1 < len(queue):
            nxt = queue[current_idx + 1]
            if isinstance(nxt, dict):
                artist = nxt.get("artist") or nxt.get("media_artist")
                title = nxt.get("title") or nxt.get("name") or nxt.get("media_title")
                album = nxt.get("album") or nxt.get("media_album_name") or ""
                url = nxt.get("image") or nxt.get("entity_picture")
                duration = nxt.get("duration") or nxt.get("media_duration") or 0
                if artist and title:
                    cleaned = self.media_data.clean_title(title) if getattr(self.config, "clean_title", True) else title
                    return str(artist), str(cleaned), str(album), url, str(title), int(duration)
        return None

    async def _run_playlist_prefetch(self) -> None:
        pref_setting = str(getattr(self.config, "playlist_prefetch_range", "Disabled") or "Disabled")
        if "disabled" in pref_setting.lower():
            self.playlist_prefetch_status = "Disabled in settings"
            self._update_prefetch_sensor_state()
            return
        if getattr(self.config, "spotify_slide", False) or getattr(self.config, "artist_slide", False):
            self.playlist_prefetch_status = "Disabled (Slider active)"
            self._update_prefetch_sensor_state()
            return
        range_val = 5 if "5" in pref_setting else 10
        queue, queue_pos = await self._fetch_player_queue()
        if not queue or queue_pos is None:
            self.playlist_prefetch_status, self.playlist_queue_total, self.playlist_queue_position, self.playlist_cached_count, self.playlist_window_range = "No queue detected", 0, None, 0, "None"
            self._update_prefetch_sensor_state()
            return
        self.playlist_queue_total, self.playlist_queue_position = len(queue), queue_pos + 1
        start_idx, end_idx = max(0, queue_pos - range_val), min(len(queue), queue_pos + range_val + 1)
        self.playlist_window_range = f"Tracks {start_idx + 1} to {end_idx}"
        target_items = [(i, queue[i]) for i in range(start_idx, end_idx) if i != queue_pos]
        cached_count, total_target = 0, len(target_items)
        self.playlist_prefetch_status = f"Scanning {total_target} tracks in window..."
        self._update_prefetch_sensor_state()

        clean_flag = getattr(self.config, "clean_title", True)
        f_mode, c_mode = getattr(self.config, "image_filter", "None"), getattr(self.config, "crop_mode", "No Crop")
        for _, item in target_items:
            if not isinstance(item, dict):
                continue
            artist = item.get("artist") or item.get("media_artist")
            title = item.get("title") or item.get("name") or item.get("media_title")
            album = item.get("album") or item.get("media_album_name") or ""
            url = item.get("image") or item.get("entity_picture")
            if not artist or not title:
                continue
            clean_t = str(self.media_data.clean_title(title) if clean_flag else title)
            clean_a = str(artist)
            mem_tag = f"master_{clean_a}_{clean_t}_{f_mode}_{c_mode}"
            if mem_tag in self.image_processor.image_cache:
                cached_count += 1
                self.playlist_cached_count = cached_count
                continue
            dummy_media = MediaData(self.hass, self.config, self.image_processor, self.websession)
            dummy_media.is_prefetch = True
            dummy_media.artist, dummy_media.title, dummy_media.album, dummy_media.picture = clean_a, clean_t, str(album), url
            try:
                if await self.fallback_service.get_final_url(url, dummy_media):
                    cached_count += 1
            except Exception:
                pass
            self.playlist_cached_count = cached_count
            self.playlist_prefetch_status = f"Caching... ({cached_count}/{total_target} ready)"
            self._update_prefetch_sensor_state()
            await asyncio.sleep(0.4)
        self.playlist_prefetch_status = f"Ready ({cached_count}/{total_target} cached in window)"
        self._update_prefetch_sensor_state()

    async def safe_state_change_callback(self, event) -> None:
        self._cancel_tasks(["debounce_task"])
        self.debounce_task = asyncio.create_task(self._run_debounced_callback(event))

    async def _run_debounced_callback(self, event) -> None:
        try:
            await asyncio.sleep(0.25)
            await self._handle_media_change(event)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _LOGGER.error("Error in state change callback: %s", e)

    async def force_update(self) -> None:
        self._apply_logic_matrix()
        if not self.ui_state.get("master_control", True):
            await self._send_off_command()
            return
        state = self.hass.states.get(self.media_player)
        if state and self._is_player_active(state):
            self._pause_timed_out = False
            self._stop_lyrics_scheduler()
            self._stop_clock_scheduler()
            self._cleanup_timers()
            self._cancel_tasks(["current_task", "_playlist_prefetch_task", "_early_send_task", "_lyrics_bg_task"])
            self._is_processing_image = False
            await self.media_data.update(state)
            if not self.media_data.title and not getattr(self.media_data, "playing_tv", False):
                await self._send_off_command()
                return
            self._fetch_external_temperature()
            queue, current_idx = await self._fetch_player_queue()
            if queue:
                self.media_data.queue_total = len(queue)
                self.chart_controller.inspect_queue_for_album_session({"queue": queue}, self.media_data.artist, self.media_data.title, self.media_data.album or "")
            if current_idx is not None:
                self.media_data.track_number = current_idx + 1
            self._active_song_key, self.media_data.track_changed = None, True
            self.current_task = self.hass.async_create_task(self._process_and_send())
            self._playlist_prefetch_task = self.hass.async_create_task(self._run_playlist_prefetch())
        else:
            await self._send_off_command()
