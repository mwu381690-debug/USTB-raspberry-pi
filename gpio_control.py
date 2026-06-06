#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPIO 外设控制
=============
- 普通单色 LED (GPIO 高低电平)
- RGB 三色 LED (共阴极, 3 路 PWM)
- 有源蜂鸣器 (GPIO 高低电平)
- 触摸传感器 TTP223 (GPIO 输入)
"""

import time
import threading

try:
    import RPi.GPIO as GPIO
    _HAS_RPI_GPIO = True
except ImportError:
    _HAS_RPI_GPIO = False
    print("[WARN] RPi.GPIO not installed. Run: pip install RPi.GPIO")


class SimpleLED:
    """
    普通单色 LED 控制 (GPIO 高低电平)

    用法:
        status_led = SimpleLED(pin=16)
        status_led.on()              # 点亮
        status_led.off()             # 熄灭
    """

    def __init__(self, pin):
        if not _HAS_RPI_GPIO:
            raise ImportError("SimpleLED 需要 RPi.GPIO")

        self.pin = pin
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

    def on(self):
        """点亮 LED"""
        GPIO.output(self.pin, GPIO.HIGH)

    def off(self):
        """熄灭 LED"""
        GPIO.output(self.pin, GPIO.LOW)

    def toggle(self):
        """翻转 LED 状态"""
        GPIO.output(self.pin, not GPIO.input(self.pin))

    def cleanup(self):
        """清理"""
        self.off()


class RGBLED:
    """
    RGB 三色 LED 控制 (共阴极) — 用于检测状态红绿交替

    用法:
        led = RGBLED(red=17, green=27, blue=22)
        led.set_color('green')       # 预设颜色
        led.set_rgb(100, 0, 0)       # 自定义 RGB (0~100)
        led.start_alternating()      # 开始红绿交替
        led.stop_alternating()       # 停止交替
    """

    def __init__(self, red_pin=17, green_pin=27, blue_pin=22, freq=100):
        if not _HAS_RPI_GPIO:
            raise ImportError("RGBLED 需要 RPi.GPIO")

        self.pins = {'r': red_pin, 'g': green_pin, 'b': blue_pin}
        self.pwm = {}
        self.freq = freq
        self._alt_thread = None
        self._alt_running = False

        # 初始化 GPIO
        GPIO.setup(red_pin,   GPIO.OUT)
        GPIO.setup(green_pin, GPIO.OUT)
        GPIO.setup(blue_pin,  GPIO.OUT)

        # 初始化 PWM
        for label, pin in self.pins.items():
            p = GPIO.PWM(pin, freq)
            p.start(0)
            self.pwm[label] = p

        self.off()

    def set_rgb(self, r, g, b):
        """
        设置 RGB 三通道占空比

        参数: r, g, b 取值 0~100 (百分比)
        """
        self.pwm['r'].ChangeDutyCycle(max(0, min(100, r)))
        self.pwm['g'].ChangeDutyCycle(max(0, min(100, g)))
        self.pwm['b'].ChangeDutyCycle(max(0, min(100, b)))

    def set_color(self, color_name):
        """
        设置预设颜色

        支持: 'red', 'green', 'blue', 'yellow', 'cyan',
              'purple', 'white', 'off'
        """
        from config import LED_COLORS
        rgb = LED_COLORS.get(color_name, (0, 0, 0))
        self.set_rgb(*rgb)

    def off(self):
        """关闭所有通道"""
        self.set_rgb(0, 0, 0)

    def start_alternating(self, interval=0.5):
        """
        开始红绿交替闪烁 (在后台线程中)

        用于指示"情绪检测进行中"
        """
        if self._alt_running:
            return
        self._alt_running = True
        self._alt_thread = threading.Thread(target=self._alt_loop,
                                            args=(interval,), daemon=True)
        self._alt_thread.start()

    def stop_alternating(self):
        """停止红绿交替"""
        self._alt_running = False
        if self._alt_thread:
            self._alt_thread.join(timeout=2.0)
        self.set_color('green')  # 恢复绿灯

    def _alt_loop(self, interval):
        """交替闪烁后台循环"""
        toggle = True
        while self._alt_running:
            if toggle:
                self.set_color('red')
            else:
                self.set_color('green')
            toggle = not toggle
            time.sleep(interval)
        # 退出时确保恢复绿色
        self.set_color('green')

    def cleanup(self):
        """清理 PWM 资源"""
        self.stop_alternating()
        for p in self.pwm.values():
            try:
                p.stop()
            except Exception:
                pass


class Buzzer:
    """
    有源蜂鸣器控制 (GPIO 高低电平)

    有源蜂鸣器内部自带振荡电路, 通电即响,
    GPIO 输出 HIGH=响, LOW=停, 无需 PWM。

    用法:
        buzzer = Buzzer(pin=18)
        buzzer.beep(0.2)            # 响 0.2 秒
        buzzer.play_pattern()       # 播放预设间歇提示音
    """

    def __init__(self, pin=18):
        if not _HAS_RPI_GPIO:
            raise ImportError("Buzzer 需要 RPi.GPIO")

        self.pin = pin
        self._playing = False
        self._thread = None

        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

    def on(self):
        """蜂鸣器开始鸣叫"""
        GPIO.output(self.pin, GPIO.HIGH)

    def off(self):
        """蜂鸣器停止鸣叫"""
        GPIO.output(self.pin, GPIO.LOW)

    def beep(self, duration):
        """
        蜂鸣器响指定时长 (阻塞)

        参数:
            duration: 时长 (秒), 0 表示静音等待
        """
        if duration > 0:
            self.on()
            time.sleep(duration)
        self.off()

    def play_pattern(self, pattern=None):
        """
        播放预设间歇提示音 (非阻塞, 在后台线程中)

        参数:
            pattern: [(响秒数, 停秒数), ...] 列表
                     若为 None, 使用 config 中的 BUZZER_PATTERN

        示例:
            buzzer.play_pattern([
                (0.15, 0.10),   # 响0.15秒, 停0.10秒
                (0.15, 0.10),
                (0.20, 0.50),   # 响0.20秒, 停0.50秒
            ])
        """
        if pattern is None:
            from config import BUZZER_PATTERN
            pattern = BUZZER_PATTERN

        if self._playing:
            return

        self._thread = threading.Thread(target=self._play_thread,
                                        args=(pattern,), daemon=True)
        self._thread.start()

    def _play_thread(self, pattern):
        """后台播放线程"""
        self._playing = True
        try:
            for on_dur, off_dur in pattern:
                if not self._playing:
                    break
                if on_dur > 0:
                    self.on()
                    time.sleep(on_dur)
                self.off()
                if off_dur > 0:
                    time.sleep(off_dur)
        finally:
            self.off()
            self._playing = False

    def cleanup(self):
        """清理资源"""
        self._playing = False
        self.off()


class TouchSensor:
    """
    TTP223 触摸传感器

    用法:
        touch = TouchSensor(pin=23)
        if touch.is_pressed():
            print("触摸!")
    """

    def __init__(self, pin=23):
        if not _HAS_RPI_GPIO:
            raise ImportError("TouchSensor 需要 RPi.GPIO")

        self.pin = pin
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    def is_pressed(self):
        """返回当前触摸状态 (True=触摸中)"""
        return GPIO.input(self.pin) == GPIO.HIGH

    def wait_for_touch(self, timeout=None):
        """
        等待触摸事件 (阻塞)

        参数:
            timeout: 超时秒数, None=无限等待

        返回:
            True=检测到触摸, False=超时
        """
        try:
            channel = GPIO.wait_for_edge(self.pin, GPIO.RISING,
                                         timeout=int(timeout * 1000) if timeout else None)
            return channel is not None
        except Exception:
            return False


# ============================================================
# 硬件初始化/清理辅助函数
# ============================================================

def gpio_setup():
    """初始化 GPIO (设置模式)"""
    if _HAS_RPI_GPIO:
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        print("[INFO] GPIO 初始化完成 (BCM 模式)")


def gpio_cleanup():
    """清理所有 GPIO 资源"""
    if _HAS_RPI_GPIO:
        try:
            GPIO.cleanup()
            print("[INFO] GPIO 资源已清理")
        except Exception:
            pass


# ============================================================
# 自检
# ============================================================

if __name__ == '__main__':
    print("=== GPIO 外设自检 ===\n")

    gpio_setup()

    try:
        # 测试 RGB LED
        print("[TEST] RGB LED...")
        led = RGBLED()
        print("  红色")
        led.set_color('red')
        time.sleep(0.5)
        print("  绿色")
        led.set_color('green')
        time.sleep(0.5)
        print("  蓝色")
        led.set_color('blue')
        time.sleep(0.5)
        print("  交替")
        led.start_alternating(0.3)
        time.sleep(2)
        led.stop_alternating()
        led.off()
        print("  [OK] RGB LED 正常\n")

        # 测试有源蜂鸣器
        print("[TEST] 有源蜂鸣器...")
        buzzer = Buzzer()
        buzzer.beep(0.15)  # 短响
        time.sleep(0.1)
        buzzer.beep(0.3)   # 长响
        buzzer.cleanup()
        print("  [OK] 有源蜂鸣器正常\n")

        # 测试触摸传感器
        print("[TEST] 触摸传感器 (请触摸 TTP223)...")
        touch = TouchSensor()
        start = time.time()
        touched = False
        while time.time() - start < 5:
            if touch.is_pressed():
                print("  >> 检测到触摸!")
                touched = True
                break
            time.sleep(0.05)

        if touched:
            print("  [OK] 触摸传感器正常\n")
        else:
            print("  [INFO] 5 秒内未检测到触摸, 若已触摸请检查接线\n")

    except KeyboardInterrupt:
        print("\n[INFO] 自检中断")
    finally:
        led.off()
        led.cleanup()
        gpio_cleanup()
