import json

def approx_tokens(data: dict | list | str) -> int:
    """Conservatively estimate LLM tokens for JSON or strings.
    JSON and punctuation-heavy text typically compresses to 1 token per 2.5 characters.
    """
    if isinstance(data, str):
        return int(len(data) // 1.5)
    return int(len(json.dumps(data)) // 1.5)
