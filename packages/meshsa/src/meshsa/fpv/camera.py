"""FPV camera capture core (Phase 2): frame ingest + index logging + encode.

:class:`CaptureWriter` owns the **one** thread the camera subsystem adds (spec
§3 otherwise reserves threading for the flight logger). The capture loop reads
:class:`Frame`s from an injected :class:`meshsa.fpv.protocols.CameraSource`,
stamps each with the **same** injected :class:`meshsa.protocols.Clock` the logger
uses (so frame timestamps interleave with telemetry on a single timebase),
records the frame index via :meth:`FlightLogger.record_frame` (the
``frames.jsonl`` contract already shipped — additive, no ``DATASET_SCHEMA``
bump), and hands the raw frame buffer to an injected ``encode`` callable. The
real muxer never runs in tests because ``encode`` is injected.

Backpressure mirrors :meth:`FlightLogger._enqueue_lossy`: a bounded
``queue.Queue`` drops-and-counts on overflow (``dropped_frames`` + a warning),
so a slow encoder can never wedge the capture loop or unbounded-buffer memory.

The frame pixel buffer lives in :attr:`Frame.data` typed ``Any`` — **no numpy in
our code**; only the ``# pragma: no cover`` real backend / encoder touches it.
The real OpenCV backend is imported lazily *inside* the factory so
``import meshsa.fpv`` never pulls a camera dependency (locked by
``test_fpv_imports_clean``).
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from ..protocols import Clock
from .config import CameraSettings
from .protocols import CameraSource, MonotonicClock

if TYPE_CHECKING:
    from .flight_logger import FlightLogger

_log = structlog.get_logger("meshsa.fpv.camera")

#: Queue marker that tells the encode thread to drain and stop.
_SENTINEL: Any = object()

#: A frame buffer plus the index/encode callable destination.
EncodeCallable = Callable[[Any], None]
#: Builds a :class:`CameraSource` (the real backend lives behind the factory).
CameraFactory = Callable[[], CameraSource]
#: Bounded idle back-off used by the capture loop; injectable for deterministic tests.
SleepCallable = Callable[[float], None]


@dataclass(frozen=True)
class Frame:
    """One captured video frame.

    ``data`` holds the raw pixel buffer (e.g. a numpy ndarray from OpenCV); it is
    typed ``Any`` and only ever touched inside the ``# pragma: no cover`` encoder
    so no numpy dependency leaks into the pure code path.
    """

    idx: int
    t: float
    data: Any


class CaptureWriter:
    """Daemon-threaded camera capture: read -> stamp -> log index -> encode.

    The capture loop pulls frames from ``source``, stamps each with ``clock`` (the
    same timebase as ``logger``), records the frame index, and enqueues the buffer
    for ``encode`` on a bounded queue that drops-and-counts on overflow. ``close``
    is idempotent, drains + joins with a bounded timeout, and closes ``source``.
    """

    def __init__(
        self,
        settings: CameraSettings,
        source: CameraSource,
        logger: FlightLogger,
        encode: EncodeCallable,
        *,
        clock: Clock | None = None,
        sleep: SleepCallable | None = None,
    ) -> None:
        self._s = settings
        self._source = source
        self._logger = logger
        self._encode = encode
        self._clock: Clock = clock or MonotonicClock()
        #: Injectable idle back-off (defaults to ``time.sleep``); tests substitute a
        #: fake to assert the loop backs off instead of spinning, deterministically.
        self._sleep: SleepCallable = sleep or time.sleep

        self._queue: queue.Queue[Any] = queue.Queue(maxsize=settings.capture_queue_len)
        self._capture_thread: threading.Thread | None = None
        self._encode_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started = False
        self._closed = False

        #: Frames dropped because the encode queue was full (overflow); surfaced
        #: alongside the logger's own ``dropped_records`` for the manifest.
        self.dropped_frames = 0

    # -- lifecycle ---------------------------------------------------------- #

    def __enter__(self) -> CaptureWriter:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def start(self) -> None:
        """Start the capture + encode threads (idempotent)."""
        if self._started:  # pragma: no cover - guarded by callers/tests
            return
        self._started = True
        self._encode_thread = threading.Thread(
            target=self._encode_loop, name="fpv-encode", daemon=True
        )
        self._encode_thread.start()
        self._capture_thread = threading.Thread(
            target=self._capture_loop, name="fpv-capture", daemon=True
        )
        self._capture_thread.start()
        _log.debug("capture writer started")

    def close(self) -> None:
        """Stop capture, release the source, drain the encode queue, join.

        Idempotent. Bounded by ``capture_shutdown_timeout_s`` on every join so a
        wedged encoder can never hang the caller. The source is closed **before**
        the capture-thread join: a backend blocked inside ``read_frame`` is
        unblocked by ``close()``, so the join cannot time out waiting on it.
        Preserves SIGINT semantics: a ``KeyboardInterrupt`` during capture
        propagates out of the loop, and this teardown still runs to release the
        device and join the encode thread.
        """
        if self._closed or not self._started:
            return
        self._closed = True
        # Both threads are always set by start(), which close() requires (the
        # not-started guard above returns early), so neither can be None here.
        assert self._capture_thread is not None
        assert self._encode_thread is not None
        timeout = self._s.capture_shutdown_timeout_s
        self._stop.set()
        # Close the source FIRST to unblock any in-flight read_frame, then join;
        # otherwise a backend wedged in read_frame would make the join time out.
        # Best-effort: a source whose close() raises must not abort teardown before
        # the joins below, which would leak the capture/encode threads.
        try:
            self._source.close()
        except Exception:
            _log.debug("capture source close error")
        self._capture_thread.join(timeout=timeout)
        if self._capture_thread.is_alive():  # pragma: no cover - capture wedged
            _log.warning("capture thread did not terminate within timeout")
        # Signal the encode thread to drain remaining frames then exit.
        try:
            self._queue.put(_SENTINEL, timeout=timeout)
        except queue.Full:  # pragma: no cover - encoder wedged (queue stuck full)
            _log.warning("encode queue full; could not enqueue shutdown sentinel")
        self._encode_thread.join(timeout=timeout)
        if self._encode_thread.is_alive():  # pragma: no cover - encoder wedged
            _log.warning("encode thread did not terminate within timeout")
        _log.debug("capture writer closed", dropped_frames=self.dropped_frames)

    # -- internals ---------------------------------------------------------- #

    def _capture_loop(self) -> None:
        while not self._stop.is_set():
            try:
                frame = self._source.read_frame()
                if frame is None:
                    # Source disconnected or between frames: back off a bounded
                    # interval instead of spinning at 100% CPU re-checking stop.
                    self._sleep(self._s.idle_poll_s)
                    continue
                t = self._clock.now()
                self._logger.record_frame(frame.idx, t)
                self._enqueue_lossy(frame.data)
            except Exception:  # noqa: BLE001 - one bad read must never kill the thread
                # A read_frame/record_frame failure is logged and skipped; killing
                # the daemon thread here would silently stop all capture.
                _log.exception("capture iteration failed; continuing")
                self._sleep(self._s.idle_poll_s)

    def _enqueue_lossy(self, buffer: Any) -> None:
        try:
            self._queue.put_nowait(buffer)
        except queue.Full:
            self.dropped_frames += 1
            _log.warning("encode queue full; dropping frame", dropped=self.dropped_frames)

    def _encode_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                self._queue.task_done()
                break
            try:
                self._encode(item)
            except Exception:  # noqa: BLE001 - a bad frame must never kill the thread
                _log.exception("frame encode failed; dropping frame")
            finally:
                self._queue.task_done()


def _default_camera_factory(settings: CameraSettings) -> CameraFactory:  # pragma: no cover
    """Build an OpenCV-backed :class:`CameraSource` (real hardware; not unit-tested).

    OpenCV (``cv2``) is imported lazily *inside* the returned factory so importing
    this module never requires a camera backend. Jetson deployments may swap this
    for a v4l2/GStreamer source — the :class:`CameraSource` Protocol makes the
    backend interchangeable without touching :class:`CaptureWriter`.
    """

    def factory() -> CameraSource:
        import cv2  # lazy: importing this module must not require opencv

        video_capture: Any = cv2.VideoCapture
        cap = video_capture(settings.device)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.height)
        cap.set(cv2.CAP_PROP_FPS, settings.fps)

        class _OpenCvSource:
            def __init__(self) -> None:
                self._idx = 0

            def read_frame(self) -> Frame | None:
                ok, data = cap.read()
                if not ok:
                    return None
                frame = Frame(idx=self._idx, t=0.0, data=data)
                self._idx += 1
                return frame

            def close(self) -> None:
                cap.release()

        return _OpenCvSource()

    return factory
