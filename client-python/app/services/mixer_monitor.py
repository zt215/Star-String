"""调音台设备音量监控（WASAPI 输入 + Loopback 输出回环）。

用 pyaudiowpatch 同时监听任意数量的：
- 输入设备（麦克风等）：真实采集，看"有没有输入音量"
- 输出设备的 Loopback 回环：抓取系统正在播放的声音，看"有没有输出音量"

每个通道一个采集线程，RMS 电平通过回调抛给 UI（Qt Signal 转主线程）。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

import pyaudiowpatch as pyaudio

# 电平回调: (channel_id, rms 0..1)
LevelListener = Callable[[str, float], None]

_FRAMES_PER_BUFFER = 1024


@dataclass
class DeviceInfo:
    index: int          # PyAudio 全局设备索引
    name: str
    kind: str           # "input" | "loopback"
    channels: int
    rate: int


def _wasapi_index(pa: pyaudio.PyAudio) -> Optional[int]:
    for i in range(pa.get_host_api_count()):
        if "WASAPI" in pa.get_host_api_info_by_index(i).get("name", ""):
            return i
    return None


def list_input_devices() -> list[DeviceInfo]:
    """枚举 WASAPI 输入设备。"""
    pa = pyaudio.PyAudio()
    try:
        wasapi = _wasapi_index(pa)
        if wasapi is None:
            return []
        out: list[DeviceInfo] = []
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if int(info.get("hostApi", -1)) != wasapi:
                continue
            if int(info.get("maxInputChannels", 0)) <= 0:
                continue
            out.append(
                DeviceInfo(
                    index=i,
                    name=str(info.get("name", f"设备{i}")),
                    kind="input",
                    channels=int(info["maxInputChannels"]),
                    rate=int(info.get("defaultSampleRate", 48000)),
                )
            )
        return out
    finally:
        pa.terminate()


def list_loopback_devices() -> list[DeviceInfo]:
    """枚举可回环监听的输出设备（系统正在播放的声音）。"""
    pa = pyaudio.PyAudio()
    try:
        out: list[DeviceInfo] = []
        try:
            for info in pa.get_loopback_device_info_generator():
                out.append(
                    DeviceInfo(
                        index=int(info["index"]),
                        name=str(info.get("name", f"回环{info['index']}")),
                        kind="loopback",
                        channels=int(info.get("maxChannels", 2)) or 2,
                        rate=int(info.get("defaultSampleRate", 48000)),
                    )
                )
        except AttributeError:
            pass
        return out
    finally:
        pa.terminate()


class MixerMonitor:
    """管理多通道电平采集。add/remove 线程安全。"""

    def __init__(self, listener: LevelListener) -> None:
        self._listener = listener
        self._pa = pyaudio.PyAudio()
        self._lock = threading.Lock()
        self._channels: dict[str, dict] = {}  # id -> {thread, stop, stream}

    def add_channel(
        self,
        channel_id: str,
        device: DeviceInfo,
    ) -> None:
        with self._lock:
            if channel_id in self._channels:
                return
            stop = threading.Event()
            entry = {"stop": stop, "thread": None, "device": device}
            self._channels[channel_id] = entry
        thread = threading.Thread(
            target=self._pump, args=(channel_id, device, stop), daemon=True
        )
        entry["thread"] = thread
        thread.start()

    def remove_channel(self, channel_id: str) -> None:
        with self._lock:
            entry = self._channels.pop(channel_id, None)
        if entry is None:
            return
        entry["stop"].set()
        thread = entry.get("thread")
        if thread is not None:
            thread.join(timeout=1.5)

    def shutdown(self) -> None:
        for channel_id in list(self._channels.keys()):
            self.remove_channel(channel_id)
        try:
            self._pa.terminate()
        except Exception:
            pass

    def _pump(self, channel_id: str, device: DeviceInfo, stop: threading.Event) -> None:
        stream = None
        try:
            channels = max(1, min(device.channels, 2))
            stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=device.rate,
                input=True,
                input_device_index=device.index,
                frames_per_buffer=_FRAMES_PER_BUFFER,
            )
        except Exception as e:
            print(f"MixerMonitor: 打开通道 {device.name} 失败: {e}")
            self._listener(channel_id, -1.0)  # -1 = 错误信号
            return
        try:
            while not stop.is_set():
                try:
                    data = stream.read(_FRAMES_PER_BUFFER, exception_on_overflow=False)
                except Exception:
                    if stop.is_set():
                        break
                    continue
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                if samples.size == 0:
                    continue
                rms = float(np.sqrt(np.mean(samples * samples)) / 32768.0)
                self._listener(channel_id, rms)
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
