import re

PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*)(?:Bearer\s+)?[^\s,\"]+"),
    re.compile(r"(?i)((?:api[_-]?key|password|secret|token)\s*[:=]\s*)[^\s,\"]+"),
]


def redact(value):
    if isinstance(value, str):
        for pattern in PATTERNS:
            value = pattern.sub(r"\1[REDACTED]", value)
        return value
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        return {
            k: (
                "[REDACTED]"
                if re.fullmatch(
                    r"(?i)(authorization|api[_-]?key|password|secret|token)", str(k)
                )
                else redact(v)
            )
            for k, v in value.items()
        }
    return value
