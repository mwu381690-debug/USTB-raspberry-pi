#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web 仪表盘 (Flask 后台服务)
============================
- 在树莓派上运行, 手机/电脑浏览器访问
- 实时传感器数据 + 情绪检测历史 + 统计图表
- API 返回 JSON, 页面用 Chart.js 渲染
"""

import os
import json
import threading
import time
from datetime import datetime

try:
    from flask import Flask, jsonify, render_template_string, request
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False
    print("[WARN] flask not installed. Run: pip install flask")

# ── 全局数据引用 (由 main.py 注入) ──
_sensor_data = {}
_emotion_logger = None
_emotion_state = {'current': 'neutral', 'status_text': '', 'detection_count': 0}

app = Flask(__name__)

# ── HTML 模板 ──
DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Emotion Robot Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background:#0d1117; color:#c9d1d9; min-height:100vh; }
  .header { background:#161b22; padding:14px 20px; border-bottom:1px solid #30363d; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; }
  .header h1 { font-size:1.3em; color:#58a6ff; }
  .header .time { font-size:0.85em; color:#8b949e; }
  .container { max-width:1200px; margin:0 auto; padding:16px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:16px; }
  .card { background:#161b22; border:1px solid #30363d; border-radius:10px; padding:16px; text-align:center; }
  .card .value { font-size:2em; font-weight:700; margin:6px 0; }
  .card .label { font-size:0.8em; color:#8b949e; text-transform:uppercase; letter-spacing:0.5px; }
  .happy .value { color:#3fb950; } .sad .value { color:#58a6ff; }
  .angry .value { color:#f85149; } .surprise .value { color:#d2a800; }
  .neutral .value { color:#8b949e; }
  .grid-2 { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }
  .panel { background:#161b22; border:1px solid #30363d; border-radius:10px; padding:16px; }
  .panel h3 { font-size:1em; margin-bottom:12px; color:#58a6ff; }
  .history { max-height:300px; overflow-y:auto; }
  .history table { width:100%; border-collapse:collapse; font-size:0.85em; }
  .history th { text-align:left; padding:8px 6px; border-bottom:1px solid #30363d; color:#8b949e; }
  .history td { padding:6px; border-bottom:1px solid #21262d; }
  .history tr:hover { background:#1c2128; }
  .badge { display:inline-block; padding:2px 8px; border-radius:10px; font-size:0.8em; font-weight:600; }
  .badge-happy { background:#1b3a1b; color:#3fb950; }
  .badge-sad { background:#1a2e3a; color:#58a6ff; }
  .badge-angry { background:#3a1b1b; color:#f85149; }
  .badge-surprise { background:#3a351b; color:#d2a800; }
  .badge-neutral { background:#1c2128; color:#8b949e; }
  .badge-fear { background:#2e1a3a; color:#bc8cff; }
  .badge-disgust { background:#3a2a1b; color:#d29922; }
  canvas { max-height:260px; }
  @media (max-width:768px) { .grid-2 { grid-template-columns:1fr; } }
</style>
</head>
<body>
<div class="header">
  <h1>🤖 Emotion Robot Dashboard</h1>
  <span class="time" id="clock">--</span>
</div>
<div class="container">

  <!-- 实时传感器卡片 -->
  <div class="cards" id="sensor-cards">
    <div class="card"><div class="label">🌡️ 温度</div><div class="value neutral" id="val-temp">--</div></div>
    <div class="card"><div class="label">💧 湿度</div><div class="value neutral" id="val-hum">--</div></div>
    <div class="card"><div class="label">☀️ 光照</div><div class="value neutral" id="val-light">--</div></div>
    <div class="card"><div class="label">📊 NTC 温度</div><div class="value neutral" id="val-ntc">--</div></div>
    <div class="card"><div class="label">😊 当前情绪</div><div class="value neutral" id="val-emotion">--</div></div>
    <div class="card"><div class="label">🔢 今日检测</div><div class="value neutral" id="val-count">0</div></div>
  </div>

  <!-- 图表区 -->
  <div class="grid-2">
    <div class="panel"><h3>📊 情绪分布 (今日)</h3><canvas id="chart-emotion"></canvas></div>
    <div class="panel"><h3>📈 温湿度趋势</h3><canvas id="chart-sensor"></canvas></div>
  </div>

  <!-- 检测历史 -->
  <div class="panel">
    <h3>📋 检测历史</h3>
    <div class="history"><table id="history-table"><thead><tr><th>时间</th><th>情绪</th><th>置信度</th><th>方法</th></tr></thead><tbody></tbody></table></div>
  </div>

</div>
<script>
const EMOTION_CLASS = {happy:'happy',sad:'sad',angry:'angry',surprise:'surprise',neutral:'neutral',fear:'fear',disgust:'disgust'};
const EMOTION_COLOR = {happy:'#3fb950',sad:'#58a6ff',angry:'#f85149',surprise:'#d2a800',neutral:'#8b949e',fear:'#bc8cff',disgust:'#d29922'};

let chartEmotion, chartSensor;

function updateClock() {
  document.getElementById('clock').textContent = new Date().toLocaleString('zh-CN');
}
setInterval(updateClock, 1000);
updateClock();

async function fetchData() {
  try {
    const [summary, sensor, history] = await Promise.all([
      fetch('/api/summary').then(r => r.json()),
      fetch('/api/sensor').then(r => r.json()),
      fetch('/api/history?limit=20').then(r => r.json())
    ]);

    // 传感器卡片
    document.getElementById('val-temp').textContent = (sensor.dht11_temp||0) + '°C';
    document.getElementById('val-hum').textContent = (sensor.dht11_humidity||0) + '%';
    document.getElementById('val-light').textContent = sensor.light_raw || '--';
    document.getElementById('val-ntc').textContent = (sensor.ntc_temp||0) + '°C';

    // 情绪卡片
    let emo = summary.latest_emotion || 'neutral';
    let emoEl = document.getElementById('val-emotion');
    emoEl.textContent = emo;
    emoEl.className = 'value ' + (EMOTION_CLASS[emo]||'neutral');
    document.getElementById('val-count').textContent = summary.total_detections || 0;

    // 情绪分布饼图
    let breakdown = summary.breakdown || {};
    let labels = Object.keys(breakdown);
    let values = Object.values(breakdown);
    let colors = labels.map(l => EMOTION_COLOR[l]||'#8b949e');
    if (!chartEmotion) {
      chartEmotion = new Chart(document.getElementById('chart-emotion'), {
        type:'doughnut', data:{labels,datasets:[{data:values,backgroundColor:colors}]},
        options:{plugins:{legend:{position:'bottom',labels:{color:'#c9d1d9'}}}}
      });
    } else {
      chartEmotion.data.labels = labels;
      chartEmotion.data.datasets[0].data = values;
      chartEmotion.data.datasets[0].backgroundColor = colors;
      chartEmotion.update();
    }

    // 温湿度趋势
    let sdata = sensor.history || [];
    let sLabels = sdata.map(d=>d.timestamp?.slice(11,19)||'').reverse();
    let temps = sdata.map(d=>d.temp).reverse();
    let hums = sdata.map(d=>d.humidity).reverse();
    if (!chartSensor) {
      chartSensor = new Chart(document.getElementById('chart-sensor'), {
        type:'line', data:{labels:sLabels,datasets:[
          {label:'温度 °C',data:temps,borderColor:'#f85149',tension:0.3,pointRadius:0},
          {label:'湿度 %',data:hums,borderColor:'#58a6ff',tension:0.3,pointRadius:0}]},
        options:{scales:{x:{ticks:{color:'#8b949e'}},y:{ticks:{color:'#8b949e'}}},
          plugins:{legend:{labels:{color:'#c9d1d9'}}}}
      });
    } else {
      chartSensor.data.labels = sLabels;
      chartSensor.data.datasets[0].data = temps;
      chartSensor.data.datasets[1].data = hums;
      chartSensor.update();
    }

    // 检测历史
    let tbody = document.querySelector('#history-table tbody');
    tbody.innerHTML = (history||[]).map(h =>
      `<tr><td>${h.timestamp}</td><td><span class="badge badge-${h.emotion}">${h.emotion}</span></td><td>${(h.confidence*100).toFixed(0)}%</td><td>${h.method}</td></tr>`
    ).join('');

  } catch(e) { console.error(e); }
}

fetchData();
setInterval(fetchData, 5000);
</script>
</body>
</html>
"""


@app.route('/')
def index():
    """仪表盘主页"""
    return render_template_string(DASHBOARD_HTML)


@app.route('/api/sensor')
def api_sensor():
    """实时传感器数据 + 最近历史"""
    global _sensor_data, _emotion_logger
    history = []
    if _emotion_logger:
        history = _emotion_logger.get_sensor_history(limit=30)
    return jsonify({
        'dht11_temp': _sensor_data.get('dht11_temp', 0),
        'dht11_humidity': _sensor_data.get('dht11_humidity', 0),
        'light_raw': _sensor_data.get('light_raw', 0),
        'light_pct': _sensor_data.get('light_pct', 0),
        'ntc_temp': _sensor_data.get('ntc_temp', 0),
        'timestamp': _sensor_data.get('timestamp', ''),
        'history': history,
    })


@app.route('/api/history')
def api_history():
    """情绪检测历史"""
    global _emotion_logger
    if not _emotion_logger:
        return jsonify([])
    limit = request.args.get('limit', 50, type=int)
    return jsonify(_emotion_logger.get_emotion_history(limit=limit))


@app.route('/api/summary')
def api_summary():
    """今日总结"""
    global _emotion_logger, _emotion_state
    if _emotion_logger:
        summary = _emotion_logger.get_today_summary()
    else:
        summary = {'date': '', 'total_detections': 0, 'breakdown': {},
                   'latest_emotion': _emotion_state['current'],
                   'latest_time': ''}
    return jsonify(summary)


@app.route('/api/status')
def api_status():
    """当前状态"""
    global _emotion_state, _sensor_data
    return jsonify({
        'emotion': _emotion_state['current'],
        'status_text': _emotion_state['status_text'],
        'detection_count': _emotion_state['detection_count'],
        'sensor': {
            'temp': _sensor_data.get('dht11_temp', 0),
            'humidity': _sensor_data.get('dht11_humidity', 0),
            'light': _sensor_data.get('light_raw', 0),
        }
    })


def update_state(emotion, status_text, detection_count):
    """由 main.py 调用, 更新当前状态"""
    global _emotion_state
    _emotion_state = {
        'current': emotion,
        'status_text': status_text,
        'detection_count': detection_count,
    }


def update_sensor_data(data):
    """由 main.py 调用, 更新传感器数据"""
    global _sensor_data
    _sensor_data = data


def set_logger(logger):
    """由 main.py 调用, 设置 logger 实例"""
    global _emotion_logger
    _emotion_logger = logger


class WebDashboard:
    """Web 仪表盘后台服务"""

    def __init__(self, host='0.0.0.0', port=5000):
        if not _HAS_FLASK:
            raise ImportError("WebDashboard 需要 flask: pip install flask")
        self.host = host
        self.port = port
        self._thread = None
        self._running = False

    def start(self):
        """后台启动 Flask 服务"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[WEB] 仪表盘已启动: http://{self._get_ip()}:{self.port}")

    def _run(self):
        try:
            app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
        except Exception as e:
            print(f"[WEB] 服务异常: {e}")

    def stop(self):
        """停止服务"""
        self._running = False

    @staticmethod
    def _get_ip():
        """获取树莓派 IP"""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return 'localhost'
