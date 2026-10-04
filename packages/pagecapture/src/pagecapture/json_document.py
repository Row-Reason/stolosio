"""Bounded JSON sniffing. Acquisition returns the original bytes unchanged."""

import json

MAX_DEPTH = 128
XSSI_PREFIXES = (")]}'", 'while(1);')


def is_json(media_type: str) -> bool:
    media = media_type.lower().split(';', 1)[0].strip()
    return media in ('application/json', 'text/json') or ('/' in media and media.endswith('+json'))


def json_candidate(body: bytes) -> bool:
    start = body.removeprefix(b'\xef\xbb\xbf').lstrip(b' \t\r\n')
    return start.startswith((b'{', b'[', b")]}'", b'while(1);'))


def _reject_constant(value: str):
    raise ValueError('Non-JSON numeric constant')


def sniff_json(body: bytes) -> bool:
    if not json_candidate(body):
        return False
    try:
        text = body.decode('utf-8-sig').lstrip(' \t\r\n')
        for prefix in XSSI_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix):].lstrip(' \t\r\n')
                break
        if not text.startswith(('{', '[')):
            return False
        depth, quoted, escaped = 0, False, False
        for character in text:
            if quoted:
                if escaped:
                    escaped = False
                elif character == '\\':
                    escaped = True
                elif character == '"':
                    quoted = False
            elif character == '"':
                quoted = True
            elif character in '[{':
                depth += 1
                if depth > MAX_DEPTH:
                    return False
            elif character in ']}':
                depth -= 1
        json.loads(text, parse_int=lambda _: None, parse_float=lambda _: None,
                   parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        return False
    return True
