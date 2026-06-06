#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据记录模块
============
SQLite 数据库, 记录每次情绪检测结果和传感器数据
"""

import sqlite3
import os
import time
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'emotion_data.db')


class EmotionLogger:
    """
    情绪检测数据记录器 (SQLite)

    表结构:
      - emotion_log:  每次检测结果 (情绪、置信度、方法、时间戳)
      - sensor_log:   检测时的传感器快照
    """

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """创建数据表 (若不存在)"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS emotion_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    emotion     TEXT    NOT NULL,
                    confidence  REAL    NOT NULL,
                    method      TEXT    NOT NULL,
                    fer_detail  TEXT,
                    timestamp   TEXT    NOT NULL
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS sensor_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    dht11_temp      REAL,
                    dht11_humidity  REAL,
                    light_raw       INTEGER,
                    light_pct       REAL,
                    ntc_temp        REAL,
                    timestamp       TEXT NOT NULL
                )
            ''')
            conn.commit()

    def log_emotion(self, emotion, confidence, method, fer_detail=None):
        """记录一次情绪检测"""
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                'INSERT INTO emotion_log (emotion, confidence, method, fer_detail, timestamp) '
                'VALUES (?, ?, ?, ?, ?)',
                (emotion, confidence, method,
                 str(fer_detail) if fer_detail else None, ts)
            )
            conn.commit()

    def log_sensor_snapshot(self, sensor_data):
        """记录传感器快照"""
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                'INSERT INTO sensor_log (dht11_temp, dht11_humidity, light_raw, '
                'light_pct, ntc_temp, timestamp) VALUES (?, ?, ?, ?, ?, ?)',
                (sensor_data.get('dht11_temp', 0),
                 sensor_data.get('dht11_humidity', 0),
                 sensor_data.get('light_raw', 0),
                 sensor_data.get('light_pct', 0),
                 sensor_data.get('ntc_temp', 0),
                 ts)
            )
            conn.commit()

    def get_emotion_history(self, limit=100):
        """获取最近的情绪检测历史"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                'SELECT emotion, confidence, method, timestamp FROM emotion_log '
                'ORDER BY id DESC LIMIT ?', (limit,)
            ).fetchall()
        return [{'emotion': r[0], 'confidence': r[1], 'method': r[2],
                 'timestamp': r[3]} for r in rows]

    def get_emotion_stats(self):
        """获取情绪统计 (各情绪出现次数)"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                'SELECT emotion, COUNT(*) as cnt FROM emotion_log GROUP BY emotion'
            ).fetchall()
        return {r[0]: r[1] for r in rows}

    def get_sensor_history(self, limit=100):
        """获取最近的传感器记录"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                'SELECT dht11_temp, dht11_humidity, light_raw, ntc_temp, timestamp '
                'FROM sensor_log ORDER BY id DESC LIMIT ?', (limit,)
            ).fetchall()
        return [{'temp': r[0], 'humidity': r[1], 'light': r[2],
                 'ntc': r[3], 'timestamp': r[4]} for r in rows]

    def get_today_summary(self):
        """今日总结"""
        today = datetime.now().strftime('%Y-%m-%d')
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute(
                'SELECT COUNT(*) FROM emotion_log WHERE timestamp LIKE ?',
                (today + '%',)
            ).fetchone()[0]
            stats = conn.execute(
                'SELECT emotion, COUNT(*) FROM emotion_log '
                'WHERE timestamp LIKE ? GROUP BY emotion',
                (today + '%',)
            ).fetchall()
            latest = conn.execute(
                'SELECT emotion, timestamp FROM emotion_log '
                'ORDER BY id DESC LIMIT 1'
            ).fetchone()
        return {
            'date': today,
            'total_detections': total,
            'breakdown': {r[0]: r[1] for r in stats},
            'latest_emotion': latest[0] if latest else None,
            'latest_time': latest[1] if latest else None,
        }
