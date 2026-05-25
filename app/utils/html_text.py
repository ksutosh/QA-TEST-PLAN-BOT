from html.parser import HTMLParser


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self._parts.append(text)

    def get_text(self) -> str:
        return "\n".join(self._parts).strip()


def html_storage_to_plain_text(html: str) -> str:
    """Convert Confluence storage HTML to plain text for the LLM prompt."""
    if not html or not html.strip():
        return ""
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return parser.get_text()
