import logging

logger = logging.getLogger("brand-guardian-telemetry")


def setup_telemetry():
    """
    Telemetry setup — Azure Monitor removed.
    Standard Python logging is active via basicConfig in server.py.
    """
    logger.info("Telemetry: using standard Python logging.")
