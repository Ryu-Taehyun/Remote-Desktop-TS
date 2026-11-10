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

    def grab(self, max_width: int = 1280, quality: int = 60) -> FrameUpload:
        shot = self._sct.grab(self.monitor)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        if img.width > max_width:
            img = img.resize((max_width, round(img.height * max_width / img.width)), Image.Resampling.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return FrameUpload(
            width=img.width, height=img.height, mime="image/jpeg",
            data_b64=base64.b64encode(buf.getvalue()).decode(),
        )

    def close(self) -> None:
        self._sct.close()
