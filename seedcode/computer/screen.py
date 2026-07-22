"""Screen driver: screenshots, resolution, and multi-monitor geometry.

Uses ``mss`` for capture (fast, multi-monitor aware) and Pillow only to
encode PNGs. All imports are lazy so the rest of Seed Code loads without the
desktop extra installed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ..utils.helpers import app_dir


@dataclass(slots=True)
class MonitorInfo:
    """One physical monitor in virtual-desktop coordinates."""

    index: int  # 1-based, matching mss numbering (0 is the combined desktop)
    left: int
    top: int
    width: int
    height: int
    primary: bool


@dataclass(slots=True)
class ScreenGeometry:
    """The combined virtual desktop plus its monitors."""

    left: int
    top: int
    width: int
    height: int
    monitors: list[MonitorInfo]

    def contains(self, x: int, y: int) -> bool:
        return (
            self.left <= x < self.left + self.width
            and self.top <= y < self.top + self.height
        )


def screenshots_dir() -> Path:
    """Directory screenshots are saved to (created on demand)."""
    path = app_dir() / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def geometry() -> ScreenGeometry:
    """Current virtual-desktop geometry (all monitors)."""
    import mss

    with mss.mss() as sct:
        combined = sct.monitors[0]
        monitors = [
            MonitorInfo(
                index=i,
                left=m["left"],
                top=m["top"],
                width=m["width"],
                height=m["height"],
                primary=(m["left"] == 0 and m["top"] == 0),
            )
            for i, m in enumerate(sct.monitors[1:], start=1)
        ]
    return ScreenGeometry(
        left=combined["left"],
        top=combined["top"],
        width=combined["width"],
        height=combined["height"],
        monitors=monitors,
    )


def capture(
    region: tuple[int, int, int, int] | None = None,
    monitor: int | None = None,
    save_to: Path | None = None,
) -> Path:
    """Capture the screen to a PNG file and return its path.

    ``region`` is (left, top, width, height) in virtual-desktop coordinates;
    ``monitor`` is a 1-based monitor index; neither means the whole desktop.
    """
    import mss
    import mss.tools

    with mss.mss() as sct:
        if region is not None:
            left, top, width, height = region
            grab_area = {"left": left, "top": top, "width": width, "height": height}
        elif monitor is not None:
            if not 1 <= monitor < len(sct.monitors):
                raise ValueError(
                    f"Monitor {monitor} does not exist (found {len(sct.monitors) - 1})."
                )
            grab_area = sct.monitors[monitor]
        else:
            grab_area = sct.monitors[0]
        shot = sct.grab(grab_area)

        if save_to is None:
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
            save_to = screenshots_dir() / f"screenshot-{stamp}.png"
        save_to.parent.mkdir(parents=True, exist_ok=True)
        mss.tools.to_png(shot.rgb, shot.size, output=str(save_to))
    return save_to


def encode_png_base64(path: Path, max_dim: int = 1568) -> str:
    """Base64-encode a screenshot PNG, downscaling large captures first.

    Vision models cap useful input resolution; downscaling keeps payloads
    small without losing the layout the model needs.
    """
    import base64
    import io

    from PIL import Image

    with Image.open(path) as img:
        if max(img.size) > max_dim:
            img.thumbnail((max_dim, max_dim))
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")
