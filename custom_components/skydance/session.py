import asyncio

from skydance.network.session import Session


# TODO push down to skydance library
class SequentialWriterSession(Session):
    """
    Session wrapper for pacing write commands.

    Allow only a single write to be processed at time.
    Automatically put sleep between writes to allow Skydance Wi-Fi controller to process commands.
    """

    PAUSE_BETWEEN_WRITES = 0.15  # seconds

    def __init__(self, host, port):
        super().__init__(host, port)
        self._sequential_lock = asyncio.Lock()

    async def write(self, data: bytes):
        async with self._sequential_lock:
            res = await super().write(data)
            await asyncio.sleep(self.PAUSE_BETWEEN_WRITES)
            return res
