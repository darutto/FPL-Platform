"""
railway_redeploy.py
===================
Trigger a Railway service redeploy via the Railway GraphQL API.

Mutation choice: ``serviceInstanceRedeploy``
--------------------------------------------
Railway's GraphQL schema (as of 2025) exposes ``serviceInstanceRedeploy``
as the canonical mutation for "redeploy this service in this environment right
now." It accepts ``serviceId`` and ``environmentId`` as inputs and returns a
``ServiceInstance`` payload that includes ``latestDeployment { id }`` — from
which we extract the new deployment id.

Alternative candidates considered (per H5b recon):
- ``deploymentRedeploy``: requires a *deployment* id as input (you'd have to
  fetch the current deployment id first — an extra round-trip). Not used.
- ``deploymentTriggerCreate``: creates a new trigger object; does not directly
  fire a redeploy. Not used.

``serviceInstanceRedeploy`` is the one-shot "fire and forget" option that
matches Railway's UI behaviour when you click "Redeploy" on a service.

Public surface (frozen by H5b §4 Decision 5):

    class RailwayRedeployError(Exception): ...

    def redeploy_service(
        service_id: str,
        environment_id: str,
        api_token: str,
        *,
        timeout_s: int = 30,
    ) -> str: ...
"""

from __future__ import annotations

import requests

RAILWAY_GRAPHQL_URL = "https://backboard.railway.app/graphql/v2"

# Mutation: serviceInstanceRedeploy returns Boolean! — no field selection allowed.
# Railway does not echo a deployment id from this mutation; success is just `true`.
_MUTATION = """
mutation ServiceInstanceRedeploy($serviceId: String!, $environmentId: String!) {
  serviceInstanceRedeploy(serviceId: $serviceId, environmentId: $environmentId)
}
"""


class RailwayRedeployError(Exception):
    """Raised on hard failure: HTTP non-2xx, network error, or GraphQL errors[]."""


def redeploy_service(
    service_id: str,
    environment_id: str,
    api_token: str,
    *,
    timeout_s: int = 30,
) -> str:
    """Trigger a Railway redeploy via GraphQL. Returns the new deployment id.

    Posts the ``serviceInstanceRedeploy`` mutation to Railway's GraphQL
    endpoint. Raises :class:`RailwayRedeployError` on:

    - HTTP 4xx / 5xx (status code included in message)
    - Network / connection error (original exception chained)
    - GraphQL ``errors`` array present in a 200 response

    Parameters
    ----------
    service_id:
        Railway service id (UUID string from Railway dashboard or env).
    environment_id:
        Railway environment id (UUID string).
    api_token:
        Railway API token — ``Authorization: Bearer <token>`` header.
    timeout_s:
        HTTP request timeout in seconds (default 30).

    Returns
    -------
    str
        The literal string ``"ok"`` on success. Railway's
        ``serviceInstanceRedeploy`` returns ``Boolean!`` (not a deployment
        object), so no deployment id is available here.
    """
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": _MUTATION,
        "variables": {
            "serviceId": service_id,
            "environmentId": environment_id,
        },
    }

    try:
        response = requests.post(
            RAILWAY_GRAPHQL_URL,
            json=payload,
            headers=headers,
            timeout=timeout_s,
        )
    except requests.exceptions.RequestException as e:
        raise RailwayRedeployError(
            f"Network error contacting Railway GraphQL API: {e}"
        ) from e

    if not response.ok:
        raise RailwayRedeployError(
            f"Railway GraphQL API returned HTTP {response.status_code}: {response.text[:200]}"
        )

    body = response.json()

    if "errors" in body and body["errors"]:
        messages = "; ".join(
            err.get("message", str(err)) for err in body["errors"]
        )
        raise RailwayRedeployError(f"GraphQL errors: {messages}")

    try:
        ok: bool = body["data"]["serviceInstanceRedeploy"]
    except (KeyError, TypeError) as e:
        raise RailwayRedeployError(
            f"Unexpected Railway GraphQL response shape: {body}"
        ) from e

    if ok is not True:
        raise RailwayRedeployError(
            f"Railway returned non-true for serviceInstanceRedeploy: {ok!r}"
        )

    return "ok"


if __name__ == "__main__":
    import os, sys
    required = ["RAILWAY_API_TOKEN", "RAILWAY_SERVICE_ID", "RAILWAY_ENVIRONMENT_ID"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"error: missing required env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    try:
        result = redeploy_service(
            service_id=os.environ["RAILWAY_SERVICE_ID"],
            environment_id=os.environ["RAILWAY_ENVIRONMENT_ID"],
            api_token=os.environ["RAILWAY_API_TOKEN"],
        )
        print(f"redeploy: {result}")
    except RailwayRedeployError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
