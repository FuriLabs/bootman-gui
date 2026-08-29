from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Tuple

class OSTypes(Enum):
    FuriOS = 1
    UbuntuTouch = 2
    Sailfish = 3

@dataclass()
class OSDownloadInfo:
    """Identity and download artifacts for an installable OS release."""

    os_type: OSTypes
    file: Path
    url: str | None = None
    md5_url: str | None = None


@dataclass()
class OSRelease:
    """Display information for an installable operating system release."""

    name: str
    description: str
    download: OSDownloadInfo
    icon_name: str = "computer-symbolic"


@dataclass()
class OperatingSystem:
    """An OS family containing one or more installable releases."""

    name: str
    description: str
    options: Tuple[OSRelease, ...]
    icon_name: str = "computer-symbolic"

    def __post_init__(self):
        if not self.options:
            raise ValueError("An operating system must have at least one release option")
