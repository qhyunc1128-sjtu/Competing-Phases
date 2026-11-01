"""Materials Project 2026 identifier compatibility.

MP material IDs may be written as mp-149, mp-ft or mp-aaaaaaft.
Task IDs may be numeric mp-... or bare alphabetic strings.
Treat *material* IDs and *task* IDs as different entity types; the shared
base-26 conversion does not imply they reference the same document.

Reference: Materials Project 2026-04-13 identifier migration; a=0 ... z=25.
"""
from __future__ import annotations

import re

_MAT_NUM = re.compile(r'mp-(\d+)$', re.I)
_MAT_ALPHA = re.compile(r'mp-([a-z]+)$', re.I)
_TASK_ALPHA = re.compile(r'[a-z]+$', re.I)
_WRAPPER = re.compile(r'^(?:MPID|AlphaID)\((.*?)\)$')


def _string(value) -> str:
    if value is None:
        return ''
    s = str(value).strip()
    match = _WRAPPER.fullmatch(s)
    return (match.group(1) if match else s).strip()


def alpha_to_int(letters: str) -> int:
    if not letters or not re.fullmatch('[a-z]+', letters, flags=re.I):
        raise ValueError(f'Invalid MP base-26 identifier: {letters!r}')
    result = 0
    for ch in letters.lower():
        result = result * 26 + (ord(ch) - ord('a'))
    return result


def material_id_legacy(value) -> str:
    """Convert an MP *material_id* to the traditional numeric mp- ID.

    Unknown strings (e.g. mvc-1234, user IDs) are left unchanged.
    """
    s = _string(value)
    if _MAT_NUM.fullmatch(s):
        return 'mp-' + _MAT_NUM.fullmatch(s).group(1)
    alpha = _MAT_ALPHA.fullmatch(s)
    if alpha:
        return f'mp-{alpha_to_int(alpha.group(1))}'
    return s


def task_id_legacy(value) -> str:
    """Convert MP *task_id* (possibly no mp- prefix) to mp-<integer>."""
    s = _string(value)
    if not s:
        return ''
    if _MAT_NUM.fullmatch(s):
        return 'mp-' + _MAT_NUM.fullmatch(s).group(1)
    alpha = _MAT_ALPHA.fullmatch(s)
    if alpha:
        return f'mp-{alpha_to_int(alpha.group(1))}'
    if _TASK_ALPHA.fullmatch(s):
        return f'mp-{alpha_to_int(s)}'
    return s


def material_url(value) -> str:
    legacy = material_id_legacy(value)
    return f'https://materialsproject.org/materials/{legacy}' if _MAT_NUM.fullmatch(legacy) else ''
