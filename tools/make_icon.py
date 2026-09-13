"""Render the app icon to a multi-size .ico (and a 256 px .png) for the build.

    python tools/make_icon.py build/icon.ico
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication

from qres_gui.gui.theme import icon_pixmap


def png_bytes(size: int) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    icon_pixmap(size).save(buffer, "PNG")
    return bytes(buffer.data())


def main(out: Path) -> None:
    app = QGuiApplication(["make_icon", "-platform", "offscreen"])  # noqa: F841 - needed for QPixmap
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [png_bytes(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = len(header) + 16 * len(sizes)
    entries = b""
    for size, data in zip(sizes, images, strict=True):
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO directory
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(header + entries + b"".join(images))
    # Toast notifications want a plain image file.
    out.with_suffix(".png").write_bytes(images[-1])
    print(f"wrote {out} and {out.with_suffix('.png').name}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "build/icon.ico"))
