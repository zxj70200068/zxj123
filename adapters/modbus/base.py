"""Skeleton only. TODO: implement under field deployment.

This module declares the abstract :class:`ModbusAdapter` interface that
real Modbus-RTU or Modbus-TCP gateway implementations must satisfy. NO
real protocol code lives here; depending on a concrete library
(``pymodbus``, ``minimalmodbus`` etc.) is the responsibility of the
deployment package, not the supervisory core.
"""

from __future__ import annotations

import abc


class ModbusAdapter(abc.ABC):
    """Abstract Modbus field-bus adapter."""

    @abc.abstractmethod
    def connect(self) -> None:
        """Open the Modbus session (TCP socket or serial port)."""
        raise NotImplementedError

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Close the Modbus session."""
        raise NotImplementedError

    @abc.abstractmethod
    def read_point(self, point_id: str) -> float:
        """Read a numeric Modbus register/coil by id and return its value."""
        raise NotImplementedError

    @abc.abstractmethod
    def write_point(self, point_id: str, value: float) -> bool:
        """Write a numeric Modbus register/coil; return True on success."""
        raise NotImplementedError

    @abc.abstractmethod
    def is_connected(self) -> bool:
        """Return True if the adapter currently holds an open session."""
        raise NotImplementedError


__all__ = ["ModbusAdapter"]
