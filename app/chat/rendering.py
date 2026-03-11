from django.utils.html import escape
from django.utils.safestring import mark_safe

try:
    import markdown as markdown_lib
except Exception:  # pragma: no cover
    markdown_lib = None


MARKDOWN_EXTENSIONS = [
    "extra",
    "sane_lists",
    "nl2br",
]


def render_assistant_markdown_html(text):
    escaped_text = escape(text or "")
    if markdown_lib is None:
        return mark_safe(escaped_text.replace("\n", "<br>"))
    rendered = markdown_lib.markdown(
        escaped_text,
        extensions=MARKDOWN_EXTENSIONS,
        output_format="html5",
    )
    return mark_safe(rendered)
