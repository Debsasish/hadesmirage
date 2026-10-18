from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MIRAGE_", env_file=".env", extra="ignore")

    profile: Literal["P1-native", "P2-prepared", "P2-cloud"] = "P1-native"
    data_dir: Path = Path(".local")
    database_url: str = Field(default="", repr=False)
    api_port: int = Field(default=8787, ge=1024, le=65535)
    backend_port: int = Field(default=8788, ge=1024, le=65535)
    backend_url: str = ""
    backend_secret: str = Field(default="", repr=False)
    access_code: str = Field(default="", repr=False)
    local_login: bool = True
    allowed_origins: list[str] = [
        "http://127.0.0.1:8787",
        "http://localhost:8787",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]
    model_provider: Literal["fixture", "gemini", "unavailable"] = "fixture"
    gemini_project: str = Field(default="", max_length=200, pattern=r"^[A-Za-z0-9-]*$")
    gemini_location: str = Field(default="global", max_length=100, pattern=r"^[a-z0-9-]+$")
    gemini_model: str = Field(default="", max_length=200, pattern=r"^[A-Za-z0-9._-]*$")
    gemini_api_key: str = Field(
        default="", repr=False, max_length=200, pattern=r"^([A-Za-z0-9._-]{20,200})?$"
    )
    gemini_endpoint: Literal["auto", "developer", "vertex"] = "auto"
    model_egress_approved: bool = False
    decoy_model_wording: bool = False
    session_ttl_seconds: int = Field(default=900, ge=1, le=86400)
    decoy_request_budget: int = Field(default=100, ge=1, le=1000)
    max_engagements: int = Field(default=10, ge=1, le=100)
    model_call_budget: int = Field(default=100, ge=1, le=10000)
    model_case_call_budget: int = Field(default=3, ge=1, le=20)
    model_max_pending: int = Field(default=4, ge=1, le=20)
    model_input_bytes: int = Field(default=65536, ge=4096, le=65536)
    # Cloud demo (P2-cloud): Google Workspace sign-in through Identity-Aware Proxy.
    auth_mode: Literal["local", "iap"] = "local"
    iap_audience: str = Field(default="", max_length=300, pattern=r"^(/projects/[0-9]+/.+)?$")
    iap_allowed_domain: str = Field(default="", max_length=200, pattern=r"^[a-z0-9.-]*$")
    iap_role_map: dict[str, list[Literal["analyst", "approver", "security_admin"]]] = {}
    iap_default_role: Literal["none", "analyst"] = "none"
    iap_tenant: str = Field(default="tenant-demo", max_length=200, pattern=r"^[a-z0-9-]+$")
    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "testserver"]
    model_timeout_seconds: int = Field(default=12, ge=1, le=30)
    max_body_bytes: int = Field(default=65536, ge=1024, le=262144)
    audit_backpressure: int = Field(default=1000, ge=10, le=10000)
    event_retention_days: int = Field(default=7, ge=1, le=365)
    # Optional Telegram bot (disabled by default). Token and webhook secret are never returned.
    telegram_bot_token: str = Field(
        default="", repr=False, max_length=200, pattern=r"^([0-9]{3,20}:[A-Za-z0-9_-]{20,120})?$"
    )
    telegram_mode: Literal["disabled", "polling", "webhook"] = "disabled"
    telegram_webhook_secret: str = Field(
        default="", repr=False, max_length=256, pattern=r"^[A-Za-z0-9_-]*$"
    )
    telegram_api_base: str = Field(
        default="https://api.telegram.org",
        max_length=200,
        pattern=r"^(https://[A-Za-z0-9.-]+(:[0-9]{1,5})?|http://127\.0\.0\.1(:[0-9]{1,5})?)/?$",
    )
    telegram_tenant: str = Field(default="tenant-demo", max_length=200, pattern=r"^[a-z0-9-]+$")
    public_url: str = Field(
        default="http://127.0.0.1:8787", max_length=300, pattern=r"^https?://[^\s<>\"'`]+$"
    )

    @model_validator(mode="after")
    def validate_telegram(self) -> Settings:
        if self.telegram_mode == "webhook" and len(self.telegram_webhook_secret) < 24:
            raise ValueError("Telegram webhook mode requires a webhook secret of 24+ characters")
        return self

    @model_validator(mode="after")
    def validate_profile(self) -> Settings:
        if self.profile != "P1-native" and self.local_login:
            raise ValueError("Local fixture login is forbidden outside P1-native")
        if self.backend_url and not self.backend_url.startswith("http://127.0.0.1:"):
            raise ValueError("This native dispatcher supports only a fixed loopback backend")
        if self.profile == "P2-cloud" and self.auth_mode != "iap":
            raise ValueError("P2-cloud requires MIRAGE_AUTH_MODE=iap")
        if self.auth_mode == "iap" and (self.local_login or not self.iap_audience):
            raise ValueError("IAP mode requires MIRAGE_IAP_AUDIENCE and disabled local login")
        if self.iap_default_role != "none" and not self.iap_allowed_domain:
            raise ValueError("MIRAGE_IAP_DEFAULT_ROLE requires MIRAGE_IAP_ALLOWED_DOMAIN")
        return self

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / "runtime-secrets.json"
        if path.exists():
            private = json.loads(path.read_text(encoding="utf-8"))
        else:
            private = {
                "backend_secret": secrets.token_urlsafe(48),
                "access_code": secrets.token_urlsafe(18),
            }
            try:
                with path.open("x", encoding="utf-8") as file:
                    json.dump(private, file)
                os.chmod(path, 0o600)
            except FileExistsError:
                private = json.loads(path.read_text(encoding="utf-8"))
        self.backend_secret = self.backend_secret or private["backend_secret"]
        self.access_code = self.access_code or private["access_code"]
        if not self.database_url:
            self.database_url = "sqlite:///" + str((self.data_dir / "mirage.sqlite3").resolve())
        if not self.backend_url:
            self.backend_url = f"http://127.0.0.1:{self.backend_port}"
