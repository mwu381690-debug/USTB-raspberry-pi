#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
情绪检测模块
============
- 人脸检测 (OpenCV Haar Cascade + DNN)
- 情绪识别 (FER 库 或 OpenCV 笑脸检测降级)
- USB 摄像头采集

支持识别的情绪: happy, sad, angry, surprise, neutral, fear, disgust
"""

import time
import threading
import numpy as np

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False
    print("[WARN] OpenCV not installed. Run: pip install opencv-python")

# FER 库 (可选, 提供更准确的情绪识别)
try:
    from fer import FER
    _HAS_FER = True
    print("[INFO] FER 库已加载 (深度学习情绪识别)")
except ImportError:
    _HAS_FER = False
    print("[INFO] FER 库未安装, 将使用 OpenCV 笑脸检测降级方案")
    print("       安装 FER: pip install fer")


class EmotionDetector:
    """
    情绪检测器

    策略:
      1. 优先使用 FER 深度学习库 (识别 7 种情绪)
      2. 降级使用 OpenCV 笑脸检测 (仅开心/不开心二分)
      3. 再降级返回 neutral (确保系统不崩溃)
    """

    # FER 标签 → 统一情绪名
    FER_LABEL_MAP = {
        'happy':    'happy',
        'sad':      'sad',
        'angry':    'angry',
        'surprise': 'surprise',
        'neutral':  'neutral',
        'fear':     'fear',
        'disgust':  'disgust',
    }

    def __init__(self, camera_index=0):
        if not _HAS_CV2:
            raise ImportError("EmotionDetector 需要 OpenCV: pip install opencv-python")

        self.camera_index = camera_index
        self.cap = None

        # 方法选择
        self._use_fer = _HAS_FER
        self._fer_detector = None

        # 加载 Haar 级联分类器
        cascade_path = cv2.data.haarcascades
        self.face_cascade = cv2.CascadeClassifier(
            cascade_path + 'haarcascade_frontalface_default.xml')
        self.smile_cascade = cv2.CascadeClassifier(
            cascade_path + 'haarcascade_smile.xml')

        # 状态
        self._last_result = None
        self._last_frame = None
        self._lock = threading.Lock()

        # 初始化 FER
        if self._use_fer:
            try:
                self._fer_detector = FER(mtcnn=False)  # 使用 OpenCV 检测器, 更快
                print("[INFO] FER 情绪检测器初始化成功")
            except Exception as e:
                print(f"[WARN] FER 初始化失败: {e}, 降级到笑脸检测")
                self._use_fer = False

    def open_camera(self):
        """打开摄像头"""
        if self.cap is not None:
            return True

        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            print(f"[ERROR] 无法打开摄像头 (index={self.camera_index})")
            self.cap = None
            return False

        # 设置分辨率
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 30)

        print(f"[INFO] 摄像头已打开 (index={self.camera_index})")
        return True

    def close_camera(self):
        """关闭摄像头"""
        if self.cap:
            self.cap.release()
            self.cap = None
            print("[INFO] 摄像头已关闭")

    def capture_frame(self):
        """捕获一帧图像 (BGR)"""
        if self.cap is None:
            self.open_camera()
        if self.cap is None:
            return None

        ret, frame = self.cap.read()
        if not ret:
            return None

        # 水平翻转 (镜像效果, 更自然)
        frame = cv2.flip(frame, 1)

        with self._lock:
            self._last_frame = frame

        return frame

    def get_preview_frame(self):
        """获取最新帧用于预览 (非阻塞)"""
        if self.cap is None:
            return None
        ret, frame = self.cap.read()
        if not ret:
            return None
        frame = cv2.flip(frame, 1)
        with self._lock:
            self._last_frame = frame
        return frame

    def detect_emotion(self, frame=None):
        """
        检测情绪 (核心方法)

        参数:
            frame: BGR 图像 (若 None 则自动捕获)

        返回:
            {
                'success':   bool,
                'emotion':   str,     # happy/sad/angry/surprise/neutral/fear/disgust
                'confidence': float,  # 0~1
                'face_found': bool,
                'fer_full':  dict | None,  # FER 完整结果 (若有)
                'method':    str,     # 'fer' | 'smile_detect' | 'fallback'
            }
        """
        if frame is None:
            frame = self.capture_frame()
        if frame is None:
            return self._fail_result('Camera not available')

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # ── 步骤 1: 人脸检测 ──────────────────────────
        faces = self.face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5,
            minSize=(60, 60), flags=cv2.CASCADE_SCALE_IMAGE
        )

        if len(faces) == 0:
            return {
                'success': False, 'emotion': 'neutral',
                'confidence': 0.0, 'face_found': False,
                'fer_full': None, 'method': 'no_face',
            }

        # 取最大的脸
        if len(faces) > 1:
            faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
        x, y, w, h = faces[0]
        face_roi = frame[y:y+h, x:x+w]

        # ── 步骤 2: 情绪识别 ──────────────────────────
        if self._use_fer and self._fer_detector is not None:
            return self._detect_fer(frame, face_roi, (x, y, w, h))
        else:
            return self._detect_smile(gray, (x, y, w, h))

    def _detect_fer(self, frame, face_roi, face_rect):
        """使用 FER 库进行情绪识别"""
        try:
            result = self._fer_detector.detect_emotions(frame)
            if result and len(result) > 0:
                emotions = result[0]['emotions']
                top_emotion = max(emotions, key=emotions.get)
                confidence = emotions[top_emotion]

                x, y, w, h = face_rect

                final = {
                    'success':    True,
                    'emotion':    self.FER_LABEL_MAP.get(top_emotion, 'neutral'),
                    'confidence': round(confidence, 2),
                    'face_found': True,
                    'fer_full':   emotions,
                    'method':     'fer',
                    'face_box':   (x, y, w, h),
                }

                with self._lock:
                    self._last_result = final

                return final
        except Exception as e:
            print(f"[ERROR] FER 检测失败: {e}")

        # FER 失败, 降级
        print("[INFO] FER 检测失败, 降级到笑脸检测")
        self._use_fer = False
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        x, y, w, h = face_rect
        return self._detect_smile(gray, (x, y, w, h))

    def _detect_smile(self, gray, face_rect):
        """
        使用 OpenCV 笑脸检测

        在检测到的人脸下半部分搜索笑容特征
        """
        x, y, w, h = face_rect

        # 在人脸下半部检测笑容 (嘴巴区域)
        roi_gray = gray[y + h//2:y + h, x:x + w]

        smiles = self.smile_cascade.detectMultiScale(
            roi_gray, scaleFactor=1.7, minNeighbors=22,
            minSize=(25, 15)
        )

        has_smile = len(smiles) > 0

        final = {
            'success':    True,
            'emotion':    'happy' if has_smile else 'neutral',
            'confidence': 0.7 if has_smile else 0.5,
            'face_found': True,
            'fer_full':   None,
            'method':     'smile_detect',
            'face_box':   (x, y, w, h),
        }

        with self._lock:
            self._last_result = final

        return final

    def _fail_result(self, reason):
        return {
            'success': False, 'emotion': 'neutral',
            'confidence': 0.0, 'face_found': False,
            'fer_full': None, 'method': 'error',
            'error': reason,
        }

    def get_last_result(self):
        """获取最近的检测结果"""
        with self._lock:
            return self._last_result

    def annotate_frame(self, frame, result):
        """
        在图像上标注人脸框和情绪

        返回标注后的 BGR 图像
        """
        if frame is None:
            return None

        display = frame.copy()

        if result and result.get('face_found'):
            box = result.get('face_box')
            if box:
                x, y, w, h = box
                emotion = result.get('emotion', 'unknown')
                conf = result.get('confidence', 0)

                # 情绪对应的框颜色
                color_map = {
                    'happy':    (0, 255, 0),    # 绿
                    'sad':      (255, 0, 0),    # 蓝
                    'angry':    (0, 0, 255),    # 红
                    'surprise': (255, 255, 0),  # 青
                    'neutral':  (200, 200, 200),
                    'fear':     (0, 165, 255),  # 橙
                    'disgust':  (128, 0, 128),  # 紫
                }
                color = color_map.get(emotion, (255, 255, 255))

                # 画框
                cv2.rectangle(display, (x, y), (x+w, y+h), color, 2)

                # 标签
                label = f"{emotion} ({conf:.0%})"
                cv2.putText(display, label, (x, y-10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                # FER 详细概率 (如果有)
                fer_full = result.get('fer_full')
                if fer_full:
                    y_offset = y + h + 20
                    for emo, prob in sorted(fer_full.items(),
                                            key=lambda e: e[1], reverse=True)[:3]:
                        txt = f"  {emo}: {prob:.0%}"
                        cv2.putText(display, txt, (x, y_offset),
                                    cv2.FONT_HERSHEY_SIMPLEX,
                                    0.5, color_map.get(emo, (200, 200, 200)), 1)
                        y_offset += 18

        return display


# ============================================================
# 自检
# ============================================================

if __name__ == '__main__':
    print("=== 情绪检测模块自检 ===\n")

    detector = EmotionDetector()

    if not detector.open_camera():
        print("[FAIL] 摄像头不可用")
        exit(1)

    print("\n按空格键检测情绪, 按 Q 退出\n")

    try:
        while True:
            frame = detector.capture_frame()
            if frame is None:
                continue

            # 预览 (不做检测, 节约资源)
            display = frame.copy()
            cv2.putText(display, "Press SPACE to detect", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

            cv2.imshow('Emotion Detector Test', display)
            key = cv2.waitKey(30) & 0xFF

            if key == ord('q'):
                break
            elif key == ord(' '):
                print("\n[检测中...]")
                result = detector.detect_emotion(frame)

                if result['face_found']:
                    print(f"  情绪: {result['emotion']}")
                    print(f"  置信度: {result['confidence']}")
                    print(f"  方法: {result['method']}")
                    if result.get('fer_full'):
                        print(f"  详细: {result['fer_full']}")

                    # 显示标注帧
                    annotated = detector.annotate_frame(frame, result)
                    cv2.imshow('Detection Result', annotated)
                    cv2.waitKey(2000)
                    cv2.destroyWindow('Detection Result')
                else:
                    print("  未检测到人脸!")

    except KeyboardInterrupt:
        print("\n[INFO] 自检中断")
    finally:
        detector.close_camera()
        cv2.destroyAllWindows()
