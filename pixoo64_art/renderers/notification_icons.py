"""Master-grade 64x64 pixel-art notification icon renderer for Pixoo64."""
import math
from typing import Callable, Dict
from PIL import ImageDraw


class NotificationIconRenderer:
    """Renders high-detail pixel-art notification icons with depth, shading, and animation."""

    # --- Core Status & Alerts ---

    @staticmethod
    def draw_v(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Vibrant checkmark with drop shadow and bright highlight
        sh = (20, 60, 20)
        draw.line([(cx - 7, cy + 1), (cx - 2, cy + 7), (cx + 8, cy - 5)], fill=sh, width=3)
        draw.line([(cx - 7, cy), (cx - 2, cy + 6), (cx + 8, cy - 6)], fill=(50, 220, 50), width=3)
        draw.line([(cx - 6, cy - 1), (cx - 2, cy + 4), (cx + 7, cy - 6)], fill=(180, 255, 180), width=1)

    @staticmethod
    def draw_x(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # 3D red X with dark drop shadow
        sh = (70, 10, 10)
        draw.line([(cx - 6, cy - 5), (cx + 6, cy + 7)], fill=sh, width=3)
        draw.line([(cx + 6, cy - 5), (cx - 6, cy + 7)], fill=sh, width=3)
        draw.line([(cx - 6, cy - 6), (cx + 6, cy + 6)], fill=(255, 45, 45), width=3)
        draw.line([(cx + 6, cy - 6), (cx - 6, cy + 6)], fill=(255, 45, 45), width=3)
        draw.line([(cx - 5, cy - 5), (cx + 5, cy + 5)], fill=(255, 170, 170), width=1)

    @staticmethod
    def draw_info(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Cyan badge with bevel and crisp white 'i'
        draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(0, 120, 215), outline=(0, 220, 255), width=1)
        draw.rectangle([cx - 1, cy - 5, cx + 1, cy - 4], fill=(255, 255, 255))
        draw.rectangle([cx - 1, cy - 2, cx + 1, cy + 5], fill=(255, 255, 255))
        draw.point((cx - 2, cy - 1), fill=(255, 255, 255))
        draw.line([(cx - 2, cy + 5), (cx + 2, cy + 5)], fill=(255, 255, 255), width=1)

    @staticmethod
    def draw_success(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Circular green badge with check
        draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(30, 140, 45), outline=(90, 240, 110), width=1)
        draw.line([(cx - 5, cy), (cx - 2, cy + 4), (cx + 5, cy - 3)], fill=(255, 255, 255), width=2)

    @staticmethod
    def draw_warning(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Golden hazard triangle with black exclamation
        pulse = (255, 220, 0) if frame_num == 0 else (255, 170, 0)
        draw.polygon([(cx, cy - 9), (cx - 9, cy + 7), (cx + 9, cy + 7)], fill=pulse, outline=(140, 80, 0))
        draw.line([(cx, cy - 4), (cx, cy + 1)], fill=(0, 0, 0), width=2)
        draw.rectangle([cx - 1, cy + 3, cx + 1, cy + 5], fill=(0, 0, 0))

    @staticmethod
    def draw_alert(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # 3D golden bell ringing with sound waves
        bell_shift = -1 if frame_num == 0 else 1
        bx = cx + bell_shift
        draw.polygon([(bx - 2, cy - 8), (bx + 2, cy - 8), (bx + 7, cy + 3), (bx - 7, cy + 3)], fill=(255, 200, 0))
        draw.line([(bx - 2, cy - 8), (bx + 2, cy - 8)], fill=(255, 255, 160), width=1)
        draw.rectangle([bx - 8, cy + 3, bx + 8, cy + 5], fill=(220, 160, 0))
        draw.ellipse([bx - 2, cy + 5, bx + 2, cy + 8], fill=(160, 100, 0))
        # Sound waves
        wave_c = (255, 255, 255) if frame_num == 0 else (180, 220, 255)
        draw.arc([bx - 12, cy - 4, bx - 8, cy + 4], 120, 240, fill=wave_c, width=1)
        draw.arc([bx + 8, cy - 4, bx + 12, cy + 4], 300, 60, fill=wave_c, width=1)

    @staticmethod
    def draw_alarm(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Emergency beacon / siren with dual flashing lights
        c1 = (255, 0, 0) if frame_num % 2 == 0 else (0, 140, 255)
        c2 = (0, 140, 255) if frame_num % 2 == 0 else (255, 0, 0)
        draw.rectangle([cx - 7, cy + 3, cx + 7, cy + 7], fill=(60, 60, 70), outline=(30, 30, 40))
        draw.polygon([(cx - 5, cy + 3), (cx + 5, cy + 3), (cx + 3, cy - 6), (cx - 3, cy - 6)], fill=c1)
        draw.line([(cx, cy - 6), (cx, cy + 3)], fill=c2, width=2)
        # Flash rays
        ray_c = (255, 255, 200) if frame_num % 2 == 0 else (180, 220, 255)
        draw.line([(cx - 7, cy - 7), (cx - 5, cy - 5)], fill=ray_c, width=1)
        draw.line([(cx + 7, cy - 7), (cx + 5, cy - 5)], fill=ray_c, width=1)

    # --- Home Automation & Climate ---

    @staticmethod
    def draw_boiler(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Hot water boiler with temperature gauge and animated heater coil
        draw.rectangle([cx - 6, cy - 8, cx + 6, cy + 7], fill=(180, 190, 205), outline=(100, 110, 125))
        draw.arc([cx - 6, cy - 9, cx + 6, cy - 4], 180, 0, fill=(100, 110, 125), width=1)
        draw.line([(cx - 4, cy - 7), (cx - 4, cy + 6)], fill=(240, 245, 255), width=1)
        # Temp dial
        draw.ellipse([cx - 3, cy - 5, cx + 3, cy + 1], fill=(255, 255, 255), outline=(70, 70, 80))
        draw.line([(cx, cy - 2), (cx + 1, cy - 4)], fill=(255, 40, 40), width=1)
        # Heating flame/coil at bottom
        h_color = (255, 60, 0) if frame_num % 2 == 0 else (255, 180, 0)
        draw.line([(cx - 3, cy + 4), (cx - 1, cy + 2), (cx + 1, cy + 4), (cx + 3, cy + 2)], fill=h_color, width=1)

    @staticmethod
    def draw_ac(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # 6-branch crystal snowflake with pulsing core
        rot = frame_num * 15
        draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(255, 255, 255))
        for deg in [0, 60, 120, 180, 240, 300]:
            rad = math.radians(deg + rot)
            x1, y1 = cx + int(7 * math.cos(rad)), cy + int(7 * math.sin(rad))
            draw.line([(cx, cy), (x1, y1)], fill=(0, 220, 255), width=1)
            # small branch spurs
            bx = cx + int(4.5 * math.cos(rad))
            by = cy + int(4.5 * math.sin(rad))
            draw.point((bx, by), fill=(255, 255, 255))

    @staticmethod
    def draw_fan(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Rotating 3-blade cooling fan
        draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], outline=(100, 110, 130), width=1)
        draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(200, 210, 230))
        angle_base = (frame_num * 40) % 360
        for blade_deg in [angle_base, angle_base + 120, angle_base + 240]:
            rad = math.radians(blade_deg)
            x2 = cx + int(6.5 * math.cos(rad))
            y2 = cy + int(6.5 * math.sin(rad))
            draw.line([(cx, cy), (x2, y2)], fill=(0, 180, 255), width=2)

    @staticmethod
    def draw_light(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Glowing warm lightbulb with filament & radiance
        glow = (255, 230, 80) if frame_num % 2 == 0 else (255, 200, 40)
        draw.ellipse([cx - 5, cy - 7, cx + 5, cy + 1], fill=glow, outline=(220, 160, 0))
        draw.polygon([(cx - 3, cy + 1), (cx + 3, cy + 1), (cx + 2, cy + 4), (cx - 2, cy + 4)], fill=(180, 180, 190))
        draw.rectangle([cx - 2, cy + 4, cx + 2, cy + 6], fill=(130, 130, 140))
        # Inner filament
        draw.line([(cx - 1, cy - 3), (cx, cy - 5), (cx + 1, cy - 3)], fill=(255, 255, 255), width=1)
        # Rays
        draw.line([(cx - 7, cy - 3), (cx - 9, cy - 3)], fill=(255, 230, 100), width=1)
        draw.line([(cx + 7, cy - 3), (cx + 9, cy - 3)], fill=(255, 230, 100), width=1)
        draw.line([(cx, cy - 9), (cx, cy - 11)], fill=(255, 230, 100), width=1)

    @staticmethod
    def draw_vacuum(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Robot vacuum (Roomba) with rotating side sweeper
        draw.ellipse([cx - 7, cy - 6, cx + 7, cy + 6], fill=(45, 50, 60), outline=(130, 140, 155), width=1)
        draw.arc([cx - 6, cy - 5, cx + 6, cy + 5], 180, 0, fill=(70, 75, 90), width=2)
        # Status LED ring
        led_c = (0, 255, 120) if frame_num % 2 == 0 else (0, 200, 255)
        draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=led_c)
        # Spinning side sweeper
        sw_rad = math.radians(frame_num * 60)
        sx, sy = cx + 5 + int(3 * math.cos(sw_rad)), cy + 4 + int(3 * math.sin(sw_rad))
        draw.line([(cx + 5, cy + 4), (sx, sy)], fill=(255, 255, 255), width=1)

    @staticmethod
    def draw_power(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Lightning power bolt with bright core
        flash = (255, 255, 255) if frame_num % 2 == 0 else (255, 220, 0)
        draw.polygon([(cx + 1, cy - 8), (cx - 5, cy - 1), (cx - 1, cy - 1), (cx - 2, cy + 8), (cx + 5, cy), (cx + 1, cy)], fill=(255, 190, 0), outline=(150, 90, 0))
        draw.line([(cx, cy - 6), (cx - 3, cy - 1), (cx, cy - 1), (cx - 1, cy + 5)], fill=flash, width=1)

    @staticmethod
    def draw_shutter(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Window with roll-up shutter slats
        draw.rectangle([cx - 8, cy - 8, cx + 8, cy + 8], fill=(20, 25, 35), outline=(140, 150, 170), width=1)
        for y_line in range(cy - 6, cy + 6, 3):
            draw.line([(cx - 7, y_line), (cx + 7, y_line)], fill=(220, 225, 235), width=1)
            draw.line([(cx - 7, y_line + 1), (cx + 7, y_line + 1)], fill=(120, 130, 145), width=1)

    @staticmethod
    def draw_car(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Streamlined car with glass, tires, and headlights
        draw.polygon([(cx - 9, cy + 1), (cx - 5, cy - 5), (cx + 4, cy - 5), (cx + 8, cy + 1), (cx + 9, cy + 5), (cx - 9, cy + 5)], fill=(0, 170, 255))
        # Windshield
        draw.polygon([(cx - 4, cy - 4), (cx - 1, cy - 4), (cx - 1, cy), (cx - 6, cy)], fill=(180, 235, 255))
        draw.polygon([(cx + 1, cy - 4), (cx + 4, cy - 4), (cx + 6, cy), (cx + 1, cy)], fill=(180, 235, 255))
        # Wheels
        draw.ellipse([cx - 7, cy + 3, cx - 4, cy + 7], fill=(20, 20, 20), outline=(120, 120, 130))
        draw.ellipse([cx + 4, cy + 3, cx + 7, cy + 7], fill=(20, 20, 20), outline=(120, 120, 130))
        # Headlight
        hl = (255, 255, 80) if frame_num % 2 == 0 else (255, 200, 0)
        draw.point((cx + 9, cy + 2), fill=hl)

    @staticmethod
    def draw_door(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Wooden door opening with warm glow inside
        draw.rectangle([cx - 7, cy - 9, cx + 7, cy + 9], fill=(50, 40, 30), outline=(100, 80, 60))
        if frame_num == 0:
            draw.rectangle([cx - 6, cy - 8, cx + 6, cy + 8], fill=(160, 95, 45))
            draw.rectangle([cx - 4, cy - 6, cx + 4, cy - 1], outline=(120, 70, 30))
            draw.rectangle([cx - 4, cy + 1, cx + 4, cy + 6], outline=(120, 70, 30))
            draw.ellipse([cx + 3, cy, cx + 5, cy + 2], fill=(255, 215, 0))
        else:
            draw.rectangle([cx - 6, cy - 8, cx + 6, cy + 8], fill=(255, 220, 130))  # Light inside
            draw.polygon([(cx - 6, cy - 8), (cx + 2, cy - 6), (cx + 2, cy + 8), (cx - 6, cy + 8)], fill=(160, 95, 45))
            draw.point((cx + 1, cy + 1), fill=(255, 215, 0))

    @staticmethod
    def draw_garage(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Garage with paneled door
        draw.polygon([(cx - 9, cy - 5), (cx, cy - 9), (cx + 9, cy - 5)], fill=(160, 50, 40))
        draw.rectangle([cx - 8, cy - 4, cx + 8, cy + 8], fill=(60, 70, 85), outline=(100, 110, 130))
        y_cut = cy + 2 if frame_num == 1 else cy + 7
        for y in range(cy - 2, y_cut, 3):
            draw.line([(cx - 6, y), (cx + 6, y)], fill=(200, 210, 225), width=1)

    @staticmethod
    def draw_washer(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Washing machine with rotating wash water
        draw.rectangle([cx - 7, cy - 8, cx + 7, cy + 8], fill=(230, 235, 245), outline=(140, 150, 170))
        draw.rectangle([cx - 5, cy - 6, cx - 1, cy - 5], fill=(70, 80, 95))
        draw.point((cx + 4, cy - 6), fill=(0, 255, 100))
        # Porthole door
        draw.ellipse([cx - 5, cy - 2, cx + 5, cy + 6], fill=(50, 70, 100), outline=(140, 160, 190))
        water_angle = math.radians(frame_num * 90)
        wx, wy = cx + int(2.5 * math.cos(water_angle)), cy + 2 + int(2.5 * math.sin(water_angle))
        draw.ellipse([wx - 2, wy - 2, wx + 2, wy + 2], fill=(0, 210, 255))

    @staticmethod
    def draw_dryer(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Tumble dryer with warm airflow
        draw.rectangle([cx - 7, cy - 8, cx + 7, cy + 8], fill=(230, 235, 245), outline=(140, 150, 170))
        draw.point((cx + 4, cy - 6), fill=(255, 140, 0))
        draw.ellipse([cx - 5, cy - 2, cx + 5, cy + 6], fill=(90, 60, 40), outline=(190, 150, 120))
        heat_c = (255, 120, 0) if frame_num % 2 == 0 else (255, 200, 0)
        draw.arc([cx - 3, cy, cx + 3, cy + 4], 0, 180, fill=heat_c, width=2)

    @staticmethod
    def draw_lock(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # 3D brass padlock with steel shackle
        draw.arc([cx - 5, cy - 9, cx + 5, cy - 2], 180, 0, fill=(180, 190, 205), width=2)
        draw.rectangle([cx - 6, cy - 3, cx + 6, cy + 7], fill=(240, 190, 30), outline=(150, 110, 10))
        draw.line([(cx - 4, cy - 1), (cx - 4, cy + 5)], fill=(255, 240, 120), width=1)
        draw.ellipse([cx - 1, cy + 1, cx + 1, cy + 3], fill=(40, 30, 10))
        draw.line([(cx, cy + 2), (cx, cy + 5)], fill=(40, 30, 10), width=1)

    # --- Home Life, Sensors & Utilities ---

    @staticmethod
    def draw_home(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Cozy house with pitched roof, warm wall and glowing window
        draw.polygon([(cx, cy - 9), (cx - 9, cy - 1), (cx + 9, cy - 1)], fill=(210, 60, 40))
        draw.rectangle([cx - 7, cy - 1, cx + 7, cy + 8], fill=(225, 215, 195), outline=(120, 110, 95))
        # Chimney
        draw.rectangle([cx + 3, cy - 8, cx + 6, cy - 4], fill=(160, 60, 40))
        # Window & door
        draw.rectangle([cx - 4, cy + 1, cx - 1, cy + 4], fill=(255, 230, 80))
        draw.rectangle([cx + 1, cy + 2, cx + 4, cy + 8], fill=(130, 75, 30))

    @staticmethod
    def draw_motion(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Walking person silhouette with radiating motion arcs
        draw.ellipse([cx - 2, cy - 8, cx + 2, cy - 4], fill=(0, 240, 255))
        draw.line([(cx, cy - 4), (cx, cy + 2)], fill=(0, 240, 255), width=2)
        draw.line([(cx, cy - 1), (cx - 4, cy + 2)], fill=(0, 240, 255), width=1)
        draw.line([(cx, cy - 1), (cx + 4, cy - 2)], fill=(0, 240, 255), width=1)
        leg_shift = 2 if frame_num % 2 == 0 else -2
        draw.line([(cx, cy + 2), (cx - 3, cy + 7 - leg_shift)], fill=(0, 240, 255), width=2)
        draw.line([(cx, cy + 2), (cx + 3, cy + 7 + leg_shift)], fill=(0, 240, 255), width=2)
        # Radar/motion waves
        draw.arc([cx + 5, cy - 5, cx + 9, cy + 5], 300, 60, fill=(255, 255, 255), width=1)

    @staticmethod
    def draw_coffee(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Steaming coffee cup with handle
        draw.rectangle([cx - 6, cy - 2, cx + 4, cy + 6], fill=(230, 90, 70), outline=(150, 40, 30))
        draw.arc([cx + 2, cy - 1, cx + 7, cy + 4], 270, 90, fill=(150, 40, 30), width=2)
        draw.ellipse([cx - 6, cy - 3, cx + 4, cy - 1], fill=(100, 50, 25))
        # Rising steam
        s1 = cy - 5 + (1 if frame_num % 2 == 0 else 0)
        s2 = cy - 7 - (1 if frame_num % 2 == 0 else 0)
        draw.point((cx - 3, s1), fill=(240, 240, 255))
        draw.point((cx - 1, s2), fill=(240, 240, 255))
        draw.point((cx + 1, s1), fill=(240, 240, 255))

    @staticmethod
    def draw_package(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # 3D cardboard delivery box taped up
        draw.rectangle([cx - 7, cy - 5, cx + 7, cy + 7], fill=(195, 145, 95), outline=(130, 90, 50))
        # Tape strip
        draw.line([(cx, cy - 5), (cx, cy + 7)], fill=(225, 195, 145), width=2)
        # Shipping label
        draw.rectangle([cx - 5, cy + 1, cx - 2, cy + 4], fill=(255, 255, 255))

    @staticmethod
    def draw_mail(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Envelope with red wax/stamp seal
        draw.rectangle([cx - 8, cy - 6, cx + 8, cy + 6], fill=(245, 245, 250), outline=(160, 165, 180))
        draw.line([(cx - 8, cy - 6), (cx, cy + 1), (cx + 8, cy - 6)], fill=(120, 130, 150), width=1)
        draw.ellipse([cx - 2, cy, cx + 2, cy + 3], fill=(220, 40, 40))

    @staticmethod
    def draw_trash(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Green recycling bin with wheels
        draw.polygon([(cx - 6, cy - 4), (cx + 6, cy - 4), (cx + 4, cy + 7), (cx - 4, cy + 7)], fill=(45, 150, 60), outline=(25, 90, 35))
        draw.rectangle([cx - 7, cy - 6, cx + 7, cy - 4], fill=(30, 110, 45))
        draw.line([(cx - 2, cy - 7), (cx + 2, cy - 7)], fill=(30, 110, 45), width=1)
        draw.point((cx - 4, cy + 7), fill=(20, 20, 20))
        draw.point((cx + 4, cy + 7), fill=(20, 20, 20))

    @staticmethod
    def draw_pet(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Cute dog/cat paw print
        draw.ellipse([cx - 4, cy - 1, cx + 4, cy + 6], fill=(245, 160, 80))
        draw.ellipse([cx - 6, cy - 6, cx - 3, cy - 2], fill=(245, 160, 80))
        draw.ellipse([cx - 2, cy - 8, cx + 1, cy - 4], fill=(245, 160, 80))
        draw.ellipse([cx + 2, cy - 8, cx + 5, cy - 4], fill=(245, 160, 80))
        draw.ellipse([cx + 4, cy - 6, cx + 7, cy - 2], fill=(245, 160, 80))

    @staticmethod
    def draw_plant(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Plant pot with fresh green leaves
        draw.polygon([(cx - 5, cy + 1), (cx + 5, cy + 1), (cx + 4, cy + 8), (cx - 4, cy + 8)], fill=(190, 95, 60))
        draw.rectangle([cx - 6, cy, cx + 6, cy + 2], fill=(150, 70, 40))
        # Leaves
        draw.polygon([(cx, cy), (cx - 6, cy - 4), (cx - 1, cy - 7), (cx, cy)], fill=(40, 180, 70))
        draw.polygon([(cx, cy), (cx + 6, cy - 4), (cx + 1, cy - 7), (cx, cy)], fill=(70, 220, 100))
        draw.point((cx - 3, cy - 4), fill=(180, 255, 200))

    # --- Environmental, Device & Status ---

    @staticmethod
    def draw_fire(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # 3-color animated flame (red outer, orange body, yellow core)
        f_shift = 1 if frame_num % 2 == 0 else -1
        draw.polygon([(cx, cy - 9), (cx + 7, cy + 1), (cx + 5, cy + 8), (cx - 5, cy + 8), (cx - 7, cy + 1)], fill=(220, 30, 20))
        draw.polygon([(cx + f_shift, cy - 6), (cx + 5, cy + 2), (cx + 3, cy + 7), (cx - 3, cy + 7), (cx - 5, cy + 2)], fill=(255, 130, 0))
        draw.polygon([(cx - f_shift, cy - 2), (cx + 3, cy + 4), (cx + 2, cy + 7), (cx - 2, cy + 7), (cx - 3, cy + 4)], fill=(255, 240, 80))

    @staticmethod
    def draw_water(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Water teardrop with highlight & ripple
        draw.polygon([(cx, cy - 8), (cx + 6, cy + 2), (cx + 4, cy + 7), (cx - 4, cy + 7), (cx - 6, cy + 2)], fill=(0, 130, 240))
        draw.ellipse([cx - 4, cy + 1, cx + 4, cy + 7], fill=(0, 150, 255))
        draw.line([(cx - 3, cy + 1), (cx - 1, cy - 4)], fill=(200, 240, 255), width=1)
        # Ripple at bottom
        r_w = 7 if frame_num % 2 == 0 else 5
        draw.arc([cx - r_w, cy + 6, cx + r_w, cy + 9], 0, 180, fill=(120, 210, 255), width=1)

    @staticmethod
    def draw_battery(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Segmented battery with charge levels and terminal
        draw.rectangle([cx - 8, cy - 5, cx + 6, cy + 5], outline=(150, 160, 180), width=1)
        draw.rectangle([cx + 6, cy - 2, cx + 8, cy + 2], fill=(150, 160, 180))
        # 3 Green bars
        draw.rectangle([cx - 6, cy - 3, cx - 3, cy + 3], fill=(40, 220, 70))
        draw.rectangle([cx - 1, cy - 3, cx + 2, cy + 3], fill=(40, 220, 70))
        if frame_num % 2 == 0:
            draw.rectangle([cx + 3, cy - 3, cx + 5, cy + 3], fill=(40, 220, 70))

    @staticmethod
    def draw_wifi(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # 3-tier concentric wifi signal
        draw.ellipse([cx - 1, cy + 5, cx + 1, cy + 7], fill=(0, 230, 255))
        if frame_num >= 0:
            draw.arc([cx - 4, cy + 1, cx + 4, cy + 9], 220, 320, fill=(0, 230, 255), width=1)
        if frame_num >= 1:
            draw.arc([cx - 7, cy - 3, cx + 7, cy + 7], 220, 320, fill=(0, 230, 255), width=1)
        if frame_num >= 2:
            draw.arc([cx - 10, cy - 7, cx + 10, cy + 5], 220, 320, fill=(0, 230, 255), width=1)

    @staticmethod
    def draw_weather(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Smiling sun behind fluffy rain cloud
        draw.ellipse([cx + 1, cy - 8, cx + 8, cy - 1], fill=(255, 210, 0))
        # Cloud body
        draw.ellipse([cx - 8, cy - 4, cx - 1, cy + 3], fill=(190, 220, 245))
        draw.ellipse([cx - 4, cy - 6, cx + 4, cy + 2], fill=(230, 240, 255))
        draw.ellipse([cx + 1, cy - 3, cx + 8, cy + 4], fill=(190, 220, 245))
        draw.rectangle([cx - 6, cy + 1, cx + 6, cy + 4], fill=(190, 220, 245))
        # Raindrops
        r_y = cy + 6 + (1 if frame_num % 2 == 0 else 0)
        draw.point((cx - 4, r_y), fill=(0, 180, 255))
        draw.point((cx, r_y + 1), fill=(0, 180, 255))
        draw.point((cx + 4, r_y), fill=(0, 180, 255))

    @staticmethod
    def draw_sun(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Radiant sun with glowing corona
        draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 220, 0), outline=(255, 140, 0))
        for rad in [0, 45, 90, 135, 180, 225, 270, 315]:
            r_rad = math.radians(rad + (15 if frame_num % 2 == 1 else 0))
            x1 = cx + int(5.5 * math.cos(r_rad))
            y1 = cy + int(5.5 * math.sin(r_rad))
            x2 = cx + int(8.5 * math.cos(r_rad))
            y2 = cy + int(8.5 * math.sin(r_rad))
            draw.line([(x1, y1), (x2, y2)], fill=(255, 170, 0), width=1)

    @staticmethod
    def draw_moon(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Glowing crescent moon and twinkling stars
        draw.arc([cx - 7, cy - 7, cx + 7, cy + 7], 90, 270, fill=(240, 240, 180), width=3)
        draw.arc([cx - 2, cy - 7, cx + 8, cy + 7], 100, 260, fill=(0, 0, 0), width=2)
        star_c = (255, 255, 255) if frame_num % 2 == 0 else (180, 200, 255)
        draw.point((cx + 5, cy - 5), fill=star_c)
        draw.point((cx + 7, cy + 2), fill=star_c)

    @staticmethod
    def draw_music(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Beamed musical notes in neon magenta / cyan
        y_shift = -1 if frame_num % 2 == 1 else 0
        draw.ellipse([cx - 6, cy + 2 + y_shift, cx - 2, cy + 6 + y_shift], fill=(255, 80, 180))
        draw.ellipse([cx + 3, cy + 2 + y_shift, cx + 7, cy + 6 + y_shift], fill=(255, 80, 180))
        draw.line([(cx - 2, cy + 4 + y_shift), (cx - 2, cy - 6 + y_shift)], fill=(0, 230, 255), width=2)
        draw.line([(cx + 7, cy + 4 + y_shift), (cx + 7, cy - 6 + y_shift)], fill=(0, 230, 255), width=2)
        draw.line([(cx - 2, cy - 6 + y_shift), (cx + 7, cy - 6 + y_shift)], fill=(0, 230, 255), width=2)

    @staticmethod
    def draw_phone(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Vibrating modern smartphone
        vib = -1 if frame_num % 2 == 0 else 1
        px = cx + vib
        draw.rectangle([cx - 5 + vib, cy - 8, cx + 5 + vib, cy + 8], fill=(30, 35, 45), outline=(130, 140, 160))
        draw.rectangle([cx - 4 + vib, cy - 6, cx + 4 + vib, cy + 6], fill=(0, 140, 255))
        draw.point((cx + vib, cy + 7), fill=(200, 210, 220))
        # Vibration waves
        draw.arc([px - 9, cy - 4, px - 6, cy + 4], 120, 240, fill=(255, 255, 255), width=1)
        draw.arc([px + 6, cy - 4, px + 9, cy + 4], 300, 60, fill=(255, 255, 255), width=1)

    @staticmethod
    def draw_calendar(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Wall/desk calendar with red binder header
        draw.rectangle([cx - 7, cy - 7, cx + 7, cy + 8], fill=(250, 250, 255), outline=(120, 130, 145))
        draw.rectangle([cx - 7, cy - 7, cx + 7, cy - 3], fill=(230, 40, 40))
        for px, py in [(cx - 4, cy + 1), (cx, cy + 1), (cx + 4, cy + 1), (cx - 4, cy + 5), (cx, cy + 5)]:
            draw.point((px, py), fill=(60, 70, 85))

    @staticmethod
    def draw_camera(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Camera body with lens reflection & recording LED
        draw.rectangle([cx - 8, cy - 5, cx + 8, cy + 6], fill=(45, 50, 60), outline=(110, 120, 135))
        draw.rectangle([cx - 2, cy - 7, cx + 2, cy - 5], fill=(70, 75, 85))
        draw.ellipse([cx - 4, cy - 3, cx + 4, cy + 5], fill=(20, 25, 30), outline=(160, 170, 190))
        draw.point((cx - 1, cy - 1), fill=(255, 255, 255))
        rec_c = (255, 40, 40) if frame_num % 2 == 0 else (100, 20, 20)
        draw.point((cx + 6, cy - 3), fill=rec_c)

    @staticmethod
    def draw_attack(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Missile rocket with metal hull and fire trail
        draw.polygon([(cx, cy - 9), (cx - 3, cy - 4), (cx + 3, cy - 4)], fill=(220, 40, 40))
        draw.rectangle([cx - 3, cy - 4, cx + 3, cy + 4], fill=(210, 215, 225), outline=(120, 125, 135))
        draw.polygon([(cx - 3, cy + 4), (cx - 6, cy + 7), (cx - 3, cy + 6)], fill=(180, 40, 40))
        draw.polygon([(cx + 3, cy + 4), (cx + 6, cy + 7), (cx + 3, cy + 6)], fill=(180, 40, 40))
        f_c = (255, 120, 0) if frame_num % 2 == 0 else (255, 240, 0)
        draw.polygon([(cx - 2, cy + 4), (cx, cy + 8), (cx + 2, cy + 4)], fill=f_c)

    @staticmethod
    def draw_time(draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int):
        # Clock face with ticking hand
        draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(245, 245, 250), outline=(80, 90, 105))
        rad = math.radians((frame_num * 90) - 90)
        draw.line([(cx, cy), (cx + int(5 * math.cos(rad)), cy + int(5 * math.sin(rad)))], fill=(220, 30, 30), width=1)
        draw.line([(cx, cy), (cx, cy - 3)], fill=(40, 45, 55), width=1)

    # --- Registry & Dispatcher ---

    _REGISTRY: Dict[str, Callable] = {
        # Core & Status
        "v": draw_v, "success": draw_success, "x": draw_x, "cancel": draw_x,
        "error": draw_x, "info": draw_info, "warning": draw_warning,
        "alert": draw_alert, "alarm": draw_alarm, "siren": draw_alarm,
        # Smart Home & Climate
        "boiler": draw_boiler, "ac": draw_ac, "climate": draw_ac, "snowflake": draw_ac,
        "fan": draw_fan, "light": draw_light, "lamp": draw_light, "bulb": draw_light,
        "vacuum": draw_vacuum, "robot_vacuum": draw_vacuum, "shutter": draw_shutter,
        "door": draw_door, "garage": draw_garage, "gate": draw_garage,
        "lock": draw_lock, "washer": draw_washer, "dryer": draw_dryer,
        "power": draw_power, "plug": draw_power, "energy": draw_power,
        # Home Life & Utilities
        "home": draw_home, "presence": draw_home, "motion": draw_motion,
        "person": draw_motion, "coffee": draw_coffee, "package": draw_package,
        "delivery": draw_package, "mail": draw_mail, "trash": draw_trash,
        "pet": draw_pet, "dog": draw_pet, "cat": draw_pet, "plant": draw_plant,
        "leaf": draw_plant, "car": draw_car,
        # Environment & Devices
        "fire": draw_fire, "water": draw_water, "leak": draw_water,
        "battery": draw_battery, "wifi": draw_wifi, "weather": draw_weather,
        "sun": draw_sun, "moon": draw_moon, "sleep": draw_moon,
        "music": draw_music, "phone": draw_phone, "calendar": draw_calendar,
        "camera": draw_camera, "attack": draw_attack, "rocket": draw_attack,
        "timer": draw_time, "time": draw_time,
    }

    @classmethod
    def render_icon(cls, n_type: str, draw: ImageDraw.ImageDraw, cx: int, cy: int, color: tuple, frame_num: int = 0) -> None:
        """Render the specified notification icon at (cx, cy)."""
        fn = cls._REGISTRY.get(str(n_type).lower())
        if fn:
            fn(draw, cx, cy, color, frame_num)
        else:
            # Fallback to info badge if unknown icon requested
            cls.draw_info(draw, cx, cy, color, frame_num)
