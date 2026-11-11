"""화면 캡처 + JPEG 압축.

FrameProducer 는 여러 스레드에서 동시에 캡처·압축해 처리량을 높인다.
(Pillow 의 축소·JPEG 인코딩은 GIL 을 놓기 때문에 스레드 수만큼 거의 선형으로 빨라진다.)
"""
from __future__ import annotations

import base64
import io
import os
import threading
import time
from dataclasses import dataclass

import mss
from PIL import Image

from .protocol import FrameUpload


def _new_mss():
    return mss.MSS() if hasattr(mss, "MSS") else mss.mss()


def encode(raw: bytes, size: tuple[int, int], max_width: int, quality: int) -> tuple[bytes, int, int]:
    # frombuffer: 복사 없이 BGRA 원본을 RGB 로 해석
    img = Image.frombuffer("RGB", size, raw, "raw", "BGRX", 0, 1)
    if img.width > max_width:
        # BOX(면적 평균) 축소: BILINEAR 보다 빠르고 글자가 덜 뭉개진다
        img = img.resize((max_width, round(img.height * max_width / img.width)), Image.Resampling.BOX)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue(), img.width, img.height


class ScreenCapturer:
    """단일 스레드용 (HTTP 호환 모드 등)."""

    def __init__(self, monitor_index: int = 1):
        self._sct = _new_mss()
        self.monitor = self._sct.monitors[monitor_index]  # 1 = 주 모니터

    def grab_jpeg(self, max_width: int = 1280, quality: int = 60) -> tuple[bytes, int, int]:
        shot = self._sct.grab(self.monitor)
        return encode(shot.bgra, shot.size, max_width, quality)

    def grab(self, max_width: int = 1280, quality: int = 60) -> FrameUpload:
        data, w, h = self.grab_jpeg(max_width, quality)
        return FrameUpload(width=w, height=h, mime="image/jpeg", data_b64=base64.b64encode(data).decode())

    def close(self) -> None:
        self._sct.close()


@dataclass
class Frame:
    seq: int
    jpeg: bytes
    width: int
    height: int


@dataclass
class CaptureSettings:
    fps: int = 30
    max_width: int = 1280
    quality: int = 60


def default_workers() -> int:
    return max(1, min(3, (os.cpu_count() or 2) - 1))


class FrameProducer:
    """N 개 스레드가 목표 FPS 에 맞춰 번갈아 캡처·압축하고, 가장 최신 프레임만 남긴다."""

    def __init__(self, settings: CaptureSettings, workers: int | None = None, monitor_index: int = 1):
        self.settings = settings
        self.workers = workers or default_workers()
        self._monitor_index = monitor_index
        probe = _new_mss()
        self.monitor = dict(probe.monitors[monitor_index])
        probe.close()
        self._lock = threading.Lock()
        self._ready = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._next_due = 0.0
        self._ticket = 0
        self._latest: Frame | None = None
        self._last_raw: bytes | None = None
        self.error: Exception | None = None

    def start(self) -> None:
        self._next_due = time.monotonic()
        for i in range(self.workers):
            t = threading.Thread(target=self._run, name=f"capture-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        with self._ready:
            self._ready.notify_all()
        for t in self._threads:
            t.join(timeout=2)

    def _take_ticket(self) -> tuple[int, float]:
        """다음 캡처 순번과 예정 시각 (전체 스레드 합쳐서 목표 FPS 를 지키도록)."""
        with self._lock:
            now = time.monotonic()
            due = max(now, self._next_due)
            self._next_due = due + 1 / max(1, self.settings.fps)
            self._ticket += 1
            return self._ticket, due

    def _run(self) -> None:
        try:
            sct = _new_mss()
        except Exception as e:  # noqa: BLE001
            self.error = e
            return
        try:
            while not self._stop.is_set():
                seq, due = self._take_ticket()
                delay = due - time.monotonic()
                if delay > 0 and self._stop.wait(delay):
                    break
                shot = sct.grab(self.monitor)
                raw = shot.bgra
                if raw == self._last_raw:  # 화면 변화 없음 → 압축 생략
                    continue
                self._last_raw = raw
                s = self.settings
                jpeg, w, h = encode(raw, shot.size, s.max_width, s.quality)
                with self._ready:
                    if self._latest is None or seq > self._latest.seq:  # 늦게 끝난 옛 프레임은 버림
                        self._latest = Frame(seq, jpeg, w, h)
                        self._ready.notify_all()
        except Exception as e:  # noqa: BLE001
            self.error = e
        finally:
            sct.close()

    def next(self, after_seq: int, timeout: float) -> Frame | None:
        """after_seq 보다 새로운 프레임을 기다려 반환 (없으면 None)."""
        deadline = time.monotonic() + timeout
        with self._ready:
            while not self._stop.is_set():
                if self._latest is not None and self._latest.seq > after_seq:
                    return self._latest
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self.error is not None:
                    return None
                self._ready.wait(remaining)
        return None

    @property
    def latest(self) -> Frame | None:
        return self._latest
