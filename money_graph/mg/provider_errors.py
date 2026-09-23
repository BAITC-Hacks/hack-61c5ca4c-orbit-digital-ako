"""Fixed, safe UI messages for the optional OpenAI provider.

Never stringify or log an exception here: provider messages, request headers,
response bodies and chained exceptions may contain confidential case data.
"""

from __future__ import annotations


def _insufficient_quota(exc: Exception) -> bool:
    """Inspect only allowlisted error-code fields; never expose their contents."""
    markers = [getattr(exc, "code", None), getattr(exc, "type", None)]
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        markers.extend((body.get("code"), body.get("type")))
        error = body.get("error")
        if isinstance(error, dict):
            markers.extend((error.get("code"), error.get("type")))
    return any(isinstance(marker, str) and marker == "insufficient_quota" for marker in markers)


def provider_error_details(exc: Exception) -> tuple[int, str] | None:
    """Return a safe HTTP status/message, or None for an unrelated exception.

    The import stays local so graph analysis and local assistant actions work
    when the optional OpenAI SDK has not been installed.
    """
    try:
        from openai import APIConnectionError, APIStatusError, APITimeoutError
    except ImportError:
        return None

    # APITimeoutError subclasses APIConnectionError, so order matters.
    if isinstance(exc, APITimeoutError):
        return 504, "OpenAI не ответил вовремя. Повторите запрос позже; локальные действия доступны."
    if isinstance(exc, APIConnectionError):
        return 503, "Не удалось подключиться к OpenAI. Проверьте интернет-соединение сервера и доступ к API."
    if not isinstance(exc, APIStatusError):
        return None

    status = exc.status_code
    if status == 401:
        # Upstream credentials failed; the user's local login is still valid.
        return 502, "OpenAI не принял API-ключ. Проверьте ключ в настройках сервера."
    if status == 403:
        return 403, "OpenAI запретил доступ. Проверьте права проекта и доступ к выбранной модели."
    if status == 429:
        if _insufficient_quota(exc):
            return 429, "Исчерпана квота OpenAI API. Проверьте баланс и лимит расходов проекта."
        return 429, "Достигнут временный лимит запросов OpenAI. Подождите и повторите запрос."
    if status == 404:
        return 404, "Выбранная модель или ресурс OpenAI недоступны. Проверьте название модели и доступ проекта."
    if status == 400:
        return 400, "OpenAI отклонил параметры запроса. Проверьте выбранную модель и настройки ИИ на сервере."
    if 500 <= status < 600:
        return 502, "На стороне OpenAI произошла ошибка. Повторите запрос позже; локальные действия доступны."
    return None
