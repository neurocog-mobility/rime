"""RIME Application entry point."""

import argparse
import sys

from PySide6.QtWidgets import QApplication

from rime_ui import RimeMainWindow


def _parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(prog="rime")
    parser.add_argument(
        "--open",
        dest="open_session",
        metavar="PATH_TO_SESSIONJSON",
        help="Open a session.json file immediately on launch.",
    )
    parser.add_argument(
        "--model",
        dest="model_path",
        metavar="PATH_TO_MODEL_RIME",
        help="Load a .rime model package immediately on launch.",
    )
    parser.add_argument(
        "--compare",
        dest="compare_session",
        metavar="PATH_TO_COMPARISON_SESSIONJSON",
        help="Load a comparison session immediately after opening the main session.",
    )
    args, qt_args = parser.parse_known_args(argv)
    if args.compare_session and not args.open_session:
        parser.error("--compare requires --open")
    return args, qt_args


def main(argv: list[str] | None = None) -> int:
    """Launch the RIME application."""
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args, qt_args = _parse_args(raw_argv)

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("RIME")
    if hasattr(app, "setApplicationDisplayName"):
        app.setApplicationDisplayName("RIME")
    app.setOrganizationName("Neurocognition & Mobility Lab")

    window = RimeMainWindow()
    window.show()
    if args.open_session:
        window.open_session_path(args.open_session)
    if args.compare_session:
        window.load_comparison_path(args.compare_session)
    if args.model_path:
        window.load_model_path(args.model_path)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
