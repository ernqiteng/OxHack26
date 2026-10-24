"""Settings loaded from .env: database URL, battery parameters, Elexon base URL, Tiger and Vultr credentials.

Owner: shared (Phase 0). See docs/plan.md and docs/needs.md section B6.

Usage:
    from tempo.config import settings
    s = settings()
    s.database_url, s.battery.capacity_mwh, s.tiger.project_id, s.vultr.api_key

Nothing here talks to the network. Missing values are None (or the documented default), so importing
this module never fails; callers that need a value call `require()`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "models"

# Load .env once, without overriding variables already set in the process (CI, systemd, tests).
load_dotenv(REPO_ROOT / ".env", override=False)


def env(name: str, default: str | None = None) -> str | None:
    """Return the environment variable, treating empty strings as unset."""
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def require(name: str) -> str:
    value = env(name)
    if value is None:
        raise RuntimeError(f"{name} is not set; copy .env.example to .env and fill it in (docs/needs.md B6)")
    return value


@dataclass(frozen=True)
class BatteryParams:
    capacity_mwh: float = 2.0
    power_mw: float = 1.0
    rt_efficiency: float = 0.90
    cycle_cost_gbp: float = 20.0


@dataclass(frozen=True)
class TigerSettings:
    project_id: str | None
    access_key: str | None
    secret_key: str | None
    primary_service_id: str | None
    base_url: str = "https://console.cloud.tigerdata.com/public/api/v1"

    @property
    def configured(self) -> bool:
        return all([self.project_id, self.access_key, self.secret_key])


@dataclass(frozen=True)
class VultrSettings:
    api_key: str | None
    region: str = "ewr"
    worker_plan: str = "vc2-1c-1gb"
    worker_snapshot_id: str | None = None
    sshkey_id: str | None = None
    base_url: str = "https://api.vultr.com/v2"

    @property
    def configured(self) -> bool:
        return self.api_key is not None


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    test_database_url: str
    elexon_base_url: str
    price_provider: str
    mid_availability_delay_min: int
    battery: BatteryParams
    tiger: TigerSettings
    vultr: VultrSettings
    live: bool

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=env("TEMPO_DATABASE_URL"),
            test_database_url=env(
                "TEMPO_TEST_DATABASE_URL", "postgres://postgres:tempo@localhost:5433/postgres"
            ),
            elexon_base_url=env("ELEXON_BASE_URL", "https://data.elexon.co.uk/bmrs/api/v1"),
            price_provider=env("PRICE_PROVIDER", "APXMIDP"),
            mid_availability_delay_min=int(env("MID_AVAILABILITY_DELAY_MIN", "10")),
            battery=BatteryParams(
                capacity_mwh=float(env("BATTERY_CAPACITY_MWH", "2")),
                power_mw=float(env("BATTERY_POWER_MW", "1")),
                rt_efficiency=float(env("BATTERY_RT_EFFICIENCY", "0.90")),
                cycle_cost_gbp=float(env("BATTERY_CYCLE_COST_GBP", "20")),
            ),
            tiger=TigerSettings(
                project_id=env("TIGERDATA_PROJECT_ID"),
                access_key=env("TIGERDATA_ACCESS_KEY"),
                secret_key=env("TIGERDATA_SECRET_KEY"),
                primary_service_id=env("TIGER_PRIMARY_SERVICE_ID"),
                base_url=env("TIGERDATA_BASE_URL", "https://console.cloud.tigerdata.com/public/api/v1"),
            ),
            vultr=VultrSettings(
                api_key=env("VULTR_API_KEY"),
                region=env("VULTR_REGION", "ewr"),
                worker_plan=env("VULTR_WORKER_PLAN", "vc2-1c-1gb"),
                worker_snapshot_id=env("VULTR_WORKER_SNAPSHOT_ID"),
                sshkey_id=env("VULTR_SSHKEY_ID"),
                base_url=env("VULTR_BASE_URL", "https://api.vultr.com/v2"),
            ),
            live=env("TEMPO_LIVE", "0") == "1",
        )


@lru_cache(maxsize=1)
def settings() -> Settings:
    """Process-wide settings, read once. Tests that mutate the environment call `settings.cache_clear()`."""
    return Settings.from_env()
