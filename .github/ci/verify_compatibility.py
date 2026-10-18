"""Require actual successful test cases, not just a green process exit."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def verify_report(path):
    root = ET.parse(path).getroot()
    if root.tag not in {'testsuite', 'testsuites'}:
        raise ValueError('Invalid JUnit report')
    cases = list(root.iter('testcase'))
    if not cases:
        raise ValueError('Compatibility acceptance requires executed tests')
    if any(list(root.iter(tag)) for tag in ('failure', 'error', 'skipped')):
        raise ValueError('Compatibility tests failed, errored or skipped')
    for suite in root.iter():
        if suite.tag in {'testsuite', 'testsuites'}:
            if any(int(suite.get(key, '0')) for key in ('failures', 'errors', 'skipped')):
                raise ValueError('JUnit summary contains unsuccessful tests')
    return len(cases)


if __name__ == '__main__':
    print(f'Compatibility acceptance: {verify_report(Path(sys.argv[1]))} executed tests passed.')
