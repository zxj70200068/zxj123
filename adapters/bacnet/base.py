"""Skeleton only. TODO: implement under field deployment.

This module declares the abstract :class:`BACnetAdapter` interface that
real BACnet/IP or BACnet MS/TP gateway implementations must satisfy. NO
real protocol code lives here; depending on a concrete library
(``bacpypes``, ``BAC0`` etc.) is the responsibility of the deployment
package, not the supervisory core.
"""

from __future__ import annotations

import abc


class BACnetAdapter(abc.ABC):
    """Abstract BACnet field-bus adapter."""

    @abc.abstractmethod
    def connect(self) -> None:
        """Open the BACnet session."""
        raise NotImplementedError

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Close the BACnet session."""
        raise NotImplementedError

    @abc.abstractmethod
    def read_point(self, point_id: str) -> float:
        """Read a numeric BACnet point by id and return its value."""
        raise NotImplementedError

    @abc.abstractmethod
    def write_point(self, point_id: str, value: float) -> bool:
        """Write a numeric BACnet point; return True on success."""
        raise NotImplementedError

    @abc.abstractmethod
    def is_connected(self) -> bool:
        """Return True if the adapter currently holds an open session."""
        raise NotImplementedError


__all__ = ["BACnetAdapter"]
