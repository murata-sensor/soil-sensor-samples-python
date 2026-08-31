"""Serial-like test doubles shared by the protocol tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable


class FakeTransport:
    """Serve one scripted response per transaction and record all I/O.

    Unlike the original fake, read() honours its size argument and keeps unread
    bytes for the next call. max_chunk_size can make every response arrive in
    small pieces, which exercises fragmented real serial frames.

    A response is selected on the first read after reset_input(). A write that
    deliberately expects no response (for example a MODBUS broadcast) therefore
    does not consume the next scripted response.
    """

    def __init__(
        self,
        responses: Iterable[bytes] = (),
        *,
        max_chunk_size: int | None = None,
        write_result: int | None = None,
    ):
        if max_chunk_size is not None and max_chunk_size < 1:
            raise ValueError("max_chunk_size must be positive")
        self._responses = deque(bytes(response) for response in responses)
        self._active = bytearray()
        self._response_loaded = False
        self._max_chunk_size = max_chunk_size
        self._write_result = write_result
        self.writes: list[bytes] = []
        self.read_sizes: list[int] = []
        self.read_until_delimiters: list[bytes] = []
        self.read_until_timeouts: list[float | None] = []
        self.reset_count = 0

    def reset_input(self) -> None:
        self.reset_count += 1
        self._active.clear()
        self._response_loaded = False

    def write(self, data: bytes) -> int:
        self.writes.append(bytes(data))
        return len(data) if self._write_result is None else self._write_result

    def _load_response(self) -> None:
        if not self._response_loaded:
            self._active = bytearray(self._responses.popleft() if self._responses else b"")
            self._response_loaded = True

    def read(self, size: int) -> bytes:
        if size < 0:
            raise ValueError("read size must not be negative")
        self.read_sizes.append(size)
        self._load_response()
        take = min(size, len(self._active))
        if self._max_chunk_size is not None:
            take = min(take, self._max_chunk_size)
        result = bytes(self._active[:take])
        del self._active[:take]
        return result

    def read_until(
        self, expected: bytes, *, timeout: float | None = None
    ) -> bytes:
        if not expected:
            raise ValueError("read delimiter must not be empty")
        if timeout is not None and timeout < 0:
            raise ValueError("read timeout must not be negative")
        self.read_until_delimiters.append(bytes(expected))
        self.read_until_timeouts.append(timeout)
        # Model pyserial.read_until(): serial bytes may arrive one at a time,
        # but the method reassembles them through the requested delimiter.
        result = bytearray()
        while not result.endswith(expected):
            chunk = self.read(1)
            if not chunk:
                break
            result.extend(chunk)
        return bytes(result)

    @property
    def pending_response_count(self) -> int:
        """Number of logical responses that no transaction has selected yet."""
        return len(self._responses)
