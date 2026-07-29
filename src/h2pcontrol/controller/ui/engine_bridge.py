from PySide6.QtCore import QObject, Signal

from ..runtime.engine import RunEngine
from ..runtime.events import (
    EngineEvent,
    QueueChanged,
    RunFinished,
    RunQueued,
    RunStarted,
    ShotCompleted,
    StateChanged,
)


class EngineBridge(QObject):
    """Translates RunEngine events into Qt signals.
    UI components subscribe here instead of directly to the engine."""

    run_queued = Signal(object)
    run_started = Signal(object)
    shot_completed = Signal(object)
    run_finished = Signal(object)
    queue_changed = Signal(object)
    state_changed = Signal(object)

    def __init__(self, engine: RunEngine, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        engine.subscribe(self._dispatch)

    def _dispatch(self, event: EngineEvent) -> None:
        match event:
            case RunQueued():
                self.run_queued.emit(event)
            case RunStarted():
                self.run_started.emit(event)
            case ShotCompleted():
                self.shot_completed.emit(event)
            case RunFinished():
                self.run_finished.emit(event)
            case QueueChanged():
                self.queue_changed.emit(event)
            case StateChanged():
                self.state_changed.emit(event)

    def close(self) -> None:
        """Unsubscribe from the engine."""
        self._engine.unsubscribe(self._dispatch)
