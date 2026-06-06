#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LCD1602 I2C 驱动 (PCF8574 背包)
===============================
支持 16×2 字符 LCD, 通过 I2C 总线控制。

接线: VCC→5V, GND→GND, SDA→GPIO2, SCL→GPIO3
I2C 地址: 常见 0x27 或 0x3F (用 i2cdetect -y 1 确认)
"""

import time

try:
    import smbus2
    _HAS_SMBUS2 = True
except ImportError:
    _HAS_SMBUS2 = False
    print("[WARN] smbus2 not installed. Run: pip install smbus2")


# ── PCF8574 引脚映射 (4-bit mode) ──────────────────────────
# 高 4 位 (D4~D7) 接 PCF8574 的 P4~P7
# EN = P2, RW = P1, RS = P0, BL = P3
# ───────────────────────────────────────────────────────────
LCD_RS = 0x01   # Register Select (0=指令, 1=数据)
LCD_RW = 0x02   # Read/Write     (0=写, 1=读)
LCD_EN = 0x04   # Enable
LCD_BL = 0x08   # Backlight

# LCD 指令
LCD_CMD_CLEAR    = 0x01
LCD_CMD_HOME     = 0x02
LCD_CMD_ENTRY    = 0x06   # 光标右移, 不滚动
LCD_CMD_DISPLAY  = 0x0C   # 显示开, 光标关, 闪烁关
LCD_CMD_FUNCTION = 0x28   # 4-bit, 2 行, 5×8 字体
LCD_CMD_CURSOR   = 0x80   # 设置 DDRAM 地址 (行首)


class LCD1602:
    """LCD1602 I2C 显示器驱动"""

    def __init__(self, addr=0x27, bus_num=1, cols=16, rows=2):
        if not _HAS_SMBUS2:
            raise ImportError("LCD1602 需要 smbus2: pip install smbus2")

        self.addr  = addr
        self.cols  = cols
        self.rows  = rows
        self.bus   = smbus2.SMBus(bus_num)
        self.backlight = True

        # 初始化序列
        self._init_lcd()

    def _write_byte(self, data, mode=0):
        """
        通过 I2C 发送一个字节到 LCD
        mode: 0=指令, 1=数据
        """
        rs = LCD_RS if mode else 0
        bl = LCD_BL if self.backlight else 0

        # 先发高 4 位
        high_nibble = data & 0xF0
        self.bus.write_byte(self.addr, high_nibble | rs | bl | LCD_EN)
        time.sleep(0.0005)
        self.bus.write_byte(self.addr, high_nibble | rs | bl)
        time.sleep(0.0001)

        # 再发低 4 位
        low_nibble = (data << 4) & 0xF0
        self.bus.write_byte(self.addr, low_nibble | rs | bl | LCD_EN)
        time.sleep(0.0005)
        self.bus.write_byte(self.addr, low_nibble | rs | bl)
        time.sleep(0.0001)

    def _init_lcd(self):
        """4-bit 模式初始化序列"""
        time.sleep(0.05)   # 等待 LCD 上电

        bl = LCD_BL if self.backlight else 0

        # 步骤 1: 3 次发送 0x03 (尝试进入 8-bit 模式, 唤醒 LCD)
        for _ in range(3):
            self.bus.write_byte(self.addr, 0x30 | bl | LCD_EN)
            time.sleep(0.0005)
            self.bus.write_byte(self.addr, 0x30 | bl)
            time.sleep(0.005)

        # 步骤 2: 切换到 4-bit 模式
        self.bus.write_byte(self.addr, 0x20 | bl | LCD_EN)
        time.sleep(0.0005)
        self.bus.write_byte(self.addr, 0x20 | bl)
        time.sleep(0.001)

        # 步骤 3: 发送功能设置指令
        self.command(LCD_CMD_FUNCTION)     # 4bit, 2行, 5x8
        self.command(LCD_CMD_DISPLAY)      # 显示开
        self.command(LCD_CMD_CLEAR)        # 清屏
        time.sleep(0.002)
        self.command(LCD_CMD_ENTRY)        # 输入模式
        self.command(LCD_CMD_HOME)         # 光标归位

    def command(self, cmd):
        """发送指令"""
        self._write_byte(cmd, mode=0)

    def write_char(self, char):
        """写入单个字符"""
        self._write_byte(ord(char), mode=1)

    def write_string(self, text):
        """写入字符串"""
        for ch in text:
            self.write_char(ch)

    def clear(self):
        """清屏"""
        self.command(LCD_CMD_CLEAR)
        time.sleep(0.002)

    def home(self):
        """光标归位"""
        self.command(LCD_CMD_HOME)
        time.sleep(0.002)

    def set_cursor(self, col, row):
        """设置光标位置 (col: 0~15, row: 0~1)"""
        addr = col + (0x40 if row == 1 else 0x00)
        self.command(LCD_CMD_CURSOR | addr)

    def write_lines(self, line1, line2=""):
        """
        写入两行文本 (自动截断/补齐到 16 字符)

        用法:
            lcd.write_lines("Hello", "World")
        """
        # 确保每行恰好 16 个字符 (填充空格覆盖残留)
        l1 = line1[:self.cols].ljust(self.cols)
        l2 = line2[:self.cols].ljust(self.cols)

        self.set_cursor(0, 0)
        self.write_string(l1)
        self.set_cursor(0, 1)
        self.write_string(l2)

    def write_centered(self, line1, line2=""):
        """写入居中文本"""
        l1 = line1[:self.cols].center(self.cols)
        l2 = line2[:self.cols].center(self.cols)

        self.set_cursor(0, 0)
        self.write_string(l1)
        self.set_cursor(0, 1)
        self.write_string(l2)

    def backlight_on(self):
        """打开背光"""
        self.backlight = True
        self.bus.write_byte(self.adddr, LCD_BL)

    def backlight_off(self):
        """关闭背光"""
        self.backlight = False
        self.bus.write_byte(self.addr, 0x00)

    def close(self):
        """关闭 I2C 总线"""
        try:
            self.bus.close()
        except Exception:
            pass


# ============================================================
# 自检
# ============================================================

if __name__ == '__main__':
    print("=== LCD1602 自检 ===\n")

    try:
        lcd = LCD1602(addr=0x27)
        print("[OK] LCD1602 初始化成功\n")

        lcd.write_lines("Emotion Robot", "Ready")
        print("  第1行: 'Emotion Robot'")
        print("  第2行: 'Ready'")
        time.sleep(2)

        lcd.write_lines("Emotion:Happy", "Keep Smiling!")
        print("  第1行: 'Emotion:Happy'")
        print("  第2行: 'Keep Smiling!'")
        time.sleep(2)

        lcd.clear()
        print("  [OK] LCD1602 测试完成")
        lcd.close()

    except Exception as e:
        print(f"  [FAIL] {e}")
        print("  提示: 用 i2cdetect -y 1 查看 LCD 地址")
