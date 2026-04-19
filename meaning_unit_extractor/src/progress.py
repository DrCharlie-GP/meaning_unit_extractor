"""
进度显示模块。

架构设计：progress_callback 是一个通用接口，签名为 `(current, total, message)`。
当前实现 `CliProgressBar` 向 stderr 输出命令行进度条；
将来 Web 版本可以实现同签名的 WebSocket/SSE 推送器，业务逻辑层无需改动。

使用方式一 —— 直接把 bar.update 作为回调：
    bar = CliProgressBar(label="[proposition]")
    extract_propositions_all(..., progress_callback=bar.update)
    bar.close()

使用方式二 —— 手动推进：
    bar = CliProgressBar(label="任务")
    for i, item in enumerate(items):
        bar.update(i, len(items), f"处理 {item.id}")
        ...
    bar.close()
"""
from __future__ import annotations
import sys
import time


class CliProgressBar:
    """
    命令行进度条。

    输出到 stderr（默认），不干扰 stdout 的结构化输出。
    使用 ASCII 字符 `#` 与 `-`，保证 Windows CMD 兼容性（无乱码风险）。
    用 `\\r` 回退到行首覆盖同一行，避免刷屏。
    内置刷新限频（默认 100 ms 一次），循环调用频繁时不会造成 I/O 瓶颈。
    """

    def __init__(
        self,
        label: str = "",
        bar_width: int = 30,
        file=None,
        min_interval: float = 0.1,
    ):
        self.label = label
        self.bar_width = bar_width
        self.file = file if file is not None else sys.stderr
        self.min_interval = min_interval
        self._start_time: float | None = None
        self._last_render_time = 0.0
        self._closed = False

    def update(self, current: int, total: int, message: str = "") -> None:
        """
        推进进度。签名符合通用 progress_callback 接口。

        current：已完成数
        total：  总数
        message：当前项的描述（会被截断到 30 字）
        """
        if self._closed:
            return
        if self._start_time is None:
            self._start_time = time.time()

        now = time.time()
        is_final = (current >= total)
        # 限频：除非是最后一次或首次调用，否则节流
        if (not is_final and self._last_render_time > 0
                and (now - self._last_render_time) < self.min_interval):
            return
        self._last_render_time = now

        elapsed = now - self._start_time
        pct = (current / total) if total > 0 else 1.0
        pct = min(1.0, max(0.0, pct))

        filled = int(self.bar_width * pct)
        bar = "#" * filled + "-" * (self.bar_width - filled)

        if current > 0 and not is_final:
            rate = elapsed / current
            eta = rate * (total - current)
            eta_str = f"ETA {self._fmt_time(eta)}"
        elif is_final:
            eta_str = f"用时 {self._fmt_time(elapsed)}"
        else:
            eta_str = "ETA --"

        max_msg = 30
        if len(message) > max_msg:
            message = message[: max_msg - 3] + "..."

        line = (
            f"{self.label} [{bar}] {current}/{total} "
            f"({pct * 100:5.1f}%)  {eta_str}  {message}"
        )
        # 用空格填充到足够长，覆盖上一行可能遗留的字符
        self.file.write("\r" + line.ljust(120))
        self.file.flush()

    def close(self) -> None:
        """结束进度条：换行并清理。幂等。"""
        if self._closed:
            return
        self._closed = True
        self.file.write("\n")
        self.file.flush()

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds < 1:
            return "<1s"
        if seconds < 60:
            return f"{seconds:.0f}s"
        m = int(seconds // 60)
        s = int(seconds % 60)
        if m < 60:
            return f"{m}m{s:02d}s"
        h = m // 60
        m = m % 60
        return f"{h}h{m:02d}m"


class NullProgressBar:
    """
    空实现：update 与 close 均为 no-op。
    用于命令行静默模式，或测试中不需要显示进度的场景。
    """

    def update(self, current: int, total: int, message: str = "") -> None:
        pass

    def close(self) -> None:
        pass
