"""Configuration-gated adapter for the deployed ranking Lambda."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from lambda_backend.ranking import rank_borrowers as rank_locally


class RankingGatewayError(RuntimeError):
    """Raised when the remote ranking service cannot return a valid result."""


def configured() -> bool:
    return bool(os.getenv("RANKING_LAMBDA_URL", "").strip())


def _validate_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise RankingGatewayError("Ranking service returned a non-object response.")
    if not isinstance(result.get("ranked"), list):
        raise RankingGatewayError("Ranking response is missing ranked[].")
    if not isinstance(result.get("excluded"), list):
        raise RankingGatewayError("Ranking response is missing excluded[].")
    if not isinstance(result.get("summary"), dict):
        raise RankingGatewayError("Ranking response is missing summary.")
    return result


def _unwrap_lambda_response(payload: Any) -> dict[str, Any]:
    """Accept a direct result or the handler's HTTP proxy response envelope."""
    if isinstance(payload, dict) and "statusCode" in payload:
        status = payload.get("statusCode")
        body = payload.get("body")
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError as exc:
                raise RankingGatewayError("Lambda proxy body is not valid JSON.") from exc
        if not isinstance(status, int):
            raise RankingGatewayError("Lambda proxy response has an invalid statusCode.")
        if status >= 400:
            detail = body.get("error") if isinstance(body, dict) else body
            raise RankingGatewayError(f"Ranking Lambda rejected the request: {detail}")
        payload = body
    return _validate_result(payload)


def rank_borrowers(borrowers: list[dict[str, Any]]) -> dict[str, Any]:
    """Use Lambda only when configured; otherwise use the identical local engine."""
    mode = os.getenv("RANKING_MODE", "local").strip().lower()
    if mode not in {"local", "lambda"}:
        raise RankingGatewayError("RANKING_MODE must be local or lambda.")
    url = os.getenv("RANKING_LAMBDA_URL", "").strip() if mode == "lambda" else ""
    if mode == "lambda" and not url:
        raise RankingGatewayError("RANKING_LAMBDA_URL is required in lambda mode.")
    if not url:
        result = rank_locally(borrowers)
        return {**result, "ranking_source": "local"}

    timeout = float(os.getenv("RANKING_LAMBDA_TIMEOUT_SECONDS", "10"))
    try:
        response = httpx.post(
            url,
            json={"action": "rank", "borrowers": borrowers},
            timeout=timeout,
        )
        response.raise_for_status()
        result = _unwrap_lambda_response(response.json())
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        raise RankingGatewayError(f"Ranking Lambda request failed: {exc}") from exc
    return {**result, "ranking_source": "lambda"}
