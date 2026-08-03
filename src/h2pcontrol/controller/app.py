import asyncio
import logging
import sys

import qasync
from PySide6.QtWidgets import QApplication

from h2pcontrol.controller.ui.main_window import MainWindow


def main() -> None:
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


if __name__ == "__main__":
    main()
