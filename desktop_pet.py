#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌宠显示模块 (Pygame HDMI 输出)
================================
在 HDMI 显示器上展示:
  - 机器人 GIF 动画 (可用摇杆拖动位置)
  - 摄像头实时预览
  - 底部状态栏

GIF 文件放在 git/ 目录下:
  idle.gif, happy.gif, comfort.gif, flower.gif, surprise.gif
若 GIF 不存在则显示占位文字提示。
"""

import os
import sys
import math
import numpy as np

try:
    import pygame
    _HAS_PYGAME = True
except ImportError:
    _HAS_PYGAME = False
    print("[WARN] pygame not installed. Run: pip install pygame")

try:
    from PIL import Image, ImageSequence
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False


# ============================================================
# 颜色常量
# ============================================================

WHITE      = (255, 255, 255)
BLACK      = (0,   0,   0)
GRAY       = (128, 128, 128)
LIGHT_GRAY = (200, 200, 200)
DARK_GRAY  = (60,  60,  60)
GREEN      = (50,  255, 50)
RED        = (255, 50,  50)
YELLOW     = (255, 255, 0)
BLUE       = (50,  120, 255)
CYAN       = (0,   255, 255)

# 情绪 → 状态栏颜色
EMOTION_COLORS = {
    'happy':    GREEN,
    'sad':      (100, 150, 255),
    'angry':    RED,
    'surprise': YELLOW,
    'neutral':  LIGHT_GRAY,
    'fear':     (180, 0, 255),
    'disgust':  (255, 165, 0),
}


# ============================================================
# GIF 加载器
# ============================================================

def load_gif_frames(path, target_size=None):
    """
    加载 GIF 并返回 Pygame Surface 帧列表

    返回: [pygame.Surface, ...]  或  None
    """
    if not _HAS_PIL:
        return None

    try:
        gif = Image.open(path)
        frames = []
        for frame in ImageSequence.Iterator(gif):
            frame = frame.convert('RGBA')
            if target_size:
                frame = frame.resize(target_size, Image.LANCZOS)
            data = frame.tobytes()
            size = frame.size
            surf = pygame.image.fromstring(data, size, 'RGBA')
            frames.append(surf)
        return frames
    except Exception as e:
        print(f"[WARN] 无法加载 GIF '{path}': {e}")
        return None


# ============================================================
# 桌宠主显示类
# ============================================================

class DesktopPet:
    """
    HDMI 显示器布局:

      ┌──────────────────────────────────┐
      │  🤖 GIF (可拖动)   │  📷 Camera  │
      │                    │             │
      ├────────────────────┴─────────────┤
      │  Status Bar (底部 80px)           │
      └──────────────────────────────────┘
    """

    # GIF 文件名映射 (放在 git/ 目录下)
    GIF_FILES = {
        'idle':     'git/idle.gif',
        'happy':    'git/happy.gif',
        'comfort':  'git/comfort.gif',
        'flower':   'git/flower.gif',
        'surprise': 'git/surprise.gif',
        'sad':      'git/comfort.gif',   # sad 复用 comfort
        'angry':    'git/flower.gif',     # angry 复用 flower
        'neutral':  'git/idle.gif',
        'fear':     'git/surprise.gif',   # fear 暂用 surprise
        'disgust':  'git/idle.gif',
    }

    def __init__(self, fullscreen=True, width=1280, height=720):
        if not _HAS_PYGAME:
            raise ImportError("DesktopPet 需要 pygame: pip install pygame")

        pygame.init()
        pygame.display.set_caption("Emotion Robot - Desktop Pet")

        if fullscreen:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            self.width = self.screen.get_width()
            self.height = self.screen.get_height()
        else:
            self.width = width
            self.height = height
            self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)

        self.clock = pygame.time.Clock()
        self.fps = 30
        self.running = False

        # ── 布局 ──────────────────────────────────────────
        self.status_bar_h = 80
        self.main_area_h = self.height - self.status_bar_h
        self.robot_rect = pygame.Rect(0, 0,
                                      int(self.width * 0.45),
                                      self.main_area_h)
        self.camera_rect = pygame.Rect(int(self.width * 0.45), 0,
                                       self.width - int(self.width * 0.45),
                                       self.main_area_h)
        self.status_rect = pygame.Rect(0, self.main_area_h,
                                       self.width, self.status_bar_h)

        # ── GIF 管理 ──────────────────────────────────────
        self._gif_cache = {}       # emotion → [pygame.Surface, ...]
        self._gif_frame_idx = {}   # emotion → current frame index
        self._gif_last_switch = {} # emotion → last switch time
        self._gif_frame_delay = 0.08  # 约 12.5 FPS

        # 当前 GIF 显示尺寸 (加载时确定)
        self._gif_size = (200, 200)

        # 加载所有 GIF
        self._load_all_gifs()

        # ── GIF 位置 (可拖动) ─────────────────────────────
        # 初始位置 = 机器人区域中心
        self.gif_x = self.robot_rect.centerx
        self.gif_y = self.robot_rect.centery
        self.gif_target_w = 200
        self.gif_target_h = 200

        # ── 状态 ──────────────────────────────────────────
        self.emotion = 'neutral'
        self.status_text = "I'm ready when you are."
        self.camera_frame = None

        # ── 字体 ──────────────────────────────────────────
        self.font_status = pygame.font.Font(None, 32)
        self.font_title  = pygame.font.Font(None, 24)
        self.font_hint   = pygame.font.Font(None, 20)

    # ── GIF 加载 ──────────────────────────────────────────

    def _load_all_gifs(self):
        """预加载所有情绪的 GIF"""
        loaded_any = False
        for emotion, path in self.GIF_FILES.items():
            if emotion in self._gif_cache:
                continue   # 已加载
            if os.path.exists(path):
                frames = load_gif_frames(path, self._gif_size)
                if frames and len(frames) > 0:
                    self._gif_cache[emotion] = frames
                    self._gif_frame_idx[emotion] = 0
                    self._gif_last_switch[emotion] = 0
                    loaded_any = True
                    print(f"[INFO] 已加载 GIF: {path} ({len(frames)} 帧)")
                else:
                    print(f"[WARN] GIF 为空: {path}")
            else:
                # 尝试备用路径
                alt = path.replace('git/', '')
                if os.path.exists(alt):
                    frames = load_gif_frames(alt, self._gif_size)
                    if frames and len(frames) > 0:
                        self._gif_cache[emotion] = frames
                        self._gif_frame_idx[emotion] = 0
                        self._gif_last_switch[emotion] = 0
                        loaded_any = True
                        print(f"[INFO] 已加载 GIF: {alt} ({len(frames)} 帧)")
                        continue

        if not loaded_any:
            print("[WARN] 未找到任何 GIF 文件!")
            print("       请将 GIF 放入 git/ 目录:")
            print("         git/idle.gif, git/happy.gif, git/comfort.gif, git/flower.gif, git/surprise.gif")

    def _get_gif_frames(self, emotion):
        """获取指定情绪的 GIF 帧列表, 找不到则 fallback"""
        if emotion in self._gif_cache:
            return self._gif_cache[emotion]
        # fallback 链
        for fallback in [self.GIF_FILES.get(emotion, '').split('/')[-1].replace('.gif',''),
                         'idle', 'neutral']:
            if fallback in self._gif_cache:
                return self._gif_cache[fallback]
        return None

    # ── 情绪切换 ──────────────────────────────────────────

    def set_emotion(self, emotion, status_text=None):
        """
        切换情绪 (保持当前 GIF 位置不变)

        新 GIF 会在原地替换旧 GIF
        """
        if emotion not in self._gif_cache:
            # 触发按需加载
            path = self.GIF_FILES.get(emotion)
            if path and os.path.exists(path):
                frames = load_gif_frames(path, self._gif_size)
                if frames:
                    self._gif_cache[emotion] = frames
                    self._gif_frame_idx[emotion] = 0
                    self._gif_last_switch[emotion] = 0

        self.emotion = emotion
        if status_text:
            self.status_text = status_text
        print(f"[PET] 情绪切换: {emotion} (位置: {self.gif_x},{self.gif_y})")

    # ── 摇杆移动 ──────────────────────────────────────────

    def move_gif(self, dx, dy):
        """
        移动 GIF 位置

        参数:
            dx, dy: 像素偏移量 (自动钳位到机器人区域)
        """
        margin = 20
        self.gif_x = max(self.robot_rect.left + margin,
                         min(self.robot_rect.right - margin, self.gif_x + dx))
        self.gif_y = max(self.robot_rect.top + margin,
                         min(self.robot_rect.bottom - margin, self.gif_y + dy))

    # ── 摄像头帧 ──────────────────────────────────────────

    def set_camera_frame(self, frame_bgr):
        """设置摄像头画面 (BGR numpy array)"""
        self.camera_frame = frame_bgr

    # ── 每帧更新 ──────────────────────────────────────────

    def update(self, time_now=None):
        """
        执行一帧更新和渲染 (在 main loop 中每帧调用)
        """
        dt = self.clock.tick(self.fps) / 1000.0
        if time_now is None:
            time_now = pygame.time.get_ticks() / 1000.0

        # 绘制背景
        self.screen.fill((30, 30, 50))

        # ── 机器人 / GIF 区域 ──
        pygame.draw.rect(self.screen, (40, 40, 60), self.robot_rect, border_radius=10)
        self._draw_gif(time_now)

        # ── 摄像头区域 ──
        pygame.draw.rect(self.screen, (20, 20, 40), self.camera_rect, border_radius=10)
        self._draw_camera_preview()

        # ── 状态栏 ──
        self._draw_status_bar()

        # 更新显示
        pygame.display.flip()

    def _draw_gif(self, time_now):
        """绘制当前情绪的 GIF (在 gif_x, gif_y 位置)"""
        frames = self._get_gif_frames(self.emotion)

        if frames is None:
            # 无 GIF: 显示占位提示
            self._draw_gif_placeholder()
            return

        # GIF 帧切换
        idx_key = self.emotion
        if idx_key not in self._gif_last_switch:
            self._gif_last_switch[idx_key] = 0
        if idx_key not in self._gif_frame_idx:
            self._gif_frame_idx[idx_key] = 0

        if time_now - self._gif_last_switch[idx_key] >= self._gif_frame_delay:
            self._gif_frame_idx[idx_key] = (
                (self._gif_frame_idx[idx_key] + 1) % len(frames))
            self._gif_last_switch[idx_key] = time_now

        frame = frames[self._gif_frame_idx[idx_key]]
        fw, fh = frame.get_size()

        # 以 gif_x, gif_y 为中心绘制
        x = int(self.gif_x - fw / 2)
        y = int(self.gif_y - fh / 2)
        self.screen.blit(frame, (x, y))

        # 轻边框
        color = EMOTION_COLORS.get(self.emotion, LIGHT_GRAY)
        pygame.draw.rect(self.screen, color, (x - 2, y - 2, fw + 4, fh + 4), 2)

        # 情绪标签 (左上角)
        label = self.font_hint.render(self.emotion.upper(), True, color)
        self.screen.blit(label, (x + 5, y + 5))

    def _draw_gif_placeholder(self):
        """GIF 未加载时的占位提示"""
        cx, cy = self.gif_x, self.gif_y

        # 虚线框
        rect_w, rect_h = 180, 180
        rx, ry = int(cx - rect_w/2), int(cy - rect_h/2)
        pygame.draw.rect(self.screen, GRAY, (rx, ry, rect_w, rect_h), 2)

        # 文字提示
        texts = [
            "No GIF Found",
            "Put GIFs in:",
            "git/idle.gif",
            "git/happy.gif",
            "git/comfort.gif",
            "git/flower.gif",
            "git/surprise.gif",
        ]
        for i, txt in enumerate(texts):
            surf = self.font_hint.render(txt, True, GRAY)
            tx = cx - surf.get_width() // 2
            ty = ry + 15 + i * 22
            self.screen.blit(surf, (tx, ty))

    def _draw_camera_preview(self):
        """绘制摄像头预览"""
        if self.camera_frame is None:
            font = pygame.font.Font(None, 28)
            text = font.render("Camera Offline", True, GRAY)
            tx = self.camera_rect.centerx - text.get_width() // 2
            ty = self.camera_rect.centery - text.get_height() // 2
            self.screen.blit(text, (tx, ty))
            return

        try:
            frame_rgb = cv2.cvtColor(self.camera_frame, cv2.COLOR_BGR2RGB)
            fh, fw = frame_rgb.shape[:2]
            cr_w = self.camera_rect.width - 20
            cr_h = self.camera_rect.height - 20
            scale = min(cr_w / fw, cr_h / fh)
            new_w = int(fw * scale)
            new_h = int(fh * scale)

            frame_rgb = cv2.resize(frame_rgb, (new_w, new_h))
            surface = pygame.image.frombuffer(
                frame_rgb.tobytes(), (new_w, new_h), 'RGB')

            x = self.camera_rect.centerx - new_w // 2
            y = self.camera_rect.centery - new_h // 2
            self.screen.blit(surface, (x, y))
            pygame.draw.rect(self.screen, (100, 100, 150),
                             (x - 2, y - 2, new_w + 4, new_h + 4), 2)
        except Exception:
            pass

    def _draw_status_bar(self):
        """绘制底部状态栏"""
        pygame.draw.rect(self.screen, (15, 15, 30), self.status_rect)
        pygame.draw.line(self.screen, (80, 80, 120),
                         (self.status_rect.left, self.status_rect.top),
                         (self.status_rect.right, self.status_rect.top), 2)

        color = EMOTION_COLORS.get(self.emotion, LIGHT_GRAY)

        # 左侧: 情绪标签
        label = f"Emotion: {self.emotion.upper()}"
        label_surf = self.font_title.render(label, True, color)
        self.screen.blit(label_surf, (20, self.status_rect.top + 10))

        # 右侧: 状态文案
        status_surf = self.font_status.render(self.status_text, True, WHITE)
        status_x = self.width - status_surf.get_width() - 30
        status_y = self.status_rect.centery - status_surf.get_height() // 2
        self.screen.blit(status_surf, (status_x, status_y))

        # 摇杆提示
        hint = "Move: Joystick | Touch: Detect"
        hint_surf = self.font_hint.render(hint, True, GRAY)
        self.screen.blit(hint_surf, (20, self.status_rect.top + 50))

    # ── 事件处理 ──────────────────────────────────────────

    def handle_events(self):
        """处理 Pygame 事件, 返回 False 表示退出"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
            elif event.type == pygame.VIDEORESIZE:
                self.width, self.height = event.size
                self._recalc_layout()
        return True

    def _recalc_layout(self):
        """窗口大小改变时重新计算布局"""
        self.main_area_h = self.height - self.status_bar_h
        self.robot_rect = pygame.Rect(0, 0,
                                      int(self.width * 0.45),
                                      self.main_area_h)
        self.camera_rect = pygame.Rect(int(self.width * 0.45), 0,
                                       self.width - int(self.width * 0.45),
                                       self.main_area_h)
        self.status_rect = pygame.Rect(0, self.main_area_h,
                                       self.width, self.status_bar_h)

    def quit(self):
        """退出 Pygame"""
        pygame.quit()


# ============================================================
# 摇杆读取器 (从 PCF8591 读取 VRx/VRy, 映射为移动偏移)
# ============================================================

class JoystickReader:
    """
    双轴摇杆读取器 (通过 PCF8591 ADC)

    用法:
        joy = JoystickReader(pcf8591_reader)
        dx, dy, pressed = joy.read()
        # dx, dy: -speed ~ +speed 范围的移动偏移
        # pressed: 摇杆按键是否按下
    """

    def __init__(self, pcf8591, sw_pin=13, deadzone=15, speed=4):
        self.pcf = pcf8591
        self.sw_pin = sw_pin
        self.deadzone = deadzone
        self.speed = speed
        self._sw_available = False

        # 初始化 SW 引脚 (带上拉)
        try:
            import RPi.GPIO as GPIO
            GPIO.setup(sw_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self._gpio = GPIO
            self._sw_available = True
        except Exception:
            self._sw_available = False

    def read(self):
        """
        读取摇杆状态

        返回: (dx, dy, sw_pressed)
            dx, dy: 像素移动偏移 (-speed ~ +speed)
            sw_pressed: True/False
        """
        try:
            raw_x = self.pcf.read_joystick_x()  # 0~255
            raw_y = self.pcf.read_joystick_y()  # 0~255
        except Exception:
            return 0, 0, False

        # 计算偏离中心的距离
        center = 128
        offset_x = raw_x - center
        offset_y = raw_y - center

        # 死区
        dx, dy = 0, 0
        if abs(offset_x) > self.deadzone:
            # 超出死区的部分线性映射到速度
            sign_x = 1 if offset_x > 0 else -1
            magnitude = (abs(offset_x) - self.deadzone) / (127 - self.deadzone)
            dx = sign_x * self.speed * magnitude

        if abs(offset_y) > self.deadzone:
            sign_y = 1 if offset_y > 0 else -1
            magnitude = (abs(offset_y) - self.deadzone) / (127 - self.deadzone)
            dy = sign_y * self.speed * magnitude

        # 摇杆按键 (按下=低电平)
        sw = False
        if self._sw_available:
            try:
                sw = (self._gpio.input(self.sw_pin) == self._gpio.LOW)
            except Exception:
                pass

        return dx, dy, sw

    def cleanup(self):
        """清理 GPIO"""
        pass


# ============================================================
# 自检: 独立运行查看 GIF 效果
# ============================================================

if __name__ == '__main__':
    print("=== 桌宠显示模块自检 ===\n")
    print("方向键移动 GIF, 数字键 1-5 切换情绪, ESC 退出\n")

    pet = DesktopPet(fullscreen=False, width=1024, height=600)

    emotions = ['idle', 'happy', 'comfort', 'flower', 'surprise']
    status_map = {
        'idle':     "I'm ready when you are.",
        'happy':    "You look happy today! 😊",
        'comfort':  "Cheer up! I'm here for you.",
        'flower':   "Take it easy.",
        'surprise': "Wow! That's surprising!",
    }
    current = 'idle'
    pet.set_emotion('idle', status_map['idle'])

    running = True
    while running:
        running = pet.handle_events()

        # 数字键切换情绪
        keys = pygame.key.get_pressed()
        for i, emo in enumerate(emotions):
            if keys[getattr(pygame, f'K_{i+1}')]:
                pet.set_emotion(emo, status_map[emo])

        # 方向键移动 GIF
        speed = 5
        if keys[pygame.K_LEFT]:
            pet.move_gif(-speed, 0)
        if keys[pygame.K_RIGHT]:
            pet.move_gif(speed, 0)
        if keys[pygame.K_UP]:
            pet.move_gif(0, -speed)
        if keys[pygame.K_DOWN]:
            pet.move_gif(0, speed)

        pet.update()

    pet.quit()
