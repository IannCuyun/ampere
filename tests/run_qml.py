"""Run QML tests with the same Qt version installed for the application."""
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from PySide6.QtQuickTest import QUICK_TEST_MAIN
from PySide6.QtCore import QCoreApplication


def main():
    root = Path(__file__).resolve().parent.parent
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['QT_QUICK_BACKEND'] = 'software'
    QCoreApplication.setOrganizationName('AmpereTests')
    with TemporaryDirectory(prefix='ampere-qml-tests-') as config:
        os.environ['XDG_CONFIG_HOME'] = config
        return QUICK_TEST_MAIN('ampere', [sys.argv[0], '-input',
            str(root / 'tests/qml'), '-import', str(root / 'qml'), *sys.argv[1:]])


if __name__ == '__main__':
    raise SystemExit(main())
