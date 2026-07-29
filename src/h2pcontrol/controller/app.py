import asyncio
import logging
import sys

import qasync
from PySide6.QtWidgets import QApplication

from h2pcontrol.controller.ui.main_window import MainWindow


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

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
