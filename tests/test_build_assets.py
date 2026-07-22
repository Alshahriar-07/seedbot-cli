"""Tests for the Windows branding asset generator (scripts/windows/build_assets.py).

The generator is stdlib-only and deterministic, so the suite can build the
real assets into a temp dir and structurally validate every format.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
import zlib
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "windows" / "build_assets.py"


@pytest.fixture(scope="module")
def assets():
    spec = importlib.util.spec_from_file_location("build_assets", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_assets"] = module
    spec.loader.exec_module(module)
    return module


class TestIco:
    def test_build_and_verify(self, assets, tmp_path):
        ico = tmp_path / "seedcode.ico"
        assets.build_ico(ico)
        assets.verify_ico(ico)  # raises AssertionError on any structural flaw

    def test_contains_all_required_sizes(self, assets, tmp_path):
        ico = tmp_path / "s.ico"
        assets.build_ico(ico)
        data = ico.read_bytes()
        _, _, count = struct.unpack_from("<HHH", data, 0)
        sizes = {
            struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)[0] or 256
            for i in range(count)
        }
        assert sizes == {16, 24, 32, 48, 64, 128, 256}

    def test_256_entry_is_png(self, assets, tmp_path):
        ico = tmp_path / "s.ico"
        png256 = assets.build_ico(ico)
        assert png256[:8] == b"\x89PNG\r\n\x1a\n"
        # PNG payload is stored verbatim inside the ICO (what --verify-exe probes).
        assert png256 in ico.read_bytes()

    def test_deterministic(self, assets, tmp_path):
        a, b = tmp_path / "a.ico", tmp_path / "b.ico"
        assets.build_ico(a)
        assets.build_ico(b)
        assert a.read_bytes() == b.read_bytes()


class TestPng:
    def test_valid_png_stream(self, assets):
        grid = assets._render(64)
        data = assets._png(grid)
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        w, h = struct.unpack_from(">II", data, 16)
        assert (w, h) == (64, 64)
        # IDAT decompresses to exactly h * (1 + w*4) filtered bytes.
        idat_len = struct.unpack_from(">I", data, 33)[0]
        raw = zlib.decompress(data[41 : 41 + idat_len])
        assert len(raw) == 64 * (1 + 64 * 4)


class TestWizardBitmaps:
    @pytest.mark.parametrize("w,h,mark", [(164, 314, 128), (55, 58, 48)])
    def test_bmp_dimensions(self, assets, w, h, mark):
        data = assets._bmp_file(assets._wizard_canvas(w, h, mark))
        assert data[:2] == b"BM"
        bw, bh = struct.unpack_from("<ii", data, 18)
        assert (bw, bh) == (w, h)
        # Declared file size matches reality (BMP loaders reject mismatches).
        assert struct.unpack_from("<I", data, 2)[0] == len(data)


class TestVersionInfo:
    def test_written_fields(self, assets, tmp_path):
        path = tmp_path / "version_info.txt"
        assets.write_version_info(path, "1.2.3")
        text = path.read_text(encoding="utf-8")
        assert "1, 2, 3, 0" in text
        assert "'ProductName', 'Seed Code'" in text
        assert "'OriginalFilename', 'seedcode.exe'" in text

    def test_exe_icon_probe(self, assets, tmp_path):
        ico = tmp_path / "s.ico"
        png256 = assets.build_ico(ico)
        # An "exe" containing the icon payload passes; one without it exits.
        good = tmp_path / "good.exe"
        good.write_bytes(b"MZ" + png256)
        assets.verify_exe_has_icon(good, ico)
        bad = tmp_path / "bad.exe"
        bad.write_bytes(b"MZ" + b"\x00" * 1024)
        with pytest.raises(SystemExit):
            assets.verify_exe_has_icon(bad, ico)


class TestRepoAssets:
    """The committed assets must always be valid and current."""

    def test_committed_ico_is_valid(self, assets):
        ico = Path(__file__).resolve().parents[1] / "assets" / "windows" / "seedcode.ico"
        assert ico.exists(), "run: python scripts/windows/build_assets.py"
        assets.verify_ico(ico)
