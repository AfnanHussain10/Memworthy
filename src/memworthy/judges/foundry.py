"""Microsoft-Decision-1 on Microsoft Foundry: the System One preset for a Foundry deployment.

Contract from https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/
use-foundry-models-microsoft-decision (see the tech spec's judge providers section).
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlsplit

import httpx

from memworthy.judges.base import JudgeError
from memworthy.judges.systemone import SystemOneJudge

log = logging.getLogger("memworthy.judges.foundry")

PROVIDER_PATH = "/providers/microsoft/v1"
MODEL_NAME = "microsoft-decision-1"
# The data-plane deployment listing that accepts the resource API key.
DEPLOYMENTS_PATH = "/openai/deployments?api-version=2022-12-01"


def foundry_base_url(endpoint: str) -> str:
    """The System One API root for a Foundry endpoint.

    Accepts the resource endpoint, the provider root, or the full ``…/systemone`` URL.
    """
    base = endpoint.rstrip("/").removesuffix("/systemone")
    return base if base.endswith(PROVIDER_PATH) else base + PROVIDER_PATH


def discover_deployment(endpoint: str, api_key: str, timeout: float = 10.0,
                        client: httpx.Client | None = None) -> str:
    """Find the one deployment on the resource that runs Microsoft-Decision-1.

    Raises JudgeError if the listing fails or there is not exactly one such deployment.
    """
    parts = urlsplit(endpoint)
    url = f"{parts.scheme}://{parts.netloc}{DEPLOYMENTS_PATH}"
    http = client or httpx.Client(timeout=timeout)
    try:
        resp = http.get(url, headers={"api-key": api_key}, timeout=timeout)
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        raise JudgeError(f"could not list Foundry deployments: {type(exc).__name__}; "
                         "set AZURE_FOUNDRY_DEPLOYMENT") from None
    finally:
        if client is None:
            http.close()
    if resp.status_code in (401, 403):
        raise JudgeError(f"listing Foundry deployments returned HTTP {resp.status_code}; "
                         "check AZURE_FOUNDRY_API_KEY and AZURE_FOUNDRY_ENDPOINT")
    if resp.status_code != 200:
        raise JudgeError(f"listing Foundry deployments returned HTTP {resp.status_code}; "
                         "set AZURE_FOUNDRY_DEPLOYMENT")
    try:
        data: list[dict[str, Any]] = resp.json().get("data") or []
    except (ValueError, AttributeError):
        raise JudgeError("listing Foundry deployments returned invalid JSON; "
                         "set AZURE_FOUNDRY_DEPLOYMENT") from None
    names = [str(d.get("id")) for d in data if isinstance(d, dict)
             and str(d.get("model", "")).lower() == MODEL_NAME
             and d.get("status", "succeeded") == "succeeded"]
    if len(names) != 1:
        found = ", ".join(names) if names else "none"
        raise JudgeError(f"expected one Microsoft-Decision-1 deployment, found {found}; "
                         "set AZURE_FOUNDRY_DEPLOYMENT")
    log.info("using Foundry deployment %r", names[0])
    return names[0]


class FoundryDecisionJudge(SystemOneJudge):
    """Judge backed by a Microsoft-Decision-1 deployment. One POST per candidate.

    The request's ``model`` is the deployment name; when none is given it is discovered from
    the resource once, at construction. The response reports the underlying model.
    Authenticates with the resource's API key (``api-key`` header).
    """

    name = "microsoft"
    label = "Microsoft Foundry"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        deployment: str | None = None,
        timeout: float = 10.0,
        retries: int = 2,
        backoff: float = 0.5,
        client: httpx.AsyncClient | None = None,
        discovery_client: httpx.Client | None = None,
    ) -> None:
        """Configure from arguments, falling back to AZURE_FOUNDRY_* env vars."""
        endpoint = endpoint or os.environ.get("AZURE_FOUNDRY_ENDPOINT") or ""
        api_key = api_key or os.environ.get("AZURE_FOUNDRY_API_KEY") or ""
        missing = [name for name, value in [("AZURE_FOUNDRY_ENDPOINT", endpoint),
                                            ("AZURE_FOUNDRY_API_KEY", api_key)] if not value]
        if missing:
            raise JudgeError(f"{', '.join(missing)} not set; pass them or use MockJudge")
        deployment = (deployment or os.environ.get("AZURE_FOUNDRY_DEPLOYMENT")
                      or discover_deployment(endpoint, api_key, timeout, discovery_client))
        super().__init__(api_key=api_key, base_url=foundry_base_url(endpoint),
                         model=deployment, auth="api-key", timeout=timeout, retries=retries,
                         backoff=backoff, client=client)
