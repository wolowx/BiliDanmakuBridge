# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sender_server  # noqa: E402


def make_session(
    directory: Path,
    name: str = "livetrans_20260101_000000_translation.txt",
    text: str = "[00:00:01] 你好\n",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


class DetectTranscriptDirTests(unittest.TestCase):
    def test_finds_livetranslate_transcripts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            transcripts = root / "LiveTranslate" / "transcripts"
            make_session(transcripts)
            found = sender_server.detect_transcript_dir(
                roots=[root], timeout=2
            )
            self.assertEqual(found, transcripts)

    def test_prefers_newest_session(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = root / "Old" / "transcripts"
            new = root / "New" / "transcripts"
            old_file = make_session(
                old, "livetrans_20260101_000000_translation.txt"
            )
            new_file = make_session(
                new, "livetrans_20260102_000000_translation.txt"
            )
            os.utime(old_file, (1000, 1000))
            os.utime(new_file, (2000, 2000))
            found = sender_server.detect_transcript_dir(
                roots=[root], timeout=2
            )
            self.assertEqual(found, new)

    def test_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(
                sender_server.detect_transcript_dir(
                    roots=[Path(td)], timeout=1
                )
            )

    def test_resolve_trusts_explicit_existing_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            empty = root / "my_live_translate" / "transcripts"
            empty.mkdir(parents=True)
            resolved = sender_server.resolve_transcript_dir(
                {"transcript_dir": str(empty)}, roots=[root]
            )
            self.assertEqual(resolved, empty)

    def test_resolve_falls_back_to_auto_when_configured_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            transcripts = root / "Portable" / "LiveTranslate" / "transcripts"
            make_session(transcripts)
            resolved = sender_server.resolve_transcript_dir(
                {"transcript_dir": str(root / "missing")},
                roots=[root],
            )
            self.assertEqual(resolved, transcripts)


class FormatTextsTests(unittest.TestCase):
    def test_long_text_splits_at_punctuation(self):
        cfg = {
            "prefix": "【",
            "suffix": "】",
            "max_length": 10,
            "min_length": 1,
            "strip_period": True,
        }
        parts = sender_server.format_texts(
            cfg, "第一句话。第二句话。第三句话。"
        )
        self.assertTrue(parts)
        for part in parts:
            self.assertLessEqual(len(part), 10)


if __name__ == "__main__":
    unittest.main()
