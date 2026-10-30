"""Smart, fast, and surgical image cropping engine for 64x64 pixel displays."""
import math
from collections import Counter, deque
from typing import TYPE_CHECKING, Optional, Tuple
from PIL import Image, ImageChops

if TYPE_CHECKING:
    from ..models import Config


class ImageCropper:
    """Smart, fast, and surgical image cropping engine for 64x64 pixel displays."""

    @classmethod
    def crop_image_borders(cls, img: Image.Image, config: "Config", radio_logo: bool) -> Image.Image:
        crop_mode = getattr(config, "crop_mode", "No Crop")
        if radio_logo or crop_mode == "No Crop" or not getattr(config, "crop_borders", False):
            return img
        if (crop_mode == "Extra Crop" or getattr(config, "crop_extra", False) or getattr(config, "special_mode", False)) and not getattr(config, "vinyl_mode", False):
            return cls._perform_extra_subject_crop(img)
        return cls._perform_standard_crop(img)

    @classmethod
    def apply(cls, img: Image.Image, crop_mode: str = "Crop", sensitivity: bool = False) -> Image.Image:
        if not crop_mode or crop_mode in ("No", "No Crop", "False"):
            return img
        if crop_mode in ("Extra Crop", "Aggressive Crop") or sensitivity:
            return cls._perform_extra_subject_crop(img)
        return cls._perform_standard_crop(img)

    @classmethod
    def _get_border_reference(cls, proxy: Image.Image, depth: int = 2) -> Tuple[Tuple[int, int, int], float]:
        """Finds the dominant outer border color and its uniformity ratio."""
        pw, ph = proxy.size
        pixels = proxy.load()
        samples = [
            pixels[x, y]
            for y in range(ph)
            for x in range(pw)
            if x < depth or x >= pw - depth or y < depth or y >= ph - depth
        ]
        if not samples:
            return (0, 0, 0), 1.0

        buckets = Counter((r >> 3, g >> 3, b >> 3) for r, g, b in samples)
        top_bucket, _ = buckets.most_common(1)[0]
        matching_archive = [p for p in samples if (p[0] >> 3, p[1] >> 3, p[2] >> 3) == top_bucket]
        mid = len(matching_archive) // 2
        r_med = sorted(p[0] for p in matching_archive)[mid]
        g_med = sorted(p[1] for p in matching_archive)[mid]
        b_med = sorted(p[2] for p in matching_archive)[mid]
        bg_ref = (r_med, g_med, b_med)
        close_count = sum(
            1 for r, g, b in samples if max(abs(r - r_med), abs(g - g_med), abs(b - b_med)) <= 22
        )
        return bg_ref, close_count / float(len(samples))

    @classmethod
    def _perform_standard_crop(cls, img: Image.Image) -> Image.Image:
        orig_w, orig_h = img.size
        if orig_w < 20 or orig_h < 20:
            return img

        scale = 120.0 / float(max(orig_w, orig_h))
        pw, ph = max(10, int(orig_w * scale)), max(10, int(orig_h * scale))
        proxy = img.resize((pw, ph), Image.Resampling.BILINEAR).convert("RGB")
        bg_ref, border_uniformity = cls._get_border_reference(proxy, depth=2)
        if border_uniformity < 0.55:
            return img

        diff_rgb = ImageChops.difference(proxy, Image.new("RGB", (pw, ph), bg_ref))
        r_d, g_d, b_d = diff_rgb.split()
        max_diff = ImageChops.lighter(ImageChops.lighter(r_d, g_d), b_d)
        bbox = max_diff.point(lambda p: 255 if p > 22 else 0).getbbox()
        if not bbox:
            return img

        scale_to_orig = 1.0 / scale
        min_x, min_y = int(round(bbox[0] * scale_to_orig)), int(round(bbox[1] * scale_to_orig))
        max_x, max_y = int(round(bbox[2] * scale_to_orig)), int(round(bbox[3] * scale_to_orig))
        w, h = max_x - min_x, max_y - min_y
        if w >= orig_w * 0.98 and h >= orig_h * 0.98:
            return img

        is_pillarbox = (min_y <= int(orig_h * 0.02) and max_y >= int(orig_h * 0.98)) and (
            min_x > int(orig_w * 0.02) and max_x < int(orig_w * 0.98)
        )
        is_letterbox = (min_x <= int(orig_w * 0.02) and max_x >= int(orig_w * 0.98)) and (
            min_y > int(orig_h * 0.02) and max_y < int(orig_h * 0.98)
        )
        crop_dim = min(w, h) if (is_pillarbox or is_letterbox) else min(max(w, h), min(orig_w, orig_h))
        cx, cy, half = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0, crop_dim / 2.0
        left = int(max(0, min(cx - half, orig_w - crop_dim)))
        top = int(max(0, min(cy - half, orig_h - crop_dim)))
        return img.crop((left, top, left + crop_dim, top + crop_dim))

    @classmethod
    def _inspect_and_unwrap_container(
        cls, comp: dict, proxy: Image.Image, pw: int, ph: int
    ) -> Optional[Tuple[Tuple[int, int, int], list]]:
        """Detects if the dominant component is a graphical stripe or outer container box."""
        is_spanning_stripe = (comp['h'] > ph * 0.72 and comp['w'] < pw * 0.48) or (
            comp['w'] > pw * 0.72 and comp['h'] < ph * 0.48
        )
        is_large_box = comp['area'] > int((pw * ph) * 0.18) and (
            comp['min_x'] <= 3 or comp['min_y'] <= 3 or comp['max_x'] >= pw - 4 or comp['max_y'] >= ph - 4
        )
        if not (is_spanning_stripe or is_large_box):
            return None

        pixels = proxy.load()
        comp_pixels = comp['pixels']
        buckets = Counter(
            (pixels[x, y][0] >> 4, pixels[x, y][1] >> 4, pixels[x, y][2] >> 4) for x, y in comp_pixels
        )
        top_bucket, top_count = buckets.most_common(1)[0]
        if (top_count / float(len(comp_pixels))) < 0.30:
            return None

        matching_colors = [
            pixels[x, y] for x, y in comp_pixels
            if (pixels[x, y][0] >> 4, pixels[x, y][1] >> 4, pixels[x, y][2] >> 4) == top_bucket
        ]
        mid = len(matching_colors) // 2
        r_med = sorted(c[0] for c in matching_colors)[mid]
        g_med = sorted(c[1] for c in matching_colors)[mid]
        b_med = sorted(c[2] for c in matching_colors)[mid]
        container_bg = (r_med, g_med, b_med)

        inner_mask_set = {
            (x, y) for x, y in comp_pixels
            if max(abs(pixels[x, y][0] - r_med), abs(pixels[x, y][1] - g_med), abs(pixels[x, y][2] - b_med)) > 14
        }
        if not inner_mask_set:
            return None

        visited = set()
        inner_comps = []
        for x, y in inner_mask_set:
            if (x, y) not in visited:
                c_pix = []
                q = deque([(x, y)])
                visited.add((x, y))
                while q:
                    cx, cy = q.popleft()
                    c_pix.append((cx, cy))
                    for ny in range(max(0, cy - 2), min(ph, cy + 3)):
                        for nx in range(max(0, cx - 2), min(pw, cx + 3)):
                            if (nx, ny) in inner_mask_set and (nx, ny) not in visited:
                                visited.add((nx, ny))
                                q.append((nx, ny))

                xs, ys = [p[0] for p in c_pix], [p[1] for p in c_pix]
                area = len(c_pix)
                if area >= int((pw * ph) * 0.004):
                    color_buckets = len(
                        {(pixels[px, py][0] >> 4, pixels[px, py][1] >> 4, pixels[px, py][2] >> 4) for px, py in c_pix}
                    )
                    inner_comps.append({
                        'area': area,
                        'min_x': min(xs), 'max_x': max(xs),
                        'min_y': min(ys), 'max_y': max(ys),
                        'w': max(xs) - min(xs) + 1, 'h': max(ys) - min(ys) + 1,
                        'pixels': c_pix,
                        'color_variety': color_buckets,
                    })

        return (container_bg, inner_comps) if inner_comps else None

    @classmethod
    def _tighten_box_inward(
        cls, img: Image.Image, rough_box: Tuple[int, int, int, int], bg_color: Tuple[int, int, int]
    ) -> Tuple[int, int, int, int]:
        """Scans inward from the 4 outer edges of rough_box to peel off background border halos."""
        orig_w, orig_h = img.size
        x1, y1, x2, y2 = max(0, rough_box[0]), max(0, rough_box[1]), min(orig_w, rough_box[2]), min(orig_h, rough_box[3])
        bw, bh = x2 - x1, y2 - y1
        if bw < 12 or bh < 12:
            return x1, y1, x2, y2

        pixels = img.load()
        br, bg, bb = bg_color
        thresh = 28
        max_trim_y, max_trim_x = max(2, int(bh * 0.12)), max(2, int(bw * 0.12))

        def row_active_ratio(y: int, start_x: int, end_x: int) -> float:
            step = max(1, max(1, end_x - start_x) // 40)
            pts = [pixels[x, y] for x in range(start_x, end_x, step)]
            active = sum(1 for r, g, b in pts if max(abs(r - br), abs(g - bg), abs(b - bb)) > thresh)
            return active / float(max(1, len(pts)))

        def col_active_ratio(x: int, start_y: int, end_y: int) -> float:
            step = max(1, max(1, end_y - start_y) // 40)
            pts = [pixels[x, y] for y in range(start_y, end_y, step)]
            active = sum(1 for r, g, b in pts if max(abs(r - br), abs(g - bg), abs(b - bb)) > thresh)
            return active / float(max(1, len(pts)))

        while y1 < y2 - 10 and (y1 - rough_box[1]) < max_trim_y and row_active_ratio(y1, x1, x2) < 0.12:
            y1 += 1
        while y2 > y1 + 10 and (rough_box[3] - y2) < max_trim_y and row_active_ratio(y2 - 1, x1, x2) < 0.12:
            y2 -= 1
        while x1 < x2 - 10 and (x1 - rough_box[0]) < max_trim_x and col_active_ratio(x1, y1, y2) < 0.12:
            x1 += 1
        while x2 > x1 + 10 and (rough_box[2] - x2) < max_trim_x and col_active_ratio(x2 - 1, y1, y2) < 0.12:
            x2 -= 1
        return x1, y1, x2, y2

    @classmethod
    def _find_subject_box(cls, comps: list, pw: int, ph: int, is_unwrapped: bool = False) -> Tuple[int, int, int, int, float]:
        """Filters out marginal typography/stripes and selects the core subject bounding box."""
        filtered = []
        for c in comps:
            min_x, max_x, min_y, max_y = c['min_x'], c['max_x'], c['min_y'], c['max_y']
            w, h, area = c['w'], c['h'], c['area']
            aspect_long = max(w / float(max(1, h)), h / float(max(1, w)))

            if not is_unwrapped:
                if max_x < pw * 0.24 or min_x > pw * 0.76 or max_y < ph * 0.22 or min_y > ph * 0.78:
                    continue
            if aspect_long > 3.2 and area < (pw * ph * 0.16):
                continue
            if h < ph * 0.085 and area < (pw * ph * 0.03):
                continue
            if is_unwrapped and (min_y <= 2 or max_y >= ph - 3) and area < (pw * ph * 0.25):
                continue
            filtered.append(c)

        pool = filtered if filtered else comps

        def comp_score(c: dict) -> float:
            w, h, area = c['w'], c['h'], c['area']
            solidity = area / float(max(1, w * h))
            aspect_sq = min(w, h) / float(max(w, h))
            center_x, center_y = (c['min_x'] + c['max_x']) / 2.0, (c['min_y'] + c['max_y']) / 2.0
            dist = math.hypot(center_x - (pw / 2.0), center_y - (ph / 2.0)) / (pw / 2.0)
            variety_bonus = min(1.8, 0.7 + (c.get('color_variety', 8) / 14.0))
            touches_border = c['min_x'] <= 1 or c['min_y'] <= 1 or c['max_x'] >= pw - 2 or c['max_y'] >= ph - 2
            border_penalty = 0.55 if touches_border else 1.0
            return area * (solidity ** 1.1) * (aspect_sq ** 0.85) * variety_bonus * border_penalty / (1.0 + dist * 0.85)

        scored_comps = sorted(pool, key=comp_score, reverse=True)
        primary = scored_comps[0]
        cur_min_x, cur_max_x = primary['min_x'], primary['max_x']
        cur_min_y, cur_max_y = primary['min_y'], primary['max_y']
        total_area = primary['area']

        for other in scored_comps[1:]:
            if other['area'] < primary['area'] * 0.12:
                continue
            dx = max(0, max(cur_min_x - other['max_x'], other['min_x'] - cur_max_x))
            dy = max(0, max(cur_min_y - other['max_y'], other['min_y'] - cur_max_y))
            if max(dx, dy) <= 4:
                new_min_x, new_max_x = min(cur_min_x, other['min_x']), max(cur_max_x, other['max_x'])
                new_min_y, new_max_y = min(cur_min_y, other['min_y']), max(cur_max_y, other['max_y'])
                new_w, new_h = new_max_x - new_min_x + 1, new_max_y - new_min_y + 1
                if (min(new_w, new_h) / float(max(new_w, new_h))) >= 0.55:
                    cur_min_x, cur_max_x, cur_min_y, cur_max_y = new_min_x, new_max_x, new_min_y, new_max_y
                    total_area += other['area']

        final_w, final_h = cur_max_x - cur_min_x + 1, cur_max_y - cur_min_y + 1
        final_solidity = min(1.0, total_area / float(max(1, final_w * final_h)))
        return cur_min_x, cur_min_y, cur_max_x, cur_max_y, final_solidity

    @classmethod
    def _find_saliency_focus(
        cls,
        proxy: Image.Image,
        min_x: int,
        min_y: int,
        max_x: int,
        max_y: int,
    ) -> Tuple[float, float]:
        """Finds the (rel_cx, rel_cy) focal center [0.0..1.0] of visual complexity within the subject box."""
        sub_w = max_x - min_x + 1
        sub_h = max_y - min_y + 1
        rel_cx, rel_cy = 0.5, 0.5

        if sub_w < 8 or sub_h < 8:
            return rel_cx, rel_cy

        pixels = proxy.load()
        pw, ph = proxy.size

        # 1. Vertical focus scan when subject is vertically elongated (e.g. portraits, standing figures)
        if sub_h > int(sub_w * 1.15):
            win_h = min(sub_w, sub_h)
            max_y_start = max_y - win_h + 1
            if max_y_start > min_y:
                y_range = max_y_start - min_y
                step = max(1, y_range // 16)
                candidates = list(range(min_y, max_y_start + 1, step))
                if max_y_start not in candidates:
                    candidates.append(max_y_start)

                best_score = -1.0
                best_y_start = min_y
                x_step = max(1, sub_w // 20)
                y_step = max(1, win_h // 20)

                for y_s in candidates:
                    edge_energy = 0
                    color_buckets = set()
                    sample_count = 0

                    for py in range(y_s, y_s + win_h, y_step):
                        for px in range(min_x, max_x + 1, x_step):
                            r, g, b = pixels[px, py]
                            color_buckets.add((r >> 4, g >> 4, b >> 4))
                            sample_count += 1
                            if px + 1 < pw:
                                r2, g2, b2 = pixels[px + 1, py]
                                edge_energy += abs(r - r2) + abs(g - g2) + abs(b - b2)
                            if py + 1 < ph:
                                r3, g3, b3 = pixels[px, py + 1]
                                edge_energy += abs(r - r3) + abs(g - g3) + abs(b - b3)

                    avg_edge = edge_energy / float(max(1, sample_count))
                    variety = len(color_buckets)
                    rel_pos = (y_s - min_y) / float(max(1, max_y_start - min_y))
                    # Anatomical top-bias: face/head is naturally in the upper region of human figures
                    top_bias = 1.0 / (1.0 + rel_pos * 1.15)
                    score = (avg_edge ** 0.8) * (variety ** 0.9) * top_bias

                    if score > best_score:
                        best_score = score
                        best_y_start = y_s

                focal_cy_proxy = best_y_start + (win_h / 2.0)
                rel_cy = max(0.15, min(0.85, (focal_cy_proxy - min_y) / float(sub_h)))

        # 2. Horizontal focus scan when subject is horizontally elongated
        elif sub_w > int(sub_h * 1.25):
            win_w = min(sub_w, sub_h)
            max_x_start = max_x - win_w + 1
            if max_x_start > min_x:
                x_range = max_x_start - min_x
                step = max(1, x_range // 16)
                candidates = list(range(min_x, max_x_start + 1, step))
                if max_x_start not in candidates:
                    candidates.append(max_x_start)

                best_score = -1.0
                best_x_start = min_x
                x_step = max(1, win_w // 20)
                y_step = max(1, sub_h // 20)

                for x_s in candidates:
                    edge_energy = 0
                    color_buckets = set()
                    sample_count = 0

                    for py in range(min_y, max_y + 1, y_step):
                        for px in range(x_s, x_s + win_w, x_step):
                            r, g, b = pixels[px, py]
                            color_buckets.add((r >> 4, g >> 4, b >> 4))
                            sample_count += 1
                            if px + 1 < pw:
                                r2, g2, b2 = pixels[px + 1, py]
                                edge_energy += abs(r - r2) + abs(g - g2) + abs(b - b2)
                            if py + 1 < ph:
                                r3, g3, b3 = pixels[px, py + 1]
                                edge_energy += abs(r - r3) + abs(g - g3) + abs(b - b3)

                    avg_edge = edge_energy / float(max(1, sample_count))
                    variety = len(color_buckets)
                    rel_pos = (x_s - min_x) / float(max(1, max_x_start - min_x))
                    center_bias = 1.0 / (1.0 + abs(rel_pos - 0.5) * 0.8)
                    score = (avg_edge ** 0.8) * (variety ** 0.9) * center_bias

                    if score > best_score:
                        best_score = score
                        best_x_start = x_s

                focal_cx_proxy = best_x_start + (win_w / 2.0)
                rel_cx = max(0.15, min(0.85, (focal_cx_proxy - min_x) / float(sub_w)))

        return rel_cx, rel_cy

    @classmethod
    def _perform_extra_subject_crop(cls, img: Image.Image) -> Image.Image:
        orig_w, orig_h = img.size
        if orig_w < 20 or orig_h < 20:
            return img

        scale = 120.0 / float(max(orig_w, orig_h))
        pw, ph = max(10, int(orig_w * scale)), max(10, int(orig_h * scale))
        proxy = img.resize((pw, ph), Image.Resampling.BILINEAR).convert("RGB")
        bg_ref, border_uniformity = cls._get_border_reference(proxy, depth=3)

        diff_rgb = ImageChops.difference(proxy, Image.new("RGB", (pw, ph), bg_ref))
        r_d, g_d, b_d = diff_rgb.split()
        max_diff = ImageChops.lighter(ImageChops.lighter(r_d, g_d), b_d)

        thresh = 16 if border_uniformity > 0.75 else 24
        diff_pixels = max_diff.load()
        proxy_pixels = proxy.load()
        visited = [[False] * pw for _ in range(ph)]
        comps = []

        for y in range(ph):
            for x in range(pw):
                if diff_pixels[x, y] > thresh and not visited[y][x]:
                    comp_pixels = []
                    q = deque([(x, y)])
                    visited[y][x] = True
                    while q:
                        cx, cy = q.popleft()
                        comp_pixels.append((cx, cy))
                        c_min_ch = min(proxy_pixels[cx, cy])
                        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                            nx, ny = cx + dx, cy + dy
                            if 0 <= nx < pw and 0 <= ny < ph and not visited[ny][nx] and diff_pixels[nx, ny] > thresh:
                                if abs(c_min_ch - min(proxy_pixels[nx, ny])) > 110:
                                    continue
                                visited[ny][nx] = True
                                q.append((nx, ny))

                    xs, ys = [p[0] for p in comp_pixels], [p[1] for p in comp_pixels]
                    w, h, area = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1, len(comp_pixels)
                    is_outer_frame = w > pw * 0.78 and h > ph * 0.78 and (area / float(w * h)) < 0.25
                    if area >= int((pw * ph) * 0.0025) and not is_outer_frame:
                        color_buckets = len({
                            (proxy_pixels[px, py][0] >> 4, proxy_pixels[px, py][1] >> 4, proxy_pixels[px, py][2] >> 4)
                            for px, py in comp_pixels
                        })
                        comps.append({
                            'area': area,
                            'min_x': min(xs), 'max_x': max(xs),
                            'min_y': min(ys), 'max_y': max(ys),
                            'w': w, 'h': h,
                            'pixels': comp_pixels,
                            'color_variety': color_buckets,
                        })

        if not comps:
            return cls._perform_standard_crop(img)

        comps.sort(key=lambda c: c['area'], reverse=True)
        container_result = cls._inspect_and_unwrap_container(comps[0], proxy, pw, ph)
        if container_result:
            target_bg_color, candidate_comps, is_unwrapped = container_result[0], container_result[1], True
        else:
            target_bg_color, candidate_comps, is_unwrapped = bg_ref, comps, False

        if not is_unwrapped and comps[0]['area'] <= int((pw * ph) * 0.045):
            top_c = comps[0]
            top_cx, top_cy = (top_c['min_x'] + top_c['max_x']) / 2.0, (top_c['min_y'] + top_c['max_y']) / 2.0
            top_dist = math.hypot(top_cx - pw / 2.0, top_cy - ph / 2.0) / (pw / 2.0)
            is_central_photo_inset = top_dist < 0.22 and top_c.get('color_variety', 0) >= 6 and top_c['w'] >= 6 and top_c['h'] >= 6
            if not is_central_photo_inset:
                central_letters = [
                    c for c in candidate_comps
                    if c['min_x'] > pw * 0.15 and c['max_x'] < pw * 0.85 and c['min_y'] > ph * 0.15 and c['max_y'] < ph * 0.85
                ]
                if central_letters:
                    sub_min_x, sub_max_x = min(c['min_x'] for c in central_letters), max(c['max_x'] for c in central_letters)
                    sub_min_y, sub_max_y = min(c['min_y'] for c in central_letters), max(c['max_y'] for c in central_letters)
                    scale_to_orig = 1.0 / scale
                    orig_sub_w = (sub_max_x - sub_min_x + 1) * scale_to_orig
                    orig_sub_h = (sub_max_y - sub_min_y + 1) * scale_to_orig
                    cx, cy = ((sub_min_x + sub_max_x) / 2.0) * scale_to_orig, ((sub_min_y + sub_max_y) / 2.0) * scale_to_orig
                    crop_dim = max(16, min(int(max(orig_sub_w, orig_sub_h) * 1.35), min(orig_w, orig_h)))
                    half = crop_dim / 2.0
                    left, top = int(max(0, min(cx - half, orig_w - crop_dim))), int(max(0, min(cy - half, orig_h - crop_dim)))
                    return img.crop((left, top, left + crop_dim, top + crop_dim))

        sub_min_x, sub_min_y, sub_max_x, sub_max_y, subj_solidity = cls._find_subject_box(
            candidate_comps, pw, ph, is_unwrapped=is_unwrapped
        )
        scale_to_orig = 1.0 / scale
        rough_box = (
            int(round(sub_min_x * scale_to_orig)),
            int(round(sub_min_y * scale_to_orig)),
            int(round((sub_max_x + 1) * scale_to_orig)),
            int(round((sub_max_y + 1) * scale_to_orig)),
        )
        x1, y1, x2, y2 = cls._tighten_box_inward(img, rough_box, target_bg_color)
        sub_w, sub_h = x2 - x1, y2 - y1
        if sub_w < 12 or sub_h < 12:
            return cls._perform_standard_crop(img)

        touches_canvas_edge = sub_min_x <= 2 or sub_min_y <= 2 or sub_max_x >= pw - 3 or sub_max_y >= ph - 3
        is_freeform_silhouette = subj_solidity < 0.52 and not is_unwrapped and not touches_canvas_edge

        rel_cx, rel_cy = cls._find_saliency_focus(proxy, sub_min_x, sub_min_y, sub_max_x, sub_max_y)
        cx, cy = x1 + sub_w * rel_cx, y1 + sub_h * rel_cy

        if is_freeform_silhouette:
            if sub_h > sub_w * 1.3:
                crop_dim = max(16, min(int(sub_w * 1.35), min(orig_w, orig_h, sub_h)))
            else:
                crop_dim = min(max(sub_w, sub_h), min(orig_w, orig_h))
            half = crop_dim / 2.0
            left = int(max(0, min(cx - half, orig_w - crop_dim)))
            top = int(max(0, min(cy - half, orig_h - crop_dim)))
        else:
            crop_dim = min(sub_w, sub_h)
            inset = max(1, int(crop_dim * 0.025))
            crop_dim = max(10, crop_dim - (inset * 2))
            half = crop_dim / 2.0
            left = int(max(x1 + inset, min(cx - half, x2 - inset - crop_dim)))
            top = int(max(y1 + inset, min(cy - half, y2 - inset - crop_dim)))

        return img.crop((left, top, left + crop_dim, top + crop_dim))
