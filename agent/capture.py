"""화면 캡처 + JPEG 압축."""
import base64
import io

import mss
from PIL import Image

from .protocol import FrameUpload


class ScreenCapturer:
    def __init__(self, monitor_index: int = 1):
        self._sct = mss.mss()
        self.monitor = self._sct.monitors[monitor_index]  # 1 = 주 모니터

    def grab_jpeg(self, max_width: int = 1280, quality: int = 60) -> tuple[bytes, int, int]:
        shot = self._sct.grab(self.monitor)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        if img.width > max_width:
            size = (max_width, round(img.height * max_width / img.width))
            # reducing_gap: 큰 축소를 단계적으로 처리해 속도를 크게 높임
            img = img.resize(size, Image.Resampling.BILINEAR, reducing_gap=2.0)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)  # optimize=True 는 느려서 사용하지 않음
        return buf.getvalue(), img.width, img.height

    def grab(self, max_width: int = 1280, quality: int = 60) -> FrameUpload:
        data, w, h = self.grab_jpeg(max_width, quality)
        return FrameUpload(width=w, height=h, mime="image/jpeg", data_b64=base64.b64encode(data).decode())

    def close(self) -> None:
        self._sct.close()
