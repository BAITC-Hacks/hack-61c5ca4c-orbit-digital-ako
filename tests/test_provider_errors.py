"""Provider error translation uses real SDK errors without making network calls."""

import builtins
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[1] / "money_graph"
sys.path.insert(0, str(PROJECT))

from mg.provider_errors import provider_error_details


SECRET = "sk-test-PRIVATE_API_KEY"
PROMPT = "CONFIDENTIAL_CASE_PROMPT"


@pytest.fixture
def sdk():
    return pytest.importorskip("openai")


@pytest.fixture
def provider_request():
    httpx = pytest.importorskip("httpx")
    return httpx.Request(
        "POST", "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {SECRET}"},
        content=PROMPT.encode("utf-8"),
    )


def status_error(sdk, provider_request, class_name, status, body=None):
    httpx = pytest.importorskip("httpx")
    if body is None:
        body = {"message": f"{SECRET} {PROMPT}", "code": "unknown", "param": PROMPT}
    response = httpx.Response(status, request=provider_request, json=body, headers={"x-request-id": SECRET})
    return getattr(sdk, class_name)(f"Provider message: {SECRET} {PROMPT}", response=response, body=body)


@pytest.mark.parametrize("class_name,status,expected_status,message_part", [
    ("AuthenticationError", 401, 502, "API-ключ"),
    ("PermissionDeniedError", 403, 403, "права проекта"),
    ("RateLimitError", 429, 429, "временный лимит"),
    ("NotFoundError", 404, 404, "название модели"),
    ("BadRequestError", 400, 400, "параметры запроса"),
    ("InternalServerError", 500, 502, "стороне OpenAI"),
    ("InternalServerError", 503, 502, "стороне OpenAI"),
    ("APIStatusError", 599, 502, "стороне OpenAI"),
])
def test_provider_statuses_use_fixed_safe_messages(
    sdk, provider_request, caplog, capsys, class_name, status, expected_status, message_part,
):
    error = status_error(sdk, provider_request, class_name, status)
    error.__cause__ = RuntimeError(f"Underlying cause: {SECRET} {PROMPT}")
    result_status, message = provider_error_details(error)
    assert result_status == expected_status
    assert message_part in message
    assert SECRET not in message and PROMPT not in message
    assert caplog.text == ""
    assert capsys.readouterr() == ("", "")


def test_timeout_and_connection_errors_have_distinct_statuses(sdk, provider_request, caplog, capsys):
    timeout = sdk.APITimeoutError(request=provider_request)
    connection = sdk.APIConnectionError(message=f"{SECRET} {PROMPT}", request=provider_request)
    assert provider_error_details(timeout)[0] == 504
    assert "не ответил вовремя" in provider_error_details(timeout)[1]
    status, message = provider_error_details(connection)
    assert status == 503
    assert "подключиться" in message
    assert SECRET not in message and PROMPT not in message
    assert caplog.text == ""
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("body", [
    {"code": "insufficient_quota", "message": SECRET},
    {"type": "insufficient_quota", "message": PROMPT},
    {"error": {"code": "insufficient_quota", "message": SECRET}},
    {"error": {"type": "insufficient_quota", "message": PROMPT}},
])
def test_quota_is_distinguished_from_retryable_rate_limit(sdk, provider_request, body):
    quota = status_error(sdk, provider_request, "RateLimitError", 429, body)
    transient = status_error(sdk, provider_request, "RateLimitError", 429, {"code": "rate_limit_exceeded"})
    status, quota_message = provider_error_details(quota)
    transient_status, transient_message = provider_error_details(transient)
    assert status == transient_status == 429
    assert "квота" in quota_message and "баланс" in quota_message
    assert "временный" in transient_message
    assert quota_message != transient_message
    assert SECRET not in quota_message and PROMPT not in quota_message


@pytest.mark.parametrize("body", [
    {"message": "insufficient_quota"},
    {"code": "insufficient_quota_extra"},
    {"type": "rate_limit_exceeded", "error": SECRET},
    ["insufficient_quota", SECRET],
])
def test_quota_detection_only_uses_exact_allowlisted_fields(sdk, provider_request, body):
    error = status_error(sdk, provider_request, "RateLimitError", 429, body)
    assert "временный лимит" in provider_error_details(error)[1]


def test_unknown_errors_are_left_to_callers(sdk, provider_request):
    class UnrelatedError(Exception):
        status_code = 401
        code = "insufficient_quota"

    assert provider_error_details(UnrelatedError(SECRET)) is None
    assert provider_error_details(ValueError(PROMPT)) is None
    assert provider_error_details(status_error(sdk, provider_request, "ConflictError", 409)) is None


def test_core_import_and_classification_work_without_optional_sdk(monkeypatch):
    original_import = builtins.__import__

    def no_openai(name, *args, **kwargs):
        if name == "openai" or name.startswith("openai."):
            raise ModuleNotFoundError("Optional SDK unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_openai)
    # Importing the module must itself remain independent of the SDK.
    import importlib
    import mg.provider_errors as module

    module = importlib.reload(module)
    assert module.provider_error_details(RuntimeError(SECRET)) is None
