"""Configuration loading for Komorebi.

Handles loading settings from YAML config file.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ProjectConfig:
    """Configuration for a tracked project."""

    path: str
    active: bool = True


@dataclass
class CalendarConfig:
    """Configuration for Google Calendar integration."""

    enabled: bool = True
    default_calendar: str = "primary"
    credentials_path: Path = field(
        default_factory=lambda: Path("~/.config/komorebi/credentials.json")
    )
    token_path: Path = field(default_factory=lambda: Path("~/.config/komorebi/token.json"))


@dataclass
class Config:
    """Main configuration container."""

    data_dir: Path = field(default_factory=lambda: Path("./data"))
    projects: dict[str, ProjectConfig] = field(default_factory=dict)
    calendar: CalendarConfig = field(default_factory=CalendarConfig)


def load_config(config_path: Path) -> Config:
    """Load configuration from YAML file.

    Args:
        config_path: Path to settings.yaml file.

    Returns:
        Parsed Config object with defaults for missing values.
    """
    if not config_path.exists():
        return Config()

    with open(config_path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    # Parse projects
    projects: dict[str, ProjectConfig] = {}
    for name, proj_data in raw.get("projects", {}).items():
        if isinstance(proj_data, dict):
            projects[name] = ProjectConfig(
                path=proj_data.get("path", ""),
                active=proj_data.get("active", True),
            )

    # Parse calendar
    cal_data = raw.get("calendar", {})
    calendar = CalendarConfig(
        enabled=cal_data.get("enabled", True),
        default_calendar=cal_data.get("default_calendar", "primary"),
        credentials_path=Path(
            cal_data.get("credentials_path", "~/.config/komorebi/credentials.json")
        ),
        token_path=Path(cal_data.get("token_path", "~/.config/komorebi/token.json")),
    )

    # Parse data_dir
    data_dir = Path(raw.get("data_dir", "./data"))

    return Config(
        data_dir=data_dir,
        projects=projects,
        calendar=calendar,
    )
