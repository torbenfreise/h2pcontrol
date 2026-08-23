import argparse
import asyncio
import logging
import sys
from pathlib import Path

from h2pcontrol.controller.scaffold import init_project


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="h2pcontrol", description="Experiment control GUI for h2pcontrol."
    )
    subcommands = parser.add_subparsers(dest="command")
    init = subcommands.add_parser(
        "init", help="Scaffold an experiment project in the given directory"
    )
    init.add_argument(
        "directory", nargs="?", default=Path(), type=Path, help="Target directory (default: .)"
    )
    init.add_argument("--force", action="store_true", help="Overwrite files that already exist")
    return parser.parse_args(argv)


def _run_gui() -> None:
    # Imported lazily so `h2pcontrol init` does not need a display or Qt import cost.
    import qasync
    from PySide6.QtWidgets import QApplication

    from h2pcontrol.controller.ui.main_window import MainWindow

    # Set root to DEBUG so dock can show DEBUG records.
    # console logger stays at INFO so stderr isn't flooded.
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    for handler in logging.getLogger().handlers:
        handler.setLevel(logging.INFO)

    app = QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.resize(800, 600)
    window.show()

    with loop:
        loop.run_forever()


def main() -> None:
    args = _parse_args()
    if args.command == "init":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        init_project(args.directory, force=args.force)
        return
    _run_gui()


if __name__ == "__main__":
    main()
