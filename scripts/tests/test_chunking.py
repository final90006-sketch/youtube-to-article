# -*- coding: utf-8 -*-
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_launcher():
    spec = importlib.util.spec_from_file_location("launcher_chunking", str(ROOT / "launcher.pyw"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load_launcher()


def _segments(n=30):
    return [{"t": i * 60, "text": f"段落{i:02d}" + "x" * 8, "i": i} for i in range(n)]


def _flat(chunks):
    return [s["i"] for c in chunks for s in c]


def test_split_by_chapters_keeps_all_segments_once_and_boundaries(tmp_path):
    segs = _segments()
    chapters = [{"start": i * 6 * 60, "title": f"章{i}"} for i in range(5)]
    chunks = L._split_by_chapters(chapters, segs, max_chars=90, max_chunks=5)
    assert sorted(_flat(chunks)) == list(range(30))
    for chunk in chunks:
        ids = _flat([chunk])
        assert ids == list(range(ids[0], ids[-1] + 1))
        assert ids[0] % 6 == 0
        assert (ids[-1] + 1) % 6 == 0


def test_split_segments_keeps_all_segments_once_when_max_chunks_forces_merge():
    segs = _segments()
    chunks = L._split_segments(segs, max_chars=30, max_chunks=5)
    assert len(chunks) <= 5
    assert _flat(chunks) == list(range(30))
    for chunk in chunks:
        ids = _flat([chunk])
        assert ids == list(range(ids[0], ids[-1] + 1))
