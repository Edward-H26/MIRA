import re

from django.utils.html import escape
from django.utils.safestring import mark_safe

try:
    import markdown as markdown_lib
except Exception:
    markdown_lib = None


MARKDOWN_EXTENSIONS = [
    "extra",
    "sane_lists",
    "nl2br",
]


_LATEX_BLOCK = re.compile(r"\$\$\s*(.+?)\s*\$\$", re.DOTALL)
_LATEX_INLINE = re.compile(
    r"(?<![A-Za-z0-9\\])\$(?!\s)([^\n$]+?)(?<!\s)\$(?![A-Za-z0-9])"
)
_ESCAPED_DOLLAR = re.compile(r"\\\$")


_AGENT_SUFFIX = re.compile(r"'s\s+[Aa]gent$")
_SPLIT_CHARS = re.compile(r"[\s'\-]+")

_MENTION_EXPANDED = re.compile(
    r"(?<!\w)@("
    r"[A-Z][a-zA-Z]*"
    r"(?:'[a-zA-Z]+)?"
    r"(?:\s+[A-Z][a-zA-Z]*(?:'[a-zA-Z]+)?){0,4}"
    r")(?:'s\s+[Aa]gent\b)?"
)

_MENTION_RENDER = re.compile(r"@([A-Za-z][\w]*(?:[\w']*[\w])?)")

_DANGEROUS_URL_SCHEME = re.compile(
    r'(href|src)\s*=\s*(["\'])\s*(?:javascript|data|vbscript|file)\s*:[^"\']*\2',
    re.IGNORECASE,
)

_DANGEROUS_TAGS = re.compile(
    r"<(/?)(\s*)("
    r"script|style|iframe|object|embed|link|meta|base|form|applet|"
    r"svg|math|foreignObject|annotation-xml|image|audio|video|source|track|"
    r"input|button|textarea|select|option|frame|frameset|noframes|marquee"
    r")\b([^>]*)>",
    re.IGNORECASE,
)

_DANGEROUS_EVENT_HANDLERS = re.compile(
    r"\son[a-z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
    re.IGNORECASE,
)


def compact_mention_handle(name):
    if not name:
        return ""
    cleaned = _AGENT_SUFFIX.sub("", name).strip()
    parts = [p for p in _SPLIT_CHARS.split(cleaned) if p]
    result = []
    for part in parts:
        if part[:1].islower():
            part = part[:1].upper() + part[1:]
        result.append(part)
    return "".join(result)


def normalize_mentions(text):
    if not text:
        return text

    def _repl(match):
        handle = compact_mention_handle(match.group(1))
        if not handle:
            return match.group(0)
        return f"@{handle}"

    return _MENTION_EXPANDED.sub(_repl, text)


def _protect_latex(text):
    placeholders = {}
    counter = 0

    def _replace_block(m):
        nonlocal counter
        key = f"\x00LATEXBLOCK{counter}\x00"
        placeholders[key] = f'<span class="math-block">$${escape(m.group(1))}$$</span>'
        counter += 1
        return key

    def _replace_inline(m):
        nonlocal counter
        key = f"\x00LATEXINLINE{counter}\x00"
        placeholders[key] = f'<span class="math-inline">${escape(m.group(1))}$</span>'
        counter += 1
        return key

    text = _LATEX_BLOCK.sub(_replace_block, text)
    text = _LATEX_INLINE.sub(_replace_inline, text)
    return text, placeholders


def _restore_latex(html, placeholders):
    for key, value in placeholders.items():
        html = html.replace(escape(key), value)
    return html


def _unescape_dollars(html):
    return _ESCAPED_DOLLAR.sub("$", html)


def _highlight_mentions(html):
    return _MENTION_RENDER.sub(
        r'<span class="mention-highlight">@\1</span>',
        html,
    )


def _strip_dangerous_urls(html):
    return _DANGEROUS_URL_SCHEME.sub(r'\1=\2#\2', html)


def _escape_dangerous_tags(html):
    html = _DANGEROUS_TAGS.sub(
        lambda m: f"&lt;{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}&gt;",
        html,
    )
    # Strip any ``on*=`` event-handler attributes that slipped through on
    # otherwise-safe tags (``<p onclick="...">`` → ``<p>``).
    html = _DANGEROUS_EVENT_HANDLERS.sub("", html)
    return html


def render_assistant_markdown_html(text):
    raw = text or ""
    if markdown_lib is None:
        escaped_text = escape(raw)
        return mark_safe(escaped_text.replace("\n", "<br>"))

    normalized = normalize_mentions(raw)
    protected, placeholders = _protect_latex(normalized)
    rendered = markdown_lib.markdown(
        protected,
        extensions=MARKDOWN_EXTENSIONS,
        output_format="html5",
    )
    rendered = _restore_latex(rendered, placeholders)
    rendered = _unescape_dollars(rendered)
    rendered = _highlight_mentions(rendered)
    rendered = _strip_dangerous_urls(rendered)
    rendered = _escape_dangerous_tags(rendered)
    return mark_safe(rendered)
