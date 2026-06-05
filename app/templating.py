import logging
import string
from dataclasses import dataclass

_formatter = string.Formatter()
_logger = logging.getLogger(__name__)


@dataclass
class RenderResult:
    text: str
    missing: list[str]


def extract_variables(template: str) -> list[str]:
    names: list[str] = []
    for _literal, field_name, _spec, _conv in _formatter.parse(template):
        if not field_name:
            continue
        base = field_name.split(".")[0].split("[")[0]
        if base and base not in names:
            names.append(base)
    return names


def render(template: str, param: dict) -> RenderResult:
    required = extract_variables(template)
    missing = [name for name in required if name not in param]
    if missing:
        return RenderResult(text="", missing=missing)
    extra = [key for key in param if key not in required]
    if extra:
        _logger.warning("render: ignoring extra param keys: %s", extra)
    try:
        text = template.format_map(param)
    except (KeyError, IndexError, AttributeError) as exc:
        _logger.warning("render: failed to format template: %s", exc)
        return RenderResult(text="", missing=[str(exc)])
    return RenderResult(text=text, missing=[])
