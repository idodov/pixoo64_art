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
    def crop_image_borders(cls, img: Image.Image, config: "Config", radio_logo: bool = False) -> Image.Image:
        if getattr(config, "force_ai", False) or str(getattr(config, "display_mode", "")).lower() == "force ai":
            return img
        crop_mode = getattr(config, "crop_mode", "No Crop")
        if crop_mode == "No Crop" or not getattr(config, "crop_borders", False):
            return img
        if (crop_mode == "Extra Crop" or getattr(config, "crop_extra", False) or getattr(config, "special_mode", False)) and not getattr(config, "vinyl_mode", False):
            return cls._perform_extra_subject_crop(img)
        return cls._perform_standard_crop(img)

    @classmethod
    def apply(cls, img: Image.Image, crop_mode: str = "Crop", sensitivity: bool = False) -> Image.Image:
        crop_lower = str(crop_mode).lower().strip()
        if not crop_mode or crop_lower in ("no", "no crop", "false", "none", "off"):
            return img
        if crop_lower in ("extra", "extra crop", "aggressive crop") or sensitivity:
            return cls._perform_extra_subject_crop(img)
        return cls._perform_standard_crop(img)

    @classmethod
    def _get_border_reference(cls, proxy: Image.Image, depth: int = 2) -> Tuple[Tuple[int, int, int], float]:
        """Finds the dominant outer border color and its uniformity ratio."""
        pw, ph = proxy.size
        pixels = proxy.load()
        samples = []
        top_limit = min(depth, ph)
        bot_start = max(top_limit, ph - depth)
        left_limit = min(depth, pw)
        right_start = max(left_limit, pw - depth)

        for y in range(top_limit):
            for x in range(pw):
                samples.append(pixels[x, y])
        for y in range(bot_start, ph):
            for x in range(pw):
                samples.append(pixels[x, y])
        for y in range(top_limit, bot_start):
            for x in range(left_limit):
                samples.append(pixels[x, y])
            for x in range(right_start, pw):
                samples.append(pixels[x, y])

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
        comp_pixels = comp.get('pixels') or []
        if not comp_pixels:
            return None
        buckets = Counter(
            (pixels[x, y][0] >> 4, pixels[x, y][1] >> 4, pixels[x, y][2] >> 4) for x, y in comp_pixels
        )
        if not buckets:
            return None
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
                min_x = max_x = x
                min_y = max_y = y
                while q:
                    cx, cy = q.popleft()
                    c_pix.append((cx, cy))
                    if cx < min_x:
                        min_x = cx
                    elif cx > max_x:
                        max_x = cx
                    if cy < min_y:
                        min_y = cy
                    elif cy > max_y:
                        max_y = cy
                    for ny in range(max(0, cy - 2), min(ph, cy + 3)):
                        for nx in range(max(0, cx - 2), min(pw, cx + 3)):
                            if (nx, ny) in inner_mask_set and (nx, ny) not in visited:
                                visited.add((nx, ny))
                                q.append((nx, ny))

                area = len(c_pix)
                if area >= int((pw * ph) * 0.004):
                    color_buckets = len(
                        {(pixels[px, py][0] >> 4, pixels[px, py][1] >> 4, pixels[px, py][2] >> 4) for px, py in c_pix}
                    )
                    inner_comps.append({
                        'area': area,
                        'min_x': min_x, 'max_x': max_x,
                        'min_y': min_y, 'max_y': max_y,
                        'w': max_x - min_x + 1, 'h': max_y - min_y + 1,
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
    def _find_subject_box(cls, comps: list, pw: int, ph: int, is_unwrapped: bool = False) -> Optional[Tuple[int, int, int, int, float]]:
        """Filters out marginal typography/stripes and selects the core subject bounding box."""
        if not comps:
            return None
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
        if not pool:
            return None

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
        bg_ref: Tuple[int, int, int] = (0, 0, 0),
        raw_rgb: Optional[bytes] = None,
    ) -> Tuple[float, float]:
        """Finds the (rel_cx, rel_cy) focal center [0.0..1.0] of visual complexity and facial/head saliency within the subject box."""
        sub_w = max_x - min_x + 1
        sub_h = max_y - min_y + 1
        rel_cx, rel_cy = 0.5, 0.5

        if sub_w < 8 or sub_h < 8:
            return rel_cx, rel_cy

        pw, ph = proxy.size
        if raw_rgb is None:
            raw_rgb = proxy.tobytes()
        br, bg, bb = bg_ref
        row_stride = pw * 3

        # Sliding window focal scan (2D) using O(1) integral images and 4x4 cell color bitmasks
        win_dim = max(24, min(int(max(sub_w, sub_h) * 0.58), min(sub_w, sub_h, pw, ph)))
        x_max = max(min_x, max_x - win_dim + 1)
        y_max = max(min_y, max_y - win_dim + 1)
        x_step = max(1, (x_max - min_x) // 16) if x_max > min_x else 1
        y_step = max(1, (y_max - min_y) // 16) if y_max > min_y else 1

        candidates_x = list(range(min_x, x_max + 1, x_step))
        if x_max not in candidates_x:
            candidates_x.append(x_max)
        candidates_y = list(range(min_y, y_max + 1, y_step))
        if y_max not in candidates_y:
            candidates_y.append(y_max)

        iw = sub_w + 1
        table_len = (sub_h + 1) * iw
        sat_edge = [0] * table_len
        sat_contrast = [0] * table_len
        sat_skin = [0] * table_len

        cw = (sub_w + 3) >> 2
        ch = (sub_h + 3) >> 2
        cell_masks = [0] * (cw * ch)

        for ry in range(sub_h):
            py = min_y + ry
            row_base = py * row_stride
            next_row_base = row_base + row_stride
            has_py_next = (py + 1) < ph
            prev_sat_row = ry * iw
            curr_sat_row = (ry + 1) * iw
            cell_row = (ry >> 2) * cw

            run_edge = 0
            run_contrast = 0
            run_skin = 0

            for rx in range(sub_w):
                px = min_x + rx
                off = row_base + px * 3
                r = raw_rgb[off]
                g = raw_rgb[off + 1]
                b = raw_rgb[off + 2]

                cell_masks[cell_row + (rx >> 2)] |= 1 << (((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4))

                d_r = r - br if r >= br else br - r
                d_g = g - bg if g >= bg else bg - g
                d_b = b - bb if b >= bb else bb - b
                diff_bg = d_r if (d_r >= d_g and d_r >= d_b) else (d_g if d_g >= d_b else d_b)

                if diff_bg > 18:
                    run_contrast += 1
                    if ((r > g > b) and (r - b > 14) and (r > 85)) or (diff_bg > 20 and r < 85 and g < 85 and b < 85):
                        run_skin += 1

                edge_px = 0
                if px + 1 < pw:
                    r2 = raw_rgb[off + 3]
                    g2 = raw_rgb[off + 4]
                    b2 = raw_rgb[off + 5]
                    edge_px += (r - r2 if r >= r2 else r2 - r) + (g - g2 if g >= g2 else g2 - g) + (b - b2 if b >= b2 else b2 - b)
                if has_py_next:
                    off_n = next_row_base + px * 3
                    r3 = raw_rgb[off_n]
                    g3 = raw_rgb[off_n + 1]
                    b3 = raw_rgb[off_n + 2]
                    edge_px += (r - r3 if r >= r3 else r3 - r) + (g - g3 if g >= g3 else g3 - g) + (b - b3 if b >= b3 else b3 - b)
                run_edge += edge_px

                c_idx = curr_sat_row + rx + 1
                p_idx = prev_sat_row + rx + 1
                sat_edge[c_idx] = sat_edge[p_idx] + run_edge
                sat_contrast[c_idx] = sat_contrast[p_idx] + run_contrast
                sat_skin[c_idx] = sat_skin[p_idx] + run_skin

        # Pre-combine horizontal cell spans for each candidate x_s across each cell row
        cand_rx_spans = []
        for x_s in candidates_x:
            rx0 = x_s - min_x
            rx1 = rx0 + win_dim
            cx0 = rx0 >> 2
            cx1 = (rx1 - 1) >> 2
            row_spans = [0] * ch
            for cy_i in range(ch):
                base_c = cy_i * cw
                m = 0
                for cx_i in range(cx0, cx1 + 1):
                    m |= cell_masks[base_c + cx_i]
                row_spans[cy_i] = m
            cand_rx_spans.append((x_s, rx0, rx1, row_spans))

        best_score = -1e9
        best_x, best_y = min_x, min_y
        inv_area = 1.0 / float(max(1, win_dim * win_dim))
        denom_y = float(max(1, sub_h - win_dim))
        denom_x = float(max(1, sub_w - win_dim))

        for y_s in candidates_y:
            ry0 = y_s - min_y
            ry1 = ry0 + win_dim
            cy0 = ry0 >> 2
            cy1 = (ry1 - 1) >> 2
            r0_iw = ry0 * iw
            r1_iw = ry1 * iw
            rel_y = ry0 / denom_y if sub_h > win_dim else 0.5
            # Anatomical top-bias: face/head is naturally situated in the upper portion of a human figure
            top_bias = 1.0 / (1.0 + rel_y * 1.5)

            for x_s, rx0, rx1, row_spans in cand_rx_spans:
                tl, tr, bl, br_i = r0_iw + rx0, r0_iw + rx1, r1_iw + rx0, r1_iw + rx1
                edge_energy = sat_edge[br_i] - sat_edge[tr] - sat_edge[bl] + sat_edge[tl]
                contrast_hits = sat_contrast[br_i] - sat_contrast[tr] - sat_contrast[bl] + sat_contrast[tl]
                skin_hair_hits = sat_skin[br_i] - sat_skin[tr] - sat_skin[bl] + sat_skin[tl]

                win_mask = 0
                for cy_i in range(cy0, cy1 + 1):
                    win_mask |= row_spans[cy_i]

                avg_edge = edge_energy * inv_area
                variety = win_mask.bit_count()
                contrast_ratio = contrast_hits * inv_area
                skin_ratio = skin_hair_hits * inv_area
                rel_x = rx0 / denom_x if sub_w > win_dim else 0.5
                x_center_bias = 1.0 / (1.0 + abs(rel_x - 0.5) * 0.7)

                score = (
                    (avg_edge ** 0.75)
                    * (variety ** 0.85)
                    * (1.0 + skin_ratio * 3.5)
                    * (0.2 if contrast_ratio < 0.12 else 1.0)
                    * top_bias
                    * x_center_bias
                )

                if score > best_score:
                    best_score = score
                    best_x, best_y = x_s, y_s

        focal_cx_proxy = best_x + (win_dim / 2.0)
        focal_cy_proxy = best_y + (win_dim / 2.0)
        rel_cx = max(0.12, min(0.88, (focal_cx_proxy - min_x) / float(sub_w)))
        rel_cy = max(0.12, min(0.88, (focal_cy_proxy - min_y) / float(sub_h)))
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
        raw_diff = max_diff.tobytes()
        raw_rgb = proxy.tobytes()
        total_px = pw * ph
        visited = bytearray(total_px)
        comps = []

        for idx in range(total_px):
            if raw_diff[idx] > thresh and not visited[idx]:
                sx = idx % pw
                sy = idx // pw
                comp_pixels = []
                q = deque([(sx, sy, idx)])
                visited[idx] = 1
                min_x = max_x = sx
                min_y = max_y = sy
                color_mask = 0
                while q:
                    cx, cy, c_idx = q.popleft()
                    comp_pixels.append((cx, cy))
                    if cx < min_x:
                        min_x = cx
                    elif cx > max_x:
                        max_x = cx
                    if cy < min_y:
                        min_y = cy
                    elif cy > max_y:
                        max_y = cy
                    c_off = c_idx * 3
                    cr, cg, cb = raw_rgb[c_off], raw_rgb[c_off + 1], raw_rgb[c_off + 2]
                    color_mask |= 1 << (((cr >> 4) << 8) | ((cg >> 4) << 4) | (cb >> 4))
                    c_min_ch = cr if (cr <= cg and cr <= cb) else (cg if cg <= cb else cb)

                    if cx > 0:
                        n_idx = c_idx - 1
                        if not visited[n_idx] and raw_diff[n_idx] > thresh:
                            n_off = n_idx * 3
                            nr, ng, nb = raw_rgb[n_off], raw_rgb[n_off + 1], raw_rgb[n_off + 2]
                            n_min = nr if (nr <= ng and nr <= nb) else (ng if ng <= nb else nb)
                            if abs(c_min_ch - n_min) <= 110:
                                visited[n_idx] = 1
                                q.append((cx - 1, cy, n_idx))
                    if cx + 1 < pw:
                        n_idx = c_idx + 1
                        if not visited[n_idx] and raw_diff[n_idx] > thresh:
                            n_off = n_idx * 3
                            nr, ng, nb = raw_rgb[n_off], raw_rgb[n_off + 1], raw_rgb[n_off + 2]
                            n_min = nr if (nr <= ng and nr <= nb) else (ng if ng <= nb else nb)
                            if abs(c_min_ch - n_min) <= 110:
                                visited[n_idx] = 1
                                q.append((cx + 1, cy, n_idx))
                    if cy > 0:
                        n_idx = c_idx - pw
                        if not visited[n_idx] and raw_diff[n_idx] > thresh:
                            n_off = n_idx * 3
                            nr, ng, nb = raw_rgb[n_off], raw_rgb[n_off + 1], raw_rgb[n_off + 2]
                            n_min = nr if (nr <= ng and nr <= nb) else (ng if ng <= nb else nb)
                            if abs(c_min_ch - n_min) <= 110:
                                visited[n_idx] = 1
                                q.append((cx, cy - 1, n_idx))
                    if cy + 1 < ph:
                        n_idx = c_idx + pw
                        if not visited[n_idx] and raw_diff[n_idx] > thresh:
                            n_off = n_idx * 3
                            nr, ng, nb = raw_rgb[n_off], raw_rgb[n_off + 1], raw_rgb[n_off + 2]
                            n_min = nr if (nr <= ng and nr <= nb) else (ng if ng <= nb else nb)
                            if abs(c_min_ch - n_min) <= 110:
                                visited[n_idx] = 1
                                q.append((cx, cy + 1, n_idx))

                w, h, area = max_x - min_x + 1, max_y - min_y + 1, len(comp_pixels)
                color_buckets = color_mask.bit_count()
                # Outer frame detection: must touch all 4 canvas borders, be mostly hollow, and have low color diversity
                is_outer_frame = (
                    w > pw * 0.82 and h > ph * 0.82
                    and min_x <= 2 and min_y <= 2 and max_x >= pw - 3 and max_y >= ph - 3
                    and (area / float(w * h)) < 0.15
                    and color_buckets <= 8
                )
                if area >= int(total_px * 0.0025) and not is_outer_frame:
                    comps.append({
                        'area': area,
                        'min_x': min_x, 'max_x': max_x,
                        'min_y': min_y, 'max_y': max_y,
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

        box_res = cls._find_subject_box(
            candidate_comps, pw, ph, is_unwrapped=is_unwrapped
        )
        if not box_res:
            return cls._perform_standard_crop(img)
        sub_min_x, sub_min_y, sub_max_x, sub_max_y, subj_solidity = box_res
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

        is_freeform_silhouette = (subj_solidity < 0.48 or (subj_solidity < 0.55 and sub_h > sub_w * 1.15)) and not is_unwrapped

        rel_cx, rel_cy = cls._find_saliency_focus(
            proxy, sub_min_x, sub_min_y, sub_max_x, sub_max_y, bg_ref=target_bg_color, raw_rgb=raw_rgb
        )
        cx, cy = x1 + sub_w * rel_cx, y1 + sub_h * rel_cy

        if is_freeform_silhouette:
            crop_dim = max(16, min(int(min(sub_w, sub_h) * 1.15), int(max(sub_w, sub_h) * 0.65), min(orig_w, orig_h)))
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
