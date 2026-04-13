import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "memoria.settings.dev")

import django
django.setup()

from app.chat.rendering import (
    compact_mention_handle,
    normalize_mentions,
    render_assistant_markdown_html,
)


class CompactMentionHandleTests(unittest.TestCase):
    def test_compact_preserves_already_compact(self):
        self.assertEqual(compact_mention_handle("KatherineOsei"), "KatherineOsei")

    def test_compact_joins_space_separated(self):
        self.assertEqual(compact_mention_handle("Katherine Osei"), "KatherineOsei")

    def test_compact_strips_apostrophe_suffix(self):
        self.assertEqual(compact_mention_handle("Katherine Osei's Agent"), "KatherineOsei")

    def test_compact_strips_apostrophe_suffix_lowercase(self):
        self.assertEqual(compact_mention_handle("Rachel Foster's agent"), "RachelFoster")

    def test_compact_handles_apostrophe_in_name(self):
        self.assertEqual(compact_mention_handle("James O'Brien"), "JamesOBrien")

    def test_compact_empty_returns_empty(self):
        self.assertEqual(compact_mention_handle(""), "")
        self.assertEqual(compact_mention_handle(None), "")


class NormalizeMentionsTests(unittest.TestCase):
    def test_normalize_expanded_mention_with_suffix(self):
        text = "@Katherine Osei's Agent, please review."
        self.assertEqual(normalize_mentions(text), "@KatherineOsei, please review.")

    def test_normalize_expanded_mention_without_suffix(self):
        text = "Ping @Katherine Osei for input."
        self.assertEqual(normalize_mentions(text), "Ping @KatherineOsei for input.")

    def test_normalize_leaves_compact_mention_alone(self):
        text = "Ping @KatherineOsei for input."
        self.assertEqual(normalize_mentions(text), "Ping @KatherineOsei for input.")

    def test_normalize_multiple_mentions(self):
        text = "Notify @Rachel Foster and @RobertChen about the update."
        self.assertEqual(
            normalize_mentions(text),
            "Notify @RachelFoster and @RobertChen about the update.",
        )

    def test_normalize_email_is_untouched(self):
        text = "Reach me at alice@KatherineOsei.com"
        self.assertEqual(normalize_mentions(text), text)

    def test_normalize_empty_string(self):
        self.assertEqual(normalize_mentions(""), "")


class RenderAssistantMarkdownHtmlTests(unittest.TestCase):
    def test_mention_gets_highlighted_span(self):
        html = str(render_assistant_markdown_html("Hi @KatherineOsei"))
        self.assertIn('class="mention-highlight"', html)
        self.assertIn("@KatherineOsei", html)

    def test_expanded_mention_normalizes_to_pill(self):
        html = str(render_assistant_markdown_html("Hi @Katherine Osei's Agent"))
        self.assertIn('class="mention-highlight"', html)
        self.assertIn("@KatherineOsei", html)
        self.assertNotIn("Osei's Agent</strong>", html)

    def test_inline_latex_currency_is_not_math(self):
        html = str(render_assistant_markdown_html("Total cost is $5,000 for the project."))
        self.assertNotIn('class="math-inline"', html)
        self.assertIn("$5,000", html)

    def test_inline_latex_math_wraps_in_math_span(self):
        html = str(render_assistant_markdown_html("Area is $r^2 + y^2$ units."))
        self.assertIn('class="math-inline"', html)

    def test_block_latex_wraps_in_math_block(self):
        html = str(render_assistant_markdown_html("$$\\int_0^1 x\\,dx$$"))
        self.assertIn('class="math-block"', html)

    def test_mixed_currency_and_prose_preserves_whitespace(self):
        text = (
            "Based on the $50,000 contract value, disqualification could result "
            "in a lost credit of approximately $3,250 - $5,000 (assuming a 6.5%-10% rate)."
        )
        html = str(render_assistant_markdown_html(text))
        self.assertNotIn('class="math-inline"', html)
        self.assertIn("contract value", html)
        self.assertIn("$3,250", html)
        self.assertIn("$5,000", html)

    def test_escaped_dollar_renders_as_literal_dollar(self):
        html = str(render_assistant_markdown_html("Price is \\$5,000 per unit."))
        self.assertIn("$5,000", html)
        self.assertNotIn("\\$", html)


if __name__ == "__main__":
    unittest.main()
