"""Validate explicit report bindings without opening databases or reading tokens."""
from apps.monitoring.contracts import identifier
from .storage import safe_directory


def validate_binding(mode, directory, device_id):
    if mode not in ('full', 'water-only'):
        raise ValueError('INVALID_SIMULATION_MODE')
    if directory is not None or device_id is not None:
        if mode != 'water-only' or not directory or not device_id:
            raise ValueError('DEVICE_REPORT_BINDING_REQUIRED')
        safe_directory(directory)
        identifier(device_id)
