"""뷰어에서 받은 (검증된) 입력 이벤트를 실제 마우스/키보드 동작으로 재생."""
from pynput.keyboard import Controller as KeyboardController, Key, KeyCode
from pynput.mouse import Button, Controller as MouseController

from .protocol import InputEvent, KeyEvent, MouseButtonEvent, MouseMove, MouseWheel

_BUTTONS = {"left": Button.left, "right": Button.right, "middle": Button.middle}

# KeyboardEvent.key → pynput 특수키
_SPECIAL: dict[str, Key] = {
    "Enter": Key.enter, "Backspace": Key.backspace, "Tab": Key.tab, "Escape": Key.esc,
    "Delete": Key.delete, "Home": Key.home, "End": Key.end, "PageUp": Key.page_up,
    "PageDown": Key.page_down, "ArrowUp": Key.up, "ArrowDown": Key.down, "ArrowLeft": Key.left,
    "ArrowRight": Key.right, "Shift": Key.shift, "Control": Key.ctrl, "Alt": Key.alt,
    "Meta": Key.cmd, "CapsLock": Key.caps_lock, " ": Key.space,
    **{f"F{i}": getattr(Key, f"f{i}") for i in range(1, 13)},
}
for _name in ("Insert", "PrintScreen", "Pause", "NumLock", "ScrollLock", "ContextMenu"):
    _attr = {"PrintScreen": "print_screen", "NumLock": "num_lock", "ScrollLock": "scroll_lock",
             "ContextMenu": "menu"}.get(_name, _name.lower())
    if hasattr(Key, _attr):
        _SPECIAL[_name] = getattr(Key, _attr)


def _to_key(key: str) -> Key | KeyCode | None:
    if key in _SPECIAL:
        return _SPECIAL[key]
    if len(key) == 1:
        return KeyCode.from_char(key)
    return None  # 알 수 없는 키("Dead", "Unidentified" 등)는 무시


class InputPlayer:
    def __init__(self, monitor: dict):
        self.left, self.top = monitor["left"], monitor["top"]
        self.width, self.height = monitor["width"], monitor["height"]
        self.mouse = MouseController()
        self.keyboard = KeyboardController()

    def _move(self, x: float, y: float) -> None:
        self.mouse.position = (
            self.left + round(x * (self.width - 1)),
            self.top + round(y * (self.height - 1)),
        )

    def play(self, ev: InputEvent) -> None:
        if isinstance(ev, MouseMove):
            self._move(ev.x, ev.y)
        elif isinstance(ev, MouseButtonEvent):
            self._move(ev.x, ev.y)
            btn = _BUTTONS[ev.button]
            (self.mouse.press if ev.type == "mouse_down" else self.mouse.release)(btn)
        elif isinstance(ev, MouseWheel):
            self.mouse.scroll(ev.dx, ev.dy)
        elif isinstance(ev, KeyEvent):
            k = _to_key(ev.key)
            if k is not None:
                (self.keyboard.press if ev.type == "key_down" else self.keyboard.release)(k)
