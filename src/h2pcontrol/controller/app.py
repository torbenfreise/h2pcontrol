import asyncio
import sys

# need to import this before qasync otherwise we get conflicts
import pandas as pd  # noqa: F401
import qasync
from PySide6.QtWidgets import QApplication

from h2pcontrol.controller.ui.main_window import MainWindow


def main() -> None:
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
