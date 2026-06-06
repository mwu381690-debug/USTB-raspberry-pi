#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
传感器模块
=========
- DHT11 温湿度传感器
- PCF8591 AD/DA 转换器 (光敏 CH0 + NTC 温度 CH1)
"""

import time
import math
import threading

# ── I2C ────────────────────────────────────────────────────
try:
    import smbus2
    _HAS_SMBUS2 = True
except ImportError:
    _HAS_SMBUS2 = False
    print("[WARN] smbus2 not installed. Run: pip install smbus2")

# ── DHT11 ───────────────────────────────────────────────────
try:
    import adafruit_dht
    import board
    _HAS_ADAFRUIT_DHT = True
except ImportError:
    _HAS_ADAFRUIT_DHT = False
    print("[WARN] adafruit-circuitpython-dht not installed.")
    print("       Run: pip install adafruit-circuitpython-dht")


class PCF8591Reader:
    """PCF8591 AD/DA 模块读取器 (I2C)"""

    def __init__(self, bus_num=1, addr=0x48):
        if not _HAS_SMBUS2:
            raise ImportError("PCF8591 需要 smbus2: pip install smbus2")
        self.bus = smbus2.SMBus(bus_num)
        self.addr = addr

        # NTC 参数 (从 config 导入或使用默认值)
        self.ntc_r0      = 10000
        self.ntc_beta    = 3950
        self.ntc_t0      = 298.15
        self.ntc_r_fixed = 10000
        self.ntc_vcc     = 5.0

        # 初始化 ADC (写控制字节)
        try:
            self.bus.write_byte(self.addr, 0x40)
        except Exception as e:
            print(f"[ERROR] PCF8591 初始化失败: {e}")
            raise

    def _read_channel(self, channel):
        """读取指定 ADC 通道 (0~3) 的原始数值"""
        try:
            # 选择通道
            ctrl = 0x40 | channel
            self.bus.write_byte(self.addr, ctrl)
            # 第一次读取是上一次转换结果, 再读一次得到当前值
            self.bus.read_byte(self.addr)
            value = self.bus.read_byte(self.addr)
            return value
        except Exception as e:
            print(f"[ERROR] PCF8591 读取通道 {channel} 失败: {e}")
            return 0

    def read_photoresistor(self):
        """读取光敏传感器原始值 (0~255)"""
        return self._read_channel(PCF8591_CH_PHOTORESISTOR)

    def read_ntc_raw(self):
        """读取 NTC 通道原始值 (0~255)"""
        return self._read_channel(PCF8591_CH_NTC)

    def read_ntc_temperature(self):
        """
        从 NTC 热敏电阻计算温度 (°C)

        电路: VCC → NTC → ADC输入 → 固定电阻 → GND
               Vadc = VCC * R_fixed / (R_ntc + R_fixed)
               R_ntc = R_fixed * (VCC/Vadc - 1)

               Beta 公式:
               1/T = 1/T0 + (1/Beta) * ln(R_ntc / R0)
               T = 1 / (1/T0 + ln(R_ntc/R0) / Beta)
        """
        raw = self.read_ntc_raw()
        if raw <= 0:
            return 0.0

        # 计算 ADC 电压
        v_adc = (raw / 255.0) * self.ntc_vcc

        # 避免除零
        if v_adc <= 0.01:
            v_adc = 0.01

        # 计算 NTC 电阻
        try:
            r_ntc = self.ntc_r_fixed * (self.ntc_vcc / v_adc - 1.0)
        except ZeroDivisionError:
            return 0.0

        if r_ntc <= 0:
            return 0.0

        # Beta 公式
        try:
            temp_k = 1.0 / (1.0 / self.ntc_t0 + math.log(r_ntc / self.ntc_r0) / self.ntc_beta)
        except (ValueError, ZeroDivisionError):
            return 0.0

        temp_c = temp_k - 273.15
        return round(temp_c, 1)

    def read_light_percentage(self):
        """
        读取光敏传感器并映射为百分比 (0~100%)

        常见模块: 光线越强, 光敏电阻越小, ADC 读数越高
        简单线性映射 (可根据实际模块调整)
        """
        raw = self.read_photoresistor()
        pct = min(100.0, max(0.0, (raw / 255.0) * 100.0))
        return round(pct, 1)

    def read_joystick_x(self):
        """读取摇杆 VRx (PCF8591 CH2), 返回 0~255, 中心≈128"""
        return self._read_channel(2)

    def read_joystick_y(self):
        """读取摇杆 VRy (PCF8591 CH3), 返回 0~255, 中心≈128"""
        return self._read_channel(3)


# 从 config 导入通道常量 (避免循环引用)
PCF8591_CH_PHOTORESISTOR = 0
PCF8591_CH_NTC = 1


class DHT11Reader:
    """
    DHT11 温湿度传感器读取器

    使用 adafruit-circuitpython-dht 库 (推荐),
    如果不可用则使用 RPi.GPIO 简单实现作为备选。
    """

    def __init__(self, pin=4):
        self.pin = pin
        self._adafruit_device = None

        if _HAS_ADAFRUIT_DHT:
            try:
                # 将 GPIO 编号映射到 board 对象
                pin_map = {
                    4:  board.D4,
                    17: board.D17,
                    18: board.D18,
                    22: board.D22,
                    23: board.D23,
                    24: board.D24,
                    25: board.D25,
                    27: board.D27,
                }
                board_pin = pin_map.get(pin, board.D4)
                self._adafruit_device = adafruit_dht.DHT11(board_pin, use_pulseio=False)
                print(f"[INFO] DHT11 使用 adafruit 库 (GPIO{pin})")
            except Exception as e:
                print(f"[WARN] DHT11 adafruit 初始化失败: {e}, 将使用 RPi.GPIO 备选方案")
                self._adafruit_device = None

        if self._adafruit_device is None:
            self._init_rpigpio_fallback()

    def _init_rpigpio_fallback(self):
        """初始化 RPi.GPIO 备选方案"""
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            self._use_fallback = True
            print(f"[INFO] DHT11 使用 RPi.GPIO 备选方案 (GPIO{self.pin})")
        except ImportError:
            self._use_fallback = False
            print("[ERROR] DHT11 无法初始化: 请安装 RPi.GPIO 或 adafruit-circuitpython-dht")
            raise ImportError("DHT11 需要 RPi.GPIO 或 adafruit-circuitpython-dht")

    def read(self):
        """读取温湿度, 返回 (temperature_c, humidity, success)"""
        if self._adafruit_device is not None:
            return self._read_adafruit()
        elif self._use_fallback:
            return self._read_fallback()
        else:
            return 0.0, 0.0, False

    def _read_adafruit(self):
        """使用 adafruit 库读取"""
        try:
            temp = self._adafruit_device.temperature
            hum  = self._adafruit_device.humidity
            if temp is not None and hum is not None:
                return round(temp, 1), round(hum, 1), True
            return 0.0, 0.0, False
        except RuntimeError as e:
            # DHT11 读取失败很常见 (时序问题), 静默重试
            return 0.0, 0.0, False
        except Exception as e:
            print(f"[ERROR] DHT11 read: {e}")
            return 0.0, 0.0, False

    def _read_fallback(self):
        """
        使用 RPi.GPIO 手动实现 DHT11 协议

        注: 在 Linux 多任务环境下微秒级时序可能不精确,
        因此读取成功率约 70~80%。推荐使用 adafruit 库。
        """
        import RPi.GPIO as GPIO

        pin = self.pin
        data = []

        try:
            # 步骤 1: 主机发送起始信号 (拉低 >18ms)
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.LOW)
            time.sleep(0.02)   # 20ms
            GPIO.output(pin, GPIO.HIGH)
            time.sleep(0.00004)  # 40μs

            # 步骤 2: 切换到输入模式读取 DHT11 响应
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

            # 等待 DHT11 拉低 (~80μs)
            timeout = 10000
            while GPIO.input(pin) == GPIO.HIGH:
                timeout -= 1
                if timeout <= 0:
                    return 0.0, 0.0, False

            # 等待 DHT11 拉高 (~80μs)
            timeout = 10000
            while GPIO.input(pin) == GPIO.LOW:
                timeout -= 1
                if timeout <= 0:
                    return 0.0, 0.0, False

            timeout = 10000
            while GPIO.input(pin) == GPIO.HIGH:
                timeout -= 1
                if timeout <= 0:
                    return 0.0, 0.0, False

            # 步骤 3: 读取 40 bits 数据
            for _ in range(40):
                # 等待低电平结束
                timeout = 10000
                while GPIO.input(pin) == GPIO.LOW:
                    timeout -= 1
                    if timeout <= 0:
                        return 0.0, 0.0, False

                # 测量高电平持续时间
                length = 0
                timeout = 10000
                while GPIO.input(pin) == GPIO.HIGH:
                    length += 1
                    timeout -= 1
                    if timeout <= 0:
                        return 0.0, 0.0, False

                # >40μs ≈ 1, <40μs ≈ 0
                data.append(1 if length > 8 else 0)

            # 解析数据
            bytes_data = []
            for i in range(5):
                byte_val = 0
                for j in range(8):
                    byte_val = (byte_val << 1) | data[i * 8 + j]
                bytes_data.append(byte_val)

            # 校验
            if (bytes_data[0] + bytes_data[1] + bytes_data[2] + bytes_data[3]) & 0xFF != bytes_data[4]:
                return 0.0, 0.0, False

            humidity    = bytes_data[0] + bytes_data[1] * 0.1
            temperature = bytes_data[2] + bytes_data[3] * 0.1

            return round(temperature, 1), round(humidity, 1), True

        except Exception as e:
            print(f"[ERROR] DHT11 fallback read: {e}")
            return 0.0, 0.0, False
        finally:
            # 恢复引脚为输入 (避免干扰下次读取)
            try:
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            except Exception:
                pass


class SensorManager:
    """
    传感器管理器
    - 后台线程定期读取所有传感器
    - 线程安全地提供最新数据
    """

    def __init__(self, dht11_pin=4, pcf8591_addr=0x48, pcf8591_bus=1):
        self._lock = threading.Lock()

        # 传感器实例
        self.dht11 = DHT11Reader(pin=dht11_pin)
        self.pcf8591 = PCF8591Reader(bus_num=pcf8591_bus, addr=pcf8591_addr)

        # 最新传感器数据
        self._data = {
            'dht11_temp':     0.0,
            'dht11_humidity': 0.0,
            'light_raw':      0,
            'light_pct':      0.0,
            'ntc_temp':       0.0,
            'timestamp':      time.time(),
        }

        # 线程控制
        self._running = False
        self._thread = None

    def start(self, interval=2.0):
        """启动后台传感器读取线程"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, args=(interval,), daemon=True)
        self._thread.start()
        print("[INFO] 传感器后台线程已启动")

    def stop(self):
        """停止后台线程"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)

    def _run(self, interval):
        """后台线程主循环"""
        while self._running:
            try:
                # 读取 DHT11
                temp, hum, ok = self.dht11.read()

                # 读取 PCF8591
                light_raw = self.pcf8591.read_photoresistor()
                light_pct = self.pcf8591.read_light_percentage()
                ntc_temp  = self.pcf8591.read_ntc_temperature()

                # 线程安全地更新数据
                with self._lock:
                    if ok:
                        self._data['dht11_temp'] = temp
                        self._data['dht11_humidity'] = hum
                    self._data['light_raw']  = light_raw
                    self._data['light_pct']  = light_pct
                    self._data['ntc_temp']   = ntc_temp
                    self._data['timestamp']  = time.time()

            except Exception as e:
                print(f"[ERROR] 传感器读取异常: {e}")

            time.sleep(interval)

    def get_data(self):
        """获取最新的传感器数据 (线程安全)"""
        with self._lock:
            return dict(self._data)


# ============================================================
# 自检: 直接运行此文件可测试传感器
# ============================================================

if __name__ == '__main__':
    print("=== 传感器模块自检 ===\n")

    # 测试 PCF8591
    print("[TEST] PCF8591...")
    try:
        pcf = PCF8591Reader()
        print(f"  光敏原始值: {pcf.read_photoresistor()}")
        print(f"  光强百分比: {pcf.read_light_percentage()}%")
        print(f"  NTC 原始值: {pcf.read_ntc_raw()}")
        print(f"  NTC 温度:   {pcf.read_ntc_temperature()}°C")
        print("  [OK] PCF8591 正常\n")
    except Exception as e:
        print(f"  [FAIL] {e}\n")

    # 测试 DHT11
    print("[TEST] DHT11...")
    try:
        dht = DHT11Reader(pin=4)
        for i in range(3):
            temp, hum, ok = dht.read()
            if ok:
                print(f"  温度: {temp}°C, 湿度: {hum}%")
            else:
                print(f"  读取失败 (尝试 {i+1}/3)")
            time.sleep(1)
        print("  [OK] DHT11 测试完成\n")
    except Exception as e:
        print(f"  [FAIL] {e}\n")

    # 测试 SensorManager
    print("[TEST] SensorManager...")
    try:
        mgr = SensorManager()
        mgr.start(interval=2.0)
        time.sleep(5)
        data = mgr.get_data()
        print(f"  数据: {data}")
        mgr.stop()
        print("  [OK] SensorManager 正常\n")
    except Exception as e:
        print(f"  [FAIL] {e}\n")
