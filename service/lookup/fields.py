"""Supported MInAS environmental triad columns."""

from enum import StrEnum


class TriadField(StrEnum):
    """The three supported environmental metadata columns."""

    BROAD = "env_broad_scale"
    LOCAL = "env_local_scale"
    MEDIUM = "env_medium"
