"""认证 Provider 集合：CAS 基类与三个服务子类。"""

from __future__ import annotations

from westlake_survival.sso.providers.canvas import CanvasAuth
from westlake_survival.sso.providers.cas import CAS_LOGIN, CASAuthorizer
from westlake_survival.sso.providers.lib import (
    OPAC_BASE,
    OPAC_SERVICE_URL,
    OPAC_SERVICE_URL_PUBLIC,
    LibAuth,
)
from westlake_survival.sso.providers.sis import SIS_BASE, SIS_LOGIN_URL, SISAuth

__all__ = [
    "CASAuthorizer",
    "CAS_LOGIN",
    "SISAuth",
    "SIS_BASE",
    "SIS_LOGIN_URL",
    "LibAuth",
    "OPAC_BASE",
    "OPAC_SERVICE_URL",
    "OPAC_SERVICE_URL_PUBLIC",
    "CanvasAuth",
]