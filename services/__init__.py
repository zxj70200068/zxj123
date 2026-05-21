"""Application services: thin orchestration over core/, consumed by ui/.

Importing this package gives you the four service classes used by the UI
layer and any future CLI / batch entry point:

* :class:`SimulationService` -- replay a scenario / sequence plan.
* :class:`OptimizationService` -- chiller-group SLSQP allocator wrapper.
* :class:`ControlService` -- DDC/BACnet front-end (the only API a real
  edge gateway should call).
* :class:`ReportingService` -- text-only run + alarm summarization.
"""

from services.control_service import ControlService
from services.optimization_service import OptimizationService
from services.reporting_service import ReportingService
from services.simulation_service import SimulationService

__all__ = [
    "SimulationService",
    "OptimizationService",
    "ControlService",
    "ReportingService",
]
