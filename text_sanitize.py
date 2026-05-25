"""
清理 Safari 地址栏 / 搜索框通过辅助功能读到的多余提示文字。
"""

from __future__ import annotations

import re

# Safari 自动完成提示后缀
_SAFARI_REMOVE_SUGGESTION = re.compile(
    r",?\s*press\s+Tab\s+then\s+Enter\s+to\s+Remove\s+Suggestion\.?\s*",
    re.IGNORECASE,
)

_SAFARI_LOCATION_HISTORY = re.compile(
    r"\s+location\s+from\s+history\b.*$",
    re.IGNORECASE | re.DOTALL,
)

_SIMPLE_URL = re.compile(
    r"([\w][\w.-]*\.(?:com|net|org|io|shop|co|dev|app|cn)(?:/[\w%.?=&/-]*)?)\s*$",
    re.IGNORECASE,
)


def sanitize_typed_text(text: str) -> str:
    """去掉 Safari 建议提示，必要时只保留末尾 URL。"""
    if not text:
        return ""

    cleaned = _SAFARI_REMOVE_SUGGESTION.sub("", text)
    cleaned = _SAFARI_LOCATION_HISTORY.sub("", cleaned)
    cleaned = cleaned.strip()

    match = _SIMPLE_URL.search(cleaned)
    if match and len(cleaned) > len(match.group(1)) + 12:
        tail = match.group(1)
        idx = cleaned.lower().rfind(tail.lower())
        if idx >= 0:
            prefix = cleaned[:idx].strip(" ,-–—|")
            if len(prefix) > 8:
                cleaned = tail

    return cleaned.strip()


def looks_like_url(text: str) -> bool:
    """简单判断是否为网址（适合地址栏逐字输入）。"""
    text = text.strip()
    if not text or " " in text:
        return False
    return bool(
        re.match(
            r"^[\w.-]+\.[\w.-]{2,}(/[\w%.?=&/-]*)?$",
            text,
            re.IGNORECASE,
        )
    )
