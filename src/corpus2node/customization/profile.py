"""Load and validate customer profile packages.

``CUSTOMER_PROFILE=longxin`` reads ``<repo>/longxin/profile.yaml``.
Any other value (including ``default``) returns the built-in default profile.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from corpus2node.config import ROOT_DIR, settings

PERSONAS = frozenset({"executive", "researcher", "operator"})
NAV_ITEMS = frozenset({"home", "new", "discover", "workspace"})


class BrandConfig(BaseModel):
    product_name: str = "corpus2node"
    tagline: str = ""


class PersonaConfig(BaseModel):
    label: str
    description: str = ""
    landing: str
    nav: list[str] = Field(default_factory=list)

    @field_validator("nav")
    @classmethod
    def _nav_known(cls, value: list[str]) -> list[str]:
        unknown = [item for item in value if item not in NAV_ITEMS]
        if unknown:
            raise ValueError(f"Unknown nav items: {', '.join(unknown)}")
        return value


class FeaturesConfig(BaseModel):
    discovery: bool = True
    notes: bool = True
    level_test: bool = True


class CustomerProfile(BaseModel):
    schema_version: int = 1
    customer_id: str = "default"
    brand: BrandConfig = Field(default_factory=BrandConfig)
    personas: dict[str, PersonaConfig]
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)

    @field_validator("personas")
    @classmethod
    def _personas_complete(cls, value: dict[str, PersonaConfig]) -> dict[str, PersonaConfig]:
        missing = PERSONAS - set(value)
        if missing:
            raise ValueError(f"Missing personas: {', '.join(sorted(missing))}")
        extra = set(value) - PERSONAS
        if extra:
            raise ValueError(f"Unknown personas: {', '.join(sorted(extra))}")
        return value

    def landing_for(self, persona: str) -> str:
        key = persona if persona in self.personas else "operator"
        return self.personas[key].landing

    def nav_for(self, persona: str) -> list[str]:
        key = persona if persona in self.personas else "operator"
        return list(self.personas[key].nav)

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump()


def default_profile() -> CustomerProfile:
    return CustomerProfile(
        customer_id="default",
        brand=BrandConfig(product_name="corpus2node", tagline="knowledge graph"),
        personas={
            "executive": PersonaConfig(
                label="决策层",
                description="看总结卡片、评估风险/ROI",
                landing="/discover?mode=scientific",
                nav=["discover", "home"],
            ),
            "researcher": PersonaConfig(
                label="研发",
                description="看证据链、深度探针、论文对比",
                landing="/discover?mode=scientific&focus=evidence",
                nav=["discover", "home"],
            ),
            "operator": PersonaConfig(
                label="执行",
                description="上传资料、看笔记、水平测试",
                landing="/",
                nav=["home", "new"],
            ),
        },
        features=FeaturesConfig(),
    )


def _profile_path(customer_id: str) -> Path | None:
    if customer_id == "longxin":
        path = ROOT_DIR / "longxin" / "profile.yaml"
        return path if path.is_file() else None
    candidate = ROOT_DIR / "customer_profiles" / customer_id / "profile.yaml"
    return candidate if candidate.is_file() else None


def load_customer_profile(customer_id: str | None = None) -> CustomerProfile:
    """Load a customer profile by id, falling back to the built-in default."""
    cid = (customer_id or settings.customer_profile or "default").strip() or "default"
    if cid == "default":
        return default_profile()
    path = _profile_path(cid)
    if path is None:
        return default_profile()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Customer profile at {path} must be a mapping.")
    return CustomerProfile.model_validate(raw)


@lru_cache(maxsize=8)
def _cached_profile(customer_id: str) -> CustomerProfile:
    return load_customer_profile(customer_id)


def get_customer_profile(customer_id: str | None = None) -> CustomerProfile:
    cid = (customer_id or settings.customer_profile or "default").strip() or "default"
    return _cached_profile(cid)


def clear_profile_cache() -> None:
    _cached_profile.cache_clear()
