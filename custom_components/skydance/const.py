"""Constants for the Skydance integration."""

from datetime import timedelta

DOMAIN = "skydance"
MANUFACTURER = "Skydance"
PLATFORMS = ["light"]

CONNECT_TIMEOUT = 5.0
"""Seconds to wait for a TCP connection to the relay."""

COMMAND_TIMEOUT = 3.0
"""Seconds to wait for the relay to answer a single command."""

CLOSE_TIMEOUT = 2.0
"""Seconds to wait for a connection to close."""

PAUSE_BETWEEN_WRITES = 0.2
"""Seconds to wait between commands, the relay cannot handle them faster."""

COMMAND_ATTEMPTS = 2
"""How many times a command is sent before giving up."""

RETRY_PAUSE = 0.3
"""Seconds to wait between attempts of the same command."""

KEEPALIVE_INTERVAL = timedelta(minutes=1)
"""How often the connection is pinged to detect a silently dead session."""
