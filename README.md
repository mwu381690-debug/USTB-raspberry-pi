# 树莓派情绪检测实验

## 硬件清单 & 接线表

| 元器件 | 元器件引脚 | → | 转接板丝印 | 板上位置 |
|--------|-----------|-----|-----------|---------|
| 🟢 普通绿色 LED | + (阳极, 串 220Ω) | → | **G16** | 左列第2 |
| (系统运行灯) | - (阴极) | → | **GND** | |
| | | | | |
| 🌈 RGB 三色 LED | R | → | **G17** | 左列第1 |
| (检测闪烁) | G | → | **G27** | 右列第10 |
| | B | → | **G22** | 右列第5 |
| | 公共 GND | → | **GND** | |
| | | | | |
| 📢 有源蜂鸣器 | IN | → | **G18** | 右列第1 |
| | VCC | → | **5V** | |
| | GND | → | **GND** | |
| | | | | |
| 👆 TTP223 触摸 | SIG | → | **G23** | 右列第6 |
| | VCC | → | **3.3V** | |
| | GND | → | **GND** | |
| | | | | |
| 🕹️ 双轴摇杆 | VRx | → | PCF8591 **CH2** | AIN2 |
| | VRy | → | PCF8591 **CH3** | AIN3 |
| | SW | → | **G13** | 左列第3 |
| | VCC | → | **3.3V** | |
| | GND | → | **GND** | |
| | | | | |
| 🌡️ DHT11 | DATA | → | **G4** | 左列第7 |
| | VCC | → | **5V** | |
| | GND | → | **GND** | |
| | | | | |
| 📊 PCF8591 | SDA | → | **SDA** | 右列第12 |
| | SCL | → | **SCL** | 右列第11 |
| | VCC | → | **5V** | |
| | GND | → | **GND** | |
| | | | | |
| 📺 LCD1602 I2C | SDA | → | **SDA** | 与 PCF8591 共线 |
| | SCL | → | **SCL** | 与 PCF8591 共线 |
| | VCC | → | **5V** | |
| | GND | → | **GND** | |
| | | | | |
| 📷 USB 摄像头 | USB | → | 树莓派 USB 口 | |

> **I2C 地址**: PCF8591=0x48, LCD1602=0x27 (用 `i2cdetect -y 1` 确认)

## GIF 文件准备

将以下 GIF 放入 `git/` 目录（若没有则显示占位提示）：

```
git/
├── idle.gif       # 待机动画
├── happy.gif      # 开心动画
├── comfort.gif    # 安慰动画 (sad 时使用)
├── flower.gif     # 送花动画 (angry 时使用)
└── surprise.gif   # 惊讶动画
```

## 安装 & 运行

```bash
# 系统依赖
sudo apt install -y python3-pip i2c-tools libgpiod2
sudo raspi-config nonint do_i2c 0

# Python 依赖
cd ~/emotion_detector
pip install -r requirements.txt

# 各模块自检
python3 gpio_control.py    # LED + 蜂鸣器 + 触摸
python3 sensors.py         # DHT11 + PCF8591 + 摇杆
python3 lcd1602.py         # LCD1602
python3 emotion.py         # 摄像头 + 情绪检测
python3 desktop_pet.py     # 桌宠 (方向键移动, 1-5切换)

# 完整运行
python3 main.py
```

## 操作说明

| 操作 | 效果 |
|------|------|
| 🕹️ 推动摇杆 | **实时移动** GIF 在屏幕上的位置 |
| 👆 触摸 TTP223 | **触发情绪检测** (摄像头拍照+识别) |
| 检测完成 | GIF **在原位置**切换为对应情绪的动画 |
| 再次触摸 | **重新检测**，新 GIF 仍在当前位置显示 |
| Ctrl+C | 安全退出 |

> GIF 不会自动消失或恢复，一直保持当前情绪，直到你再次触摸检测。

## 运行流程

```
上电 → 🟢绿灯常亮 → LCD显示"Emotion Robot/Ready"
  → HDMI显示 idle.gif + 摄像头预览 + 状态栏
  → 终端每2秒打印温湿度光照
  → 摇杆拖动 GIF 位置
  → 触摸 TTP223 → 🌈RGB红绿交替 → 拍照识别情绪
  → 蜂鸣器鸣叫(sad/angry) → GIF切换 + LCD更新
  → 保持当前状态，等待下次触摸
```

## 情绪映射

| 情绪 | GIF | LCD 第1行 | LCD 第2行 | 蜂鸣器 |
|------|-----|----------|----------|--------|
| happy | happy.gif | Emotion:Happy | Keep Smiling! | 关 |
| sad | comfort.gif | Emotion:Sad | Cheer Up! | **开** |
| angry | flower.gif | Emotion:Angry | Stay Calm! | **开** |
| surprise | surprise.gif | Emotion:Wow! | Amazing! | 关 |
| neutral | idle.gif | Emotion:Neutral | Ready | 关 |
