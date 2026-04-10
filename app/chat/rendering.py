import re

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

_LATEX_BLOCK = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_LATEX_INLINE = re.compile(r"\$(.+?)\$")


def _protect_latex(text):
    placeholders = {}
    counter = 0

    def _replace_block(m):
        nonlocal counter
        key = f"\x00LATEXBLOCK{counter}\x00"
        placeholders[key] = f'<span class="math-block">$${m.group(1)}$$</span>'
        counter += 1
        return key

    def _replace_inline(m):
        nonlocal counter
        key = f"\x00LATEXINLINE{counter}\x00"
        placeholders[key] = f'<span class="math-inline">${m.group(1)}$</span>'
        counter += 1
        return key

    text = _LATEX_BLOCK.sub(_replace_block, text)
    text = _LATEX_INLINE.sub(_replace_inline, text)
    return text, placeholders


def _restore_latex(html, placeholders):
    for key, value in placeholders.items():
        html = html.replace(escape(key), value)
    return html


def render_assistant_markdown_html(text):
    raw = text or ""
    if markdown_lib is None:
        escaped_text = escape(raw)
        return mark_safe(escaped_text.replace("\n", "<br>"))

    protected, placeholders = _protect_latex(raw)
    escaped_text = escape(protected)
    rendered = markdown_lib.markdown(
        escaped_text,
        extensions=MARKDOWN_EXTENSIONS,
        output_format="html5",
    )
    rendered = _restore_latex(rendered, placeholders)
    return mark_safe(rendered)
