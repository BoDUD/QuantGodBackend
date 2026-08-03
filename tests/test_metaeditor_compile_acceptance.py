import codecs
import importlib.util
import os
import tempfile
import time
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "validate_metaeditor_compile.py"
SPEC = importlib.util.spec_from_file_location("validate_metaeditor_compile", MODULE_PATH)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(validator)

EXPECTED_WINDOWS_SOURCE = r"C:\qg\compile-run-test\QuantGod_MultiStrategy.mq5"
VALID_COMPILE_RECORD = (
    f"{EXPECTED_WINDOWS_SOURCE} : information: compiling {EXPECTED_WINDOWS_SOURCE}\n"
)


class MetaEditorCompileAcceptanceTests(unittest.TestCase):
    def write_attempt(
        self,
        root: Path,
        *,
        log_bytes: bytes,
        ex5_bytes: bytes = b"fresh-ex5",
        ex5_fresh: bool = True,
        log_fresh: bool = True,
        source_newer: bool = False,
    ) -> tuple[Path, Path, Path, Path]:
        source = root / "QuantGod_MultiStrategy.mq5"
        marker = root / ".compile-started"
        ex5 = root / "QuantGod_MultiStrategy.ex5"
        log = root / "compile.log"
        source.write_text("// shadow/read-only test source\n", encoding="utf-8")
        marker.write_bytes(b"")
        ex5.write_bytes(ex5_bytes)
        log.write_bytes(log_bytes)
        marker_ns = time.time_ns() - 10_000_000_000
        fresh_ns = marker_ns + 5_000_000_000
        stale_ns = marker_ns - 5_000_000_000
        source_ns = fresh_ns + 1_000_000_000 if source_newer else marker_ns - 1_000_000_000
        os.utime(source, ns=(source_ns, source_ns))
        os.utime(marker, ns=(marker_ns, marker_ns))
        os.utime(ex5, ns=((fresh_ns if ex5_fresh else stale_ns),) * 2)
        os.utime(log, ns=((fresh_ns if log_fresh else stale_ns),) * 2)
        return source, ex5, log, marker

    def assert_rejected(
        self,
        source: Path,
        ex5: Path,
        log: Path,
        marker: Path,
        *,
        expected_windows_source: str = EXPECTED_WINDOWS_SOURCE,
    ) -> None:
        with self.assertRaises(validator.CompileAcceptanceError):
            validator.validate_compile_acceptance(
                source_path=source,
                ex5_path=ex5,
                log_path=log,
                marker_path=marker,
                expected_windows_source=expected_windows_source,
            )

    def test_accepts_fresh_exact_zero_result_in_supported_encodings(self):
        text = (
            VALID_COMPILE_RECORD
            + "Result: 0 errors, 0 warnings, 812 msec elapsed\n"
        )
        encoded_logs = {
            "utf8": text.encode("utf-8"),
            "utf8_bom": codecs.BOM_UTF8 + text.encode("utf-8"),
            "utf16_bom": text.encode("utf-16"),
            "utf16le_no_bom": text.encode("utf-16-le"),
            "utf16be_no_bom": text.encode("utf-16-be"),
        }
        for name, log_bytes in encoded_logs.items():
            with self.subTest(encoding=name), tempfile.TemporaryDirectory() as tmp_dir:
                source, ex5, log, marker = self.write_attempt(Path(tmp_dir), log_bytes=log_bytes)
                validator.validate_compile_acceptance(
                    source_path=source,
                    ex5_path=ex5,
                    log_path=log,
                    marker_path=marker,
                    expected_windows_source=EXPECTED_WINDOWS_SOURCE,
                )

    def test_normalizes_windows_source_case_and_separator_style(self):
        logged_source = "c:/QG/COMPILE-RUN-TEST/QuantGod_MultiStrategy.mq5"
        log_bytes = (
            f"{logged_source} : INFORMATION: compiling {logged_source}\n"
            "Result: 0 errors, 0 warnings\n"
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp_dir:
            source, ex5, log, marker = self.write_attempt(Path(tmp_dir), log_bytes=log_bytes)
            validator.validate_compile_acceptance(
                source_path=source,
                ex5_path=ex5,
                log_path=log,
                marker_path=marker,
                expected_windows_source=EXPECTED_WINDOWS_SOURCE,
            )

    def test_rejects_stale_or_empty_artifacts(self):
        valid_log = (VALID_COMPILE_RECORD + "Result: 0 errors, 0 warnings\n").encode("utf-8")
        cases = {
            "stale_ex5": {"ex5_fresh": False},
            "stale_log": {"log_fresh": False},
            "empty_ex5": {"ex5_bytes": b""},
            "empty_log": {"log_bytes": b""},
            "source_newer_than_artifacts": {"source_newer": True},
        }
        for name, overrides in cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp_dir:
                kwargs = {"log_bytes": valid_log, **overrides}
                source, ex5, log, marker = self.write_attempt(Path(tmp_dir), **kwargs)
                self.assert_rejected(source, ex5, log, marker)

    def test_rejects_nonzero_duplicate_or_nonfinal_result(self):
        logs = {
            "compile_error": (VALID_COMPILE_RECORD + "Result: 1 errors, 0 warnings\n").encode("utf-8"),
            "warning": (VALID_COMPILE_RECORD + "Result: 0 errors, 1 warnings\n").encode("utf-8"),
            "stale_success_then_failure": (
                VALID_COMPILE_RECORD + "Result: 0 errors, 0 warnings\nResult: 1 errors, 0 warnings\n"
            ).encode("utf-8"),
            "success_not_final": (
                VALID_COMPILE_RECORD
                + "Result: 0 errors, 0 warnings\nerror: compiler terminated unexpectedly\n"
            ).encode("utf-8"),
            "embedded_success": (
                VALID_COMPILE_RECORD + "prefix Result: 0 errors, 0 warnings\n"
            ).encode("utf-8"),
        }
        for name, log_bytes in logs.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp_dir:
                source, ex5, log, marker = self.write_attempt(Path(tmp_dir), log_bytes=log_bytes)
                self.assert_rejected(source, ex5, log, marker)

    def test_rejects_wrong_mismatched_or_duplicate_compile_source_records(self):
        wrong_source = r"C:\qg\other-run\QuantGod_MultiStrategy.mq5"
        records = {
            "wrong_both_sides": (
                f"{wrong_source} : information: compiling {wrong_source}\n"
            ),
            "mismatched_compiled_side": (
                f"{EXPECTED_WINDOWS_SOURCE} : information: compiling {wrong_source}\n"
            ),
            "mismatched_source_side": (
                f"{wrong_source} : information: compiling {EXPECTED_WINDOWS_SOURCE}\n"
            ),
            "duplicate_expected_record": VALID_COMPILE_RECORD + VALID_COMPILE_RECORD,
            "extra_wrong_record": (
                VALID_COMPILE_RECORD
                + f"{wrong_source} : information: compiling {wrong_source}\n"
            ),
        }
        for name, record_text in records.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp_dir:
                log_bytes = (record_text + "Result: 0 errors, 0 warnings\n").encode("utf-8")
                source, ex5, log, marker = self.write_attempt(Path(tmp_dir), log_bytes=log_bytes)
                self.assert_rejected(source, ex5, log, marker)

    def test_rejects_malformed_or_ambiguous_encoding_without_fallback(self):
        logs = {
            "malformed_utf16_bom": codecs.BOM_UTF16_LE + b"\xff",
            "invalid_utf8": b"\x80Result: 0 errors, 0 warnings\n",
            "ambiguous_nuls": b"R\x00e\x00s\x00u\x00l\x00t\x00:\x00\x00\x00garbage",
            "control_byte": b"Result: 0 errors, 0 warnings\x01\n",
        }
        for name, log_bytes in logs.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp_dir:
                source, ex5, log, marker = self.write_attempt(Path(tmp_dir), log_bytes=log_bytes)
                self.assert_rejected(source, ex5, log, marker)

    def test_rejects_symlinked_evidence(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source, ex5, log, marker = self.write_attempt(
                root,
                log_bytes=(VALID_COMPILE_RECORD + "Result: 0 errors, 0 warnings\n").encode("utf-8"),
            )
            real_log = root / "real.log"
            log.replace(real_log)
            log.symlink_to(real_log)
            self.assert_rejected(source, ex5, log, marker)


if __name__ == "__main__":
    unittest.main()
