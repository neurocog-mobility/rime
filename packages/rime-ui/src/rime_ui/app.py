"""RIME entry point: native record inspection and annotation workspaces."""

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from rime_ui.presentation.window import RimeWindow


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="rime", description="RIME annotation workspace and record inspector."
    )
    parser.add_argument(
        "--open", metavar="PATH", help="Open workspace.json or a native .rime document."
    )
    args, qt_args = parser.parse_known_args(argv)
    if any(option in qt_args for option in ["--model", "--compare", "--preview-screen"]):
        parser.error(
            "Use the desktop controls to run models or compare records; preview screens are no longer supported."
        )
    return args, qt_args


def main(argv=None):
    args, qt_args = _parse_args(sys.argv[1:] if argv is None else argv)
    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("RIME")
    app.setApplicationDisplayName("RIME")
    app.setOrganizationName("Neurocognition & Mobility Lab")
    if args.open and Path(args.open).suffix.lower() != ".rime":
        window = RimeWindow()
        window.show()
        window.open_workspace_path(args.open)
    elif args.open:
        from rime_ui.presentation.records import RecordWindow

        window = RecordWindow()
        window.show()
        window.open_path(args.open)
    else:
        window = RimeWindow()
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
