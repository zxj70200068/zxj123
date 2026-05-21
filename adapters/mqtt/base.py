"""Skeleton only. TODO: implement under field deployment.

This module declares the abstract :class:`MQTTAdapter` interface that real
MQTT broker bridge implementations must satisfy. NO real protocol code
lives here; depending on a concrete library (``paho-mqtt``,
``aiomqtt`` etc.) is the responsibility of the deployment package, not
the supervisory core.
"""

from __future__ import annotations

import abc


class MQTTAdapter(abc.ABC):
    """Abstract MQTT field-bus adapter."""

    @abc.abstractmethod
    def connect(self) -> None:
        """Open the MQTT broker connection."""
        raise NotImplementedError

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Close the MQTT broker connection."""
        raise NotImplementedError

    @abc.abstractmethod
    def read_point(self, point_id: str) -> float:
        """Read a numeric MQTT topic value by id."""
        raise NotImplementedError

    @abc.abstractmethod
    def write_point(self, point_id: str, value: float) -> bool:
        """Publish a numeric MQTT topic; return True on success."""
        raise NotImplementedError

    @abc.abstractmethod
    def is_connected(self) -> bool:
        """Return True if the adapter currently holds an open session."""
        raise NotImplementedError


__all__ = ["MQTTAdapter"]
