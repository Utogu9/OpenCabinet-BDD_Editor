"""Reject explicit missing-ID markers, never guess from repeated serials."""
import re


def exclusion_reason(serial, system=None):
    token = re.sub(r'[^A-Z0-9]', '', serial.upper())
    if token in {'NONE', 'UNKNOWN', 'NA', 'NOINFO', 'NOINFORMATION', 'NOSERIAL', 'OBSCURED', 'NOTAPPLICABLE'}:
        return 'missing_identifier_marker'
    if system == 'GamePark - GP32' and serial == '1':
        return 'gp32_constant_not_product_identifier'
    return None
