"""语音驱动口型（Voice Lip Sync）。

把麦克风的电平转成「嘴巴开合」数值，并顺带估计一个粗粒度的「口型形状」，
让虚拟形象的嘴跟着人声动，而不是跟着摄像头画面动。

生产者是音频回调线程（``feed``），消费者是 UI 线程（``read``），
因此共享状态统一用锁保护。包络采用快开慢关的非对称平滑：
说话时立刻张嘴，收声时缓慢合拢，避免出现「打点式」的抽搐口型。
"""

from __future__ import annotations

import math
import threading
import time

import numpy as np


class VoiceLipSync:
    """音频电平 -> 口型开合 / 口型形状 的转换器。"""

    #: 低于该电平等同于静音，高于 :attr:`CEIL_DB` 视为满口型
    FLOOR_DB = -55.0
    CEIL_DB = -12.0

    #: 音频断流多久之后开始强制收口（秒）
    HOLD_SECONDS = 0.25
    #: 收口速度（单位/秒）
    DECAY_PER_SECOND = 6.0

    #: 张嘴/合嘴的平滑速度（单位/秒），开着快、关着慢
    ATTACK_PER_SECOND = 22.0
    RELEASE_PER_SECOND = 9.0

    #: 口型形状的平滑系数（形状变化本来就慢）
    FORM_ALPHA = 0.18

    #: 区分「扁口」与「圆唇」的频谱分界点（Hz）
    FORM_SPLIT_HZ = 1200.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open = 0.0
        self._form = 0.0
        self._level = 0.0
        self._last_feed = 0.0
        self._gain = 1.0
        self._enabled = False

    # ---- 配置 ----

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = bool(enabled)
            if not self._enabled:
                self._open = 0.0
                self._form = 0.0
                self._level = 0.0

    def is_enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def set_gain(self, gain: float) -> None:
        with self._lock:
            self._gain = max(0.2, min(4.0, float(gain)))

    def reset(self) -> None:
        with self._lock:
            self._open = 0.0
            self._form = 0.0
            self._level = 0.0
            self._last_feed = 0.0

    # ---- 生产端：音频线程 ----

    def feed(self, audio, sample_rate: int) -> None:
        """喂入一段原始音频，更新内部包络。"""
        if not self._enabled or audio is None:
            return
        try:
            block = np.asarray(audio, dtype=np.float32).reshape(-1)
        except Exception:
            return
        if block.size == 0:
            return

        try:
            rms = float(np.sqrt(np.mean(block * block)))
            db = 20.0 * math.log10(max(rms, 1e-7))
            level = (db - self.FLOOR_DB) / (self.CEIL_DB - self.FLOOR_DB)
            level = max(0.0, min(1.0, level))
            shape = self._estimate_form(block, sample_rate)
        except Exception:
            return

        now = time.monotonic()
        with self._lock:
            if not self._enabled:
                return
            dt = now - self._last_feed if self._last_feed else 0.03
            dt = max(0.005, min(0.2, dt))
            self._last_feed = now
            self._level = level
            rate = self.ATTACK_PER_SECOND if level > self._open else self.RELEASE_PER_SECOND
            self._open += (level - self._open) * min(1.0, rate * dt)
            self._open = max(0.0, min(1.0, self._open))
            self._form += (shape - self._form) * self.FORM_ALPHA

    @classmethod
    def _estimate_form(cls, block: np.ndarray, sample_rate: int) -> float:
        """粗估口型形状：高频占比高 -> 扁口（i/e），低 -> 圆唇（o/u）。

        真正的音素口型需要 ASR 级别的声学模型，这里用频谱重心做一个廉价近似：
        只求一个 -1..1 的形状值，够驱动 Live2D 的 ParamMouthForm / VRM 的
        aa/ou 表情即可。
        """
        size = 512
        if block.size < size:
            size = 1 << int(math.log2(max(32, block.size)))
            if size < 64:
                return 0.0
        window = np.hanning(size).astype(np.float32)
        spectrum = np.abs(np.fft.rfft(block[:size] * window))
        total = float(spectrum.sum())
        if total <= 1e-9:
            return 0.0
        freqs = np.fft.rfftfreq(size, 1.0 / float(max(int(sample_rate), 1)))
        high = float(spectrum[freqs >= cls.FORM_SPLIT_HZ].sum())
        ratio = high / total
        return max(-1.0, min(1.0, (ratio - 0.28) * 3.0))

    # ---- 消费端：UI 线程 ----

    def read(self) -> tuple[float, float, float]:
        """返回 ``(口型开合 0..1, 口型形状 -1..1, 音量 0..1)``。"""
        with self._lock:
            if not self._enabled:
                return 0.0, 0.0, 0.0
            open_value = self._open
            form = self._form
            level = self._level
            gain = self._gain
            last = self._last_feed

        if last:
            idle = time.monotonic() - last
            if idle > self.HOLD_SECONDS:
                open_value = max(
                    0.0, open_value - (idle - self.HOLD_SECONDS) * self.DECAY_PER_SECOND
                )
        # 0.75 次幂让小声说话也能看见口型，同时保持大音量不过曝
        mouth = min(1.0, (open_value ** 0.75) * gain)
        return mouth, form, level

    def is_speaking(self, threshold: float = 0.05) -> bool:
        return self.read()[0] >= threshold
