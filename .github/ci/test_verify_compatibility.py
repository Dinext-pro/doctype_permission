"""Guard against admitting a revision without executed compatibility evidence."""
from pathlib import Path
import tempfile
import unittest
from verify_compatibility import verify_report


class ReportValidation(unittest.TestCase):
    def verify(self, text):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'junit.xml'
            report.write_text(text)
            return verify_report(report)

    def test_executed_success(self):
        self.assertEqual(self.verify('<testsuites><testsuite tests="2"><testcase name="own"/><testcase name="other"/></testsuite></testsuites>'), 2)

    def test_reject_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                verify_report(Path(directory) / 'missing.xml')

    def test_reject_empty_or_invalid(self):
        for text in ('<testsuite tests="0"/>', '<html/>', '<testsuite tests="6"/>'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.verify(text)

    def test_reject_failed_errored_and_skipped(self):
        for tag in ('failure', 'error', 'skipped'):
            text = f'<testsuite><testcase name="permission"><{tag}/></testcase></testsuite>'
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                self.verify(text)

    def test_reject_unsuccessful_summary(self):
        for key in ('failures', 'errors', 'skipped'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(f'<testsuite {key}="1"><testcase name="permission"/></testsuite>')


if __name__ == '__main__':
    unittest.main()
