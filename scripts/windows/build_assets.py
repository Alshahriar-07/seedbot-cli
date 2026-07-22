"""Generate the Windows branding assets for Seed Code — stdlib only.

Produces, under ``assets/windows/``:

* ``seedcode.ico``      — multi-resolution icon (16..128 BMP + 256 PNG),
                          embedded into seedcode.exe, setup.exe and every
                          shortcut so the default Python icon never appears.
* ``wizard.bmp``        — Inno Setup wizard side image (164x314, 24-bit).
* ``wizard-small.bmp``  — Inno Setup wizard header image (55x58, 24-bit).
* ``version_info.txt``  — PyInstaller version resource (publisher, version,
                          product name shown in Explorer file properties).
* ``preview.png``       — 256px render for eyeballing the artwork.

The artwork is drawn from a 16x16 pixel-art grid matching the blocky Seed
Code logo style (Seed Green #2ecc71 on dark), scaled with nearest-neighbour
so every size stays crisp. Everything is deterministic: same inputs, byte-
identical outputs.

Usage:
    python build_assets.py --version 1.0.0
    python build_assets.py --verify-exe ..\\..\\dist\\seedcode.exe
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets" / "windows"

# --- palette (mirrors seedcode/ui/theme.py) ---------------------------------
BG = (13, 17, 23, 255)        # dark panel background
PRIMARY = (46, 204, 113, 255)  # Seed Green
ACCENT = (123, 237, 159, 255)  # Soft Green
DARK = (27, 122, 67, 255)      # seed body
CLEAR = (0, 0, 0, 0)

# --- the mark: a sprouting seed, 16x16 --------------------------------------
_ART = [
    "................",
    "................",
    "...LL.....GG....",
    "..LLLL...GGGG...",
    ".LLLLLL.GGGGG...",
    ".LLLLLL.GGGGGG..",
    "..LLLLL.GGGGG...",
    "...LLLL.GGGG....",
    ".....LL.GG......",
    "......LGG.......",
    ".......G........",
    ".......G........",
    "......DDD.......",
    ".....DDDDD......",
    ".....DDDDD......",
    "......DDD.......",
]
_INK = {"L": ACCENT, "G": PRIMARY, "D": DARK}


def _render(size: int) -> list[list[tuple[int, int, int, int]]]:
    """Render the mark at ``size`` px: rounded dark tile + scaled pixel art."""
    radius = size * 3 // 16
    grid = [[CLEAR] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            # Rounded-rect clip: inside unless outside a corner circle.
            cx = radius if x < radius else (size - 1 - radius if x >= size - radius else x)
            cy = radius if y < radius else (size - 1 - radius if y >= size - radius else y)
            if (x - cx) ** 2 + (y - cy) ** 2 > radius * radius and (
                (x < radius or x >= size - radius) and (y < radius or y >= size - radius)
            ):
                continue
            cell = _ART[y * 16 // size][x * 16 // size]
            grid[y][x] = _INK.get(cell, BG)
    return grid


# --- PNG encoding (RGBA, no filters) -----------------------------------------
def _png(grid: list[list[tuple[int, int, int, int]]]) -> bytes:
    h, w = len(grid), len(grid[0])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    raw = b"".join(
        b"\x00" + b"".join(bytes(px) for px in row) for row in grid
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


# --- ICO assembly --------------------------------------------------------------
def _ico_bmp_entry(grid: list[list[tuple[int, int, int, int]]]) -> bytes:
    """One 32-bit BMP image as stored inside an ICO (DIB + empty AND mask)."""
    h, w = len(grid), len(grid[0])
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, w * h * 4, 0, 0, 0, 0)
    xor = b"".join(
        bytes((px[2], px[1], px[0], px[3]))  # BGRA, rows bottom-up
        for row in reversed(grid)
        for px in row
    )
    and_mask = b"\x00" * (((w + 31) // 32) * 4) * h  # alpha carries transparency
    return header + xor + and_mask


def build_ico(path: Path) -> bytes:
    """Write the multi-resolution .ico; returns the 256px PNG payload."""
    bmp_sizes = (16, 24, 32, 48, 64, 128)
    images = [(s, _ico_bmp_entry(_render(s))) for s in bmp_sizes]
    png256 = _png(_render(256))
    images.append((256, png256))

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        entries += struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset
        )
        blobs += data
        offset += len(data)
    path.write_bytes(header + entries + blobs)
    return png256


# --- Inno wizard bitmaps (24-bit BMP files) -------------------------------------
def _bmp_file(grid: list[list[tuple[int, int, int, int]]]) -> bytes:
    h, w = len(grid), len(grid[0])
    row_pad = (4 - (w * 3) % 4) % 4
    pixels = b"".join(
        b"".join(bytes((px[2], px[1], px[0])) for px in row) + b"\x00" * row_pad
        for row in reversed(grid)
    )
    info = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(pixels), 0, 0, 0, 0)
    file_header = struct.pack("<2sIHHI", b"BM", 14 + len(info) + len(pixels), 0, 0, 14 + len(info))
    return file_header + info + pixels


def _wizard_canvas(w: int, h: int, mark_px: int) -> list[list[tuple[int, int, int, int]]]:
    """Dark canvas with the mark centred (nearest-neighbour from the art grid)."""
    grid = [[BG] * w for _ in range(h)]
    x0, y0 = (w - mark_px) // 2, (h - mark_px) // 2
    for y in range(mark_px):
        for x in range(mark_px):
            cell = _ART[y * 16 // mark_px][x * 16 // mark_px]
            if cell in _INK:
                grid[y0 + y][x0 + x] = _INK[cell]
    return grid


# --- PyInstaller version resource -------------------------------------------------
_VERSION_INFO = """\
# Generated by scripts/windows/build_assets.py — do not edit.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v_tuple}),
    prodvers=({v_tuple}),
    mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Al Shahriar Sowan'),
      StringStruct('FileDescription', 'Seed Code - terminal AI coding assistant'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'seedcode'),
      StringStruct('LegalCopyright', 'Copyright (c) Al Shahriar Sowan. MIT License.'),
      StringStruct('OriginalFilename', 'seedcode.exe'),
      StringStruct('ProductName', 'Seed Code'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def write_version_info(path: Path, version: str) -> None:
    parts = [int(p) for p in version.split(".") if p.isdigit()][:4]
    parts += [0] * (4 - len(parts))
    path.write_text(
        _VERSION_INFO.format(version=version, v_tuple=", ".join(map(str, parts))),
        encoding="utf-8",
    )


# --- verification ------------------------------------------------------------------
def verify_ico(path: Path) -> None:
    """Structural check: parse the ICO back and confirm every expected entry."""
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert reserved == 0 and kind == 1, "not an ICO file"
    sizes = set()
    for i in range(count):
        w, h, _, _, planes, bpp, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * i
        )
        assert offset + length <= len(data), "entry overruns file"
        sizes.add(w or 256)
        blob = data[offset : offset + length]
        assert blob[:8] == b"\x89PNG\r\n\x1a\n" or struct.unpack_from("<I", blob)[0] == 40
    expected = {16, 24, 32, 48, 64, 128, 256}
    assert sizes == expected, f"icon sizes {sorted(sizes)} != {sorted(expected)}"


def verify_exe_has_icon(exe: Path, ico: Path) -> None:
    """Confirm the built exe embeds this icon (the 256px PNG payload is stored
    verbatim as an RT_ICON resource, so a byte search is a reliable probe)."""
    ico_data = ico.read_bytes()
    png = ico_data[ico_data.find(b"\x89PNG") :]
    if png[:512] not in exe.read_bytes():
        raise SystemExit(
            f"VERIFY FAILED: {exe} does not embed the Seed Code icon "
            "(PyInstaller --icon step missing or used a different file)."
        )
    print(f"[OK] {exe.name} embeds the Seed Code icon.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="", help="app version for the exe resource")
    parser.add_argument("--verify-exe", default="", help="check an exe embeds the icon")
    opts = parser.parse_args()

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    ico_path = ASSETS_DIR / "seedcode.ico"

    if opts.verify_exe:
        verify_exe_has_icon(Path(opts.verify_exe), ico_path)
        return

    build_ico(ico_path)
    verify_ico(ico_path)
    (ASSETS_DIR / "preview.png").write_bytes(_png(_render(256)))
    (ASSETS_DIR / "wizard.bmp").write_bytes(_bmp_file(_wizard_canvas(164, 314, 128)))
    (ASSETS_DIR / "wizard-small.bmp").write_bytes(_bmp_file(_wizard_canvas(55, 58, 48)))
    if opts.version:
        write_version_info(ASSETS_DIR / "version_info.txt", opts.version)
    print(f"[OK] Branding assets written to {ASSETS_DIR}")
    for name in ("seedcode.ico", "wizard.bmp", "wizard-small.bmp", "preview.png"):
        print(f"     {name}  ({(ASSETS_DIR / name).stat().st_size} bytes)")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        sys.exit(f"VERIFY FAILED: {exc}")
