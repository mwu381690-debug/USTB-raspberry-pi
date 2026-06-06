#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
树莓派情绪检测实验 - 主程序
============================

系统功能:
  (1) 环境监测: DHT11 温湿度 + PCF8591 光敏, 终端每 2s 输出
  (2) 情绪识别: USB 摄像头 + OpenCV + FER
  (3) 桌宠互动: HDMI 显示 GIF 动画, 摇杆拖动位置
  (4) LCD 状态显示: LCD1602 I2C
  (5) 触摸启动: TTP223 触发情绪检测
  (6) LED 指示: 绿色常亮=运行, RGB 红绿交替=检测中
  (7) 蜂鸣器: sad/angry 时触发间歇 Beep

运行:
    python3 main.py
"""

import os
import sys
import time
import signal
import threading
from datetime import datetime

# ── 项目模块 ─────────────────────────────────────────────
from config import (
    GREEN_LED_PIN,
    LED_RED_PIN, LED_GREEN_PIN, LED_BLUE_PIN,
    BUZZER_PIN, TOUCH_PIN, DHT11_PIN,
    JOYSTICK_SW_PIN, JOYSTICK_DEADZONE, JOYSTICK_SPEED,
    LCD1602_ADDR, PCF8591_ADDR, I2C_BUS,
    CAMERA_INDEX, DETECTION_TIMEOUT,
    SENSOR_READ_INTERVAL, TERMINAL_PRINT_INTERVAL,
    DISPLAY_FULLSCREEN, DISPLAY_WIDTH, DISPLAY_HEIGHT,
    EMOTION_LCD_MAP, EMOTION_STATUS_MAP, BUZZER_EMOTIONS,
)

from gpio_control import SimpleLED, RGBLED, Buzzer, TouchSensor, gpio_setup, gpio_cleanup
from sensors import SensorManager
from lcd1602 import LCD1602
from emotion import EmotionDetector
from desktop_pet import DesktopPet, JoystickReader
from emotion_logger import EmotionLogger
from web_dashboard import WebDashboard, update_state, update_sensor_data, set_logger


# ============================================================
# 终端输出辅助
# ============================================================

def print_sensor_data(data):
    """格式化打印传感器数据到终端"""
    ts = datetime.fromtimestamp(data['timestamp']).strftime('%H:%M:%S')
    print("=" * 40)
    print(f"Time: {ts}\n")
    print(f"Temperature : {data['dht11_temp']} C")
    print(f"Humidity    : {data['dht11_humidity']} %")
    print(f"Light Level : {data['light_raw']}")
    print("=" * 40)


def update_lcd_emotion(lcd, emotion):
    """根据情绪更新 LCD 显示"""
    lines = EMOTION_LCD_MAP.get(emotion, ("Emotion:?", "Ready"))
    lcd.write_lines(lines[0], lines[1])


# ============================================================
# 主程序
# ============================================================

def main():
    print("\n" + "=" * 50)
    print("  树莓派情绪检测实验")
    print("  Raspberry Pi Emotion Detection System")
    print("=" * 50 + "\n")

    # ──────────────────────────────────────────────────────
    # Step 1: GPIO 初始化
    # ──────────────────────────────────────────────────────
    print("[Step 1/5] 初始化 GPIO...")
    gpio_setup()

    # ──────────────────────────────────────────────────────
    # Step 2: 硬件初始化
    # ──────────────────────────────────────────────────────
    print("[Step 2/5] 初始化硬件外设...")

    # 普通绿色 LED (系统运行指示灯)
    try:
        status_led = SimpleLED(GREEN_LED_PIN)
        status_led.on()
        print("  [OK] 绿色运行指示灯 (G16)")
    except Exception as e:
        print(f"  [FAIL] 运行指示灯: {e}")
        status_led = None

    # RGB 三色 LED (检测状态)
    try:
        rgb_led = RGBLED(LED_RED_PIN, LED_GREEN_PIN, LED_BLUE_PIN)
        rgb_led.off()
        print("  [OK] RGB 三色 LED")
    except Exception as e:
        print(f"  [FAIL] RGB LED: {e}")
        rgb_led = None

    # 有源蜂鸣器
    try:
        buzzer = Buzzer(BUZZER_PIN)
        print("  [OK] 有源蜂鸣器 (G18)")
    except Exception as e:
        print(f"  [FAIL] 蜂鸣器: {e}")
        buzzer = None

    # 触摸传感器
    try:
        touch = TouchSensor(TOUCH_PIN)
        print("  [OK] 触摸传感器 (G23)")
    except Exception as e:
        print(f"  [FAIL] 触摸传感器: {e}")
        touch = None

    # LCD1602
    try:
        lcd = LCD1602(addr=LCD1602_ADDR, bus_num=I2C_BUS)
        lcd.write_lines("Emotion Robot", "Ready")
        print("  [OK] LCD1602")
    except Exception as e:
        print(f"  [FAIL] LCD1602: {e}")
        print("  [提示] 用 i2cdetect -y 1 检查地址")
        lcd = None

    # ──────────────────────────────────────────────────────
    # Step 3: 传感器初始化 + 启动后台线程
    # ──────────────────────────────────────────────────────
    print("[Step 3/5] 初始化传感器...")

    sensors = None
    joystick = None
    try:
        sensors = SensorManager(
            dht11_pin=DHT11_PIN,
            pcf8591_addr=PCF8591_ADDR,
            pcf8591_bus=I2C_BUS
        )
        sensors.start(interval=SENSOR_READ_INTERVAL)
        time.sleep(3)  # 等待第一批传感器数据

        # 摇杆读取器 (复用 PCF8591 实例)
        joystick = JoystickReader(
            pcf8591=sensors.pcf8591,
            sw_pin=JOYSTICK_SW_PIN,
            deadzone=JOYSTICK_DEADZONE,
            speed=JOYSTICK_SPEED
        )
        print("  [OK] 传感器 + 摇杆就绪")
    except Exception as e:
        print(f"  [FAIL] 传感器: {e}")

    # ──────────────────────────────────────────────────────
    # Step 4: 情绪检测器 + 摄像头初始化
    # ──────────────────────────────────────────────────────
    print("[Step 4/5] 初始化情绪检测器...")

    detector = None
    try:
        detector = EmotionDetector(camera_index=CAMERA_INDEX)
        if detector.open_camera():
            print("  [OK] 摄像头 + 情绪检测器就绪")
        else:
            print("  [WARN] 摄像头不可用, 情绪检测功能受限")
    except Exception as e:
        print(f"  [FAIL] 情绪检测器: {e}")

    # ──────────────────────────────────────────────────────
    # Step 5: HDMI 桌宠显示初始化
    # ──────────────────────────────────────────────────────
    print("[Step 5/5] 初始化 HDMI 桌宠显示...")

    pet = None
    try:
        pet = DesktopPet(
            fullscreen=DISPLAY_FULLSCREEN,
            width=DISPLAY_WIDTH,
            height=DISPLAY_HEIGHT
        )
        pet.set_emotion('neutral', EMOTION_STATUS_MAP['neutral'])
        print("  [OK] HDMI 桌宠显示就绪")
    except Exception as e:
        print(f"  [FAIL] HDMI 显示: {e}")

    # ──────────────────────────────────────────────────────
    # 数据库 + Web 仪表盘
    # ──────────────────────────────────────────────────────
    logger = None
    dashboard = None
    detection_count = 0

    try:
        logger = EmotionLogger()
        set_logger(logger)
        print("  [OK] SQLite 数据库就绪")
    except Exception as e:
        print(f"  [WARN] 数据库初始化失败: {e}")

    try:
        dashboard = WebDashboard(host='0.0.0.0', port=5000)
        dashboard.start()
        print("  [OK] Web 仪表盘就绪")
    except Exception as e:
        print(f"  [WARN] Web 仪表盘启动失败: {e}")

    # 定期记录传感器快照变量
    last_sensor_log = time.time()

    print("\n" + "=" * 50)
    print("  系统就绪!")
    print("  摇杆: 移动 GIF 位置")
    print("  触摸 TTP223: 触发情绪检测")
    print("  Web 仪表盘: http://<树莓派IP>:5000")
    print("  按 Ctrl+C 退出")
    print("=" * 50 + "\n")

    # ──────────────────────────────────────────────────────
    # 主循环
    # ──────────────────────────────────────────────────────
    # 状态: 'idle' | 'detecting' | 'displaying'
    # 注意: 没有自动恢复! displaying 一直保持到下次触摸
    state = 'idle'
    state_timer = 0.0
    last_terminal_print = time.time()
    last_joystick_read = time.time()
    last_sensor_data = {}
    current_emotion = 'neutral'

    try:
        while True:
            now = time.time()

            # ── Pygame 事件处理 ──
            if pet:
                if not pet.handle_events():
                    break

            # ── 摇杆读取 (控制 GIF 移动) ──
            if joystick and pet and now - last_joystick_read >= 0.05:
                dx, dy, sw_pressed = joystick.read()
                if dx != 0 or dy != 0:
                    pet.move_gif(dx, dy)
                last_joystick_read = now

            # ── 传感器数据 ──
            if sensors:
                last_sensor_data = sensors.get_data()
                # 更新 Web 仪表盘传感器数据
                update_sensor_data(last_sensor_data)
                # 每 30 秒记录一次传感器快照
                if now - last_sensor_log >= 30:
                    if logger:
                        logger.log_sensor_snapshot(last_sensor_data)
                    last_sensor_log = now

            # ── 终端打印 (每 2 秒) ──
            if now - last_terminal_print >= TERMINAL_PRINT_INTERVAL:
                if last_sensor_data:
                    print_sensor_data(last_sensor_data)
                last_terminal_print = now

            # ── 摄像头预览帧 ──
            camera_frame = None
            if detector:
                camera_frame = detector.get_preview_frame()

            # ── LCD 更新 ──
            if lcd:
                if state == 'idle' and last_sensor_data:
                    if int(now) % 4 == 0:
                        line1 = f"T:{last_sensor_data['dht11_temp']}C "
                        line1 += f"H:{last_sensor_data['dht11_humidity']}%"
                        line2 = f"L:{last_sensor_data['light_raw']} "
                        line2 += f"NTC:{last_sensor_data['ntc_temp']}C"
                        lcd.write_lines(line1[:16], line2[:16])
                elif state == 'displaying':
                    if int(now) % 2 == 0:
                        update_lcd_emotion(lcd, current_emotion)

            # ── 检查触摸 (任何状态都响应) ──
            if touch and touch.is_pressed():
                # 防止重复触发 (去抖)
                if state != 'detecting':
                    print("\n[TOUCH] >> 触摸检测到! 开始情绪识别...\n")
                    state = 'detecting'
                    state_timer = now

                    # LED 交替
                    if rgb_led:
                        rgb_led.start_alternating(interval=0.3)

                    # LCD 提示
                    if lcd:
                        lcd.write_lines("Detecting...", "Look at camera!")

            # ── 检测中 ──
            if state == 'detecting':
                if detector:
                    result = detector.detect_emotion()
                    if result['face_found']:
                        current_emotion = result['emotion']
                        print(f"[RESULT] 情绪: {current_emotion}, "
                              f"置信度: {result['confidence']}, "
                              f"方法: {result['method']}")
                        if result.get('fer_full'):
                            print(f"         详细: {result['fer_full']}")

                        # 记录到数据库
                        detection_count += 1
                        if logger:
                            logger.log_emotion(
                                emotion=current_emotion,
                                confidence=result['confidence'],
                                method=result['method'],
                                fer_detail=result.get('fer_full')
                            )
                            if last_sensor_data:
                                logger.log_sensor_snapshot(last_sensor_data)

                        # 更新 Web 状态
                        status_text = EMOTION_STATUS_MAP.get(
                            current_emotion, EMOTION_STATUS_MAP['neutral'])
                        update_state(current_emotion, status_text, detection_count)

                        # 切换到显示状态 (保持 GIF 原位置不变)
                        state = 'displaying'

                        # 停止 LED 交替
                        if rgb_led:
                            rgb_led.stop_alternating()

                        # 更新 LCD
                        if lcd:
                            update_lcd_emotion(lcd, current_emotion)

                        # 更新桌宠 GIF (位置不变)
                        if pet:
                            status_text = EMOTION_STATUS_MAP.get(
                                current_emotion,
                                EMOTION_STATUS_MAP['neutral'])
                            pet.set_emotion(current_emotion, status_text)

                        # 蜂鸣器 (sad / angry)
                        if buzzer and current_emotion in BUZZER_EMOTIONS:
                            print(f"[BUZZER] 触发蜂鸣器提示音")
                            buzzer.play_pattern()

                    elif now - state_timer > DETECTION_TIMEOUT:
                        # 超时无脸 → 回到之前的状态
                        print("[TIMEOUT] 检测超时, 未检测到人脸")
                        if rgb_led:
                            rgb_led.stop_alternating()
                        if lcd:
                            lcd.write_lines("No Face Found", "Try Again!")
                        state = 'idle'
                        if pet:
                            pet.set_emotion('neutral',
                                            EMOTION_STATUS_MAP['neutral'])
                else:
                    # 无检测器
                    state = 'idle'
                    if rgb_led:
                        rgb_led.stop_alternating()

            # ── 更新 HDMI 显示 ──
            if pet:
                if state == 'detecting' and detector and camera_frame is not None:
                    last_res = detector.get_last_result()
                    if last_res and last_res.get('face_found'):
                        annotated = detector.annotate_frame(camera_frame, last_res)
                        pet.set_camera_frame(annotated)
                    else:
                        pet.set_camera_frame(camera_frame)
                else:
                    pet.set_camera_frame(camera_frame)

                pet.update()

    except KeyboardInterrupt:
        print("\n\n[INFO] 用户中断 (Ctrl+C)")

    finally:
        # ──────────────────────────────────────────────────
        # 清理
        # ──────────────────────────────────────────────────
        print("\n[清理] 正在关闭系统...")

        if sensors:
            sensors.stop()
            print("  [OK] 传感器线程已停止")

        if detector:
            detector.close_camera()
            print("  [OK] 摄像头已关闭")

        if lcd:
            lcd.clear()
            lcd.write_lines("System", "Shutdown...")
            lcd.close()
            print("  [OK] LCD 已关闭")

        if status_led:
            status_led.off()
            status_led.cleanup()
            print("  [OK] 绿色运行灯已关闭")

        if rgb_led:
            rgb_led.off()
            rgb_led.cleanup()
            print("  [OK] RGB LED 已关闭")

        if buzzer:
            buzzer.cleanup()
            print("  [OK] 蜂鸣器已关闭")

        if dashboard:
            dashboard.stop()
            print("  [OK] Web 仪表盘已关闭")

        if joystick:
            joystick.cleanup()

        gpio_cleanup()
        print("  [OK] GPIO 已清理")

        if pet:
            pet.quit()
            print("  [OK] Pygame 已退出")

        print("\n系统已安全退出。再见! 👋\n")


if __name__ == '__main__':
    main()
