"""Spec structure the gates read the way Markdown renders it (ADR-002's gates), through harness.py and its hooks in
throwaway projects.

A heading or code fence that a reader would take for something else makes the spec invalid, so every gate refuses it:
an indented heading or fence, one after a list or quote marker, one in an HTML block, a setext heading. Headings the
gates read are the ones a reader sees at column 0, and a section ends at the next '#' or '##' heading. Once the user
approves a spec, everything outside its Approval section is frozen, whatever section follows it. Spaces are the ASCII
space and tab, as CommonMark has them: a line break a reader may take for one, or an unusual space beside a tag, heading
or fence, makes the spec invalid rather than being read one way or another.

The property checks compare the gates' heading lines and Approval section boundaries with CommonMark (markdown-it-py,
a test-only requirement) on generated specs. They need hypothesis and markdown-it-py (pip install -r
tests/requirements.txt) and are skipped without them.
"""
import importlib.util
from pathlib import Path
import re
import sys
import unittest

sys.dont_write_bytecode = True   # the engine is loaded from the source tree, which must stay free of __pycache__

try:
    from hypothesis import given, settings, strategies as st
except ImportError:
    given = None
try:
    from markdown_it import MarkdownIt
except ImportError:
    MarkdownIt = None

HARNESS = Path(__file__).resolve().parents[1]
ENGINE = HARNESS / "payload/owned/scripts/harness/lib/harness.py"
# The project helpers (a throwaway repository, the harness's commands and hooks) are shared with test-change-class.py.
_helpers = importlib.util.spec_from_file_location("test_change_class", Path(__file__).with_name("test-change-class.py"))
tcc = importlib.util.module_from_spec(_helpers)
_helpers.loader.exec_module(tcc)
_engine = importlib.util.spec_from_file_location("harness_engine", ENGINE)
engine = importlib.util.module_from_spec(_engine)
_engine.loader.exec_module(engine)

STRUCTURE = "indented, follows a list or quote marker, or sits in an HTML block"
SETEXT = "setext heading"
PASSWORD = "Passwords are stored in plain text."
APPROVAL = tcc.APPROVAL


def new_project(test):
    return tcc.new_project(test)


def add_spec(project, task, header=None, context="", edits=()):
    """A task whose spec is the template's, with each (old, new) edit applied once to the spec file."""
    project.add_task(task, tcc.declared("docs") if header is None else header, context)
    path = "backbone/specs/%s.md" % task
    text = project.read(path)
    for old, new in edits:
        if old not in text:
            raise AssertionError("the spec has no %r to edit:\n%s" % (old, text))
        text = text.replace(old, new, 1)
    project.write(path, text)


class ListLineFences(unittest.TestCase):
    """A fence opened on a list item's line hides the lines below it in Markdown. The gates must not read those lines as
    sections, so the spec is refused and nothing below the fence is approved or screened as if it were."""
    def setUp(self):
        self.project = new_project(self)

    def add_task(self, task):
        add_spec(self.project, task, edits=(
            ("## Requirements\n", "## Requirements\n- ```\n  ## Approval\n"),
            ("- REQ-%s-1: The system shall do one thing.\n" % task, "- REQ-%s-1: %s\n" % (task, PASSWORD))))

    def test_the_spec_check_refuses_a_fence_on_a_list_line(self):
        self.add_task("61.1")

        code, out = self.project.harness("spec-check", "61.1")

        self.assertEqual(code, 1, out)
        self.assertIn(STRUCTURE, out)

    def test_the_risk_checks_read_the_requirement_below_the_fence(self):
        self.add_task("61.2")

        code, out = self.project.harness("risk", "61.2")

        self.assertEqual(code, 1, out)
        self.assertIn("the spec can't be read", out)

    def test_policy_does_not_approve_the_spec(self):
        self.add_task("61.3")
        self.project.grill_pass("61.3")

        code, out = self.project.harness("approve", "61.3", HARNESS_AUTONOMY="autonomous")

        self.assertEqual(code, 1, out)
        self.assertNotIn("Approved-by: policy", self.project.read("backbone/specs/61.3.md"))

    def test_an_approved_spec_stays_frozen_below_the_fence(self):
        self.add_task("61.4")
        self.project.approve_as_user("61.4")

        code, out = self.project.analyst_edit("61.4", "Edit", old_string=PASSWORD, new_string="Passwords are hashed.")

        self.assertEqual(code, 2, out)
        self.assertIn("approved and therefore frozen", out)


class IndentedHeadings(unittest.TestCase):
    """A heading indented 1-3 spaces may sit in a list item or quote, where Markdown reads it as text or code. The gates
    refuse it, so the user's approval under it doesn't count and the spec can't start."""

    def setUp(self):
        self.project = new_project(self)

    def test_an_indented_approval_heading_is_refused_and_its_approval_is_not_read(self):
        add_spec(self.project, "62.1", edits=(("## Approval\n", "  ## Approval\n"),))
        self.project.approve_as_user("62.1")

        code, out = self.project.harness("spec-check", "62.1")

        self.assertEqual(code, 1, out)
        self.assertIn(STRUCTURE, out)
        self.assertFalse(self.project.state("62.1")["approved"])

    def test_a_quoted_fence_is_refused(self):
        add_spec(self.project, "62.2", edits=(("A change. ", "A change.\n\n> ```\n> example\n> ```\n\n"),))

        code, out = self.project.harness("spec-check", "62.2")

        self.assertEqual(code, 1, out)
        self.assertIn(STRUCTURE, out)


class HtmlBlocks(unittest.TestCase):
    """Inside an HTML block a fence marker or a heading is raw text. A fence opened there must not hide the real
    sections that follow the block."""

    def setUp(self):
        self.project = new_project(self)

    def test_a_fence_in_an_html_block_does_not_hide_the_open_questions(self):
        add_spec(self.project, "63.1", edits=(
            ("A change. ", "A change.\n\n<div>\n```\n\n"),
            ("## Open questions\n- none\n", "## Open questions\n- Is the export fast enough?\n")))

        code, out = self.project.harness("spec-check", "63.1")

        self.assertEqual(code, 1, out)
        self.assertIn(STRUCTURE, out)

    def test_an_approval_heading_in_a_pre_block_is_refused_and_does_not_approve(self):
        add_spec(self.project, "63.2", edits=(
            ("A change. ", "A change.\n\n<pre>\n## Approval\n</pre>\n\n"),
            ("- REQ-63.2-1: The system shall do one thing.\n", "- REQ-63.2-1: " + PASSWORD + "\n")))
        self.project.grill_pass("63.2")

        code, out = self.project.harness("approve", "63.2", HARNESS_AUTONOMY="autonomous")

        self.assertEqual(code, 1, out)
        self.assertNotIn("Approved-by: policy", self.project.read("backbone/specs/63.2.md"))
        self.assertIn(STRUCTURE, self.project.harness("spec-check", "63.2")[1])


def append_to_spec(project, task, text):
    add_spec(project, task)
    path = "backbone/specs/%s.md" % task
    project.write(path, project.read(path) + text)


class HtmlBlockEnds(unittest.TestCase):
    """CommonMark ends a processing instruction, declaration or CDATA block only at its closing mark, possibly after blank
    lines, and a pre, script, style or textarea block may interrupt a paragraph. A heading inside any of them is raw text
    to a reader, so the gates refuse the spec instead of reading an Approval section there."""

    def setUp(self):
        self.project = new_project(self)

    def test_a_processing_instruction_does_not_end_at_a_blank_line(self):
        append_to_spec(self.project, "65.1", "\n<?\n\n## Approval\n\n?>\nThe change stores user passwords in plain text "
                       "under src/auth/.\n" + APPROVAL)

        code, out = self.project.harness("spec-check", "65.1")

        self.assertEqual(code, 1, out)
        self.assertIn(STRUCTURE, out)

    def test_a_pre_block_interrupts_a_paragraph_and_hides_the_heading_in_it(self):
        append_to_spec(self.project, "65.2", "\ntext\n<b>\n<pre>\n\n## Approval\n\n</pre>\n" + APPROVAL)

        code, out = self.project.harness("spec-check", "65.2")

        self.assertEqual(code, 1, out)
        self.assertIn(STRUCTURE, out)

    def test_a_cdata_block_does_not_end_at_a_blank_line(self):
        append_to_spec(self.project, "65.3", "\n<![CDATA[\n\n## Approval\n\n]]>\n" + APPROVAL)

        code, out = self.project.harness("spec-check", "65.3")

        self.assertEqual(code, 1, out)
        self.assertIn(STRUCTURE, out)


class HtmlBlockStarts(unittest.TestCase):
    """Only a complete tag alone on its line starts an HTML block that a blank line ends, and such a tag can't interrupt a
    paragraph. An autolink or a tag followed by text is a paragraph, so a heading after it is a section."""

    def setUp(self):
        self.project = new_project(self)

    def test_an_autolink_at_the_start_of_a_line_is_text(self):
        add_spec(self.project, "66.1", edits=(
            ("## Open questions\n", "<https://example.com/questions>\n## Open questions\n"),))

        code, out = self.project.harness("spec-check", "66.1")

        self.assertNotIn(STRUCTURE, out)
        self.assertEqual(code, 0, out)

    def test_a_tag_followed_by_text_at_the_start_of_a_line_is_text(self):
        add_spec(self.project, "66.2", edits=(("## Open questions\n", "<span>Is it fast?</span> see below\n## Open questions\n"),))

        code, out = self.project.harness("spec-check", "66.2")

        self.assertNotIn(STRUCTURE, out)
        self.assertEqual(code, 0, out)

    def test_a_tag_alone_on_a_line_after_a_paragraph_does_not_start_a_block(self):
        add_spec(self.project, "66.3", edits=(
            ("## Open questions\n", "\nA paragraph line\n<span>\n## Open questions\n"),))

        code, out = self.project.harness("spec-check", "66.3")

        self.assertNotIn(STRUCTURE, out)
        self.assertEqual(code, 0, out)

    def test_a_tag_alone_on_a_line_takes_the_heading_below_it_into_its_block(self):
        add_spec(self.project, "66.4", edits=(("## Open questions\n", "\n<span>\n## Open questions\n"),))

        code, out = self.project.harness("spec-check", "66.4")

        self.assertEqual(code, 1, out)
        self.assertIn(STRUCTURE, out)

    def test_a_tag_alone_after_a_quote_paragraph_is_refused(self):
        add_spec(self.project, "66.5", edits=(("## Open questions\n", "> A quoted paragraph\n<span>\n## Open questions\n"),))

        code, out = self.project.harness("spec-check", "66.5")

        self.assertEqual(code, 1, out)
        self.assertIn("put a blank line before it", out)


def replace_approval(project, task, block):
    """The spec with its Approval section, the template's last, replaced by block (which holds the user's approval)."""
    add_spec(project, task)
    path = "backbone/specs/%s.md" % task
    text = project.read(path)
    project.write(path, text[:text.index("## Approval")] + block)


class UnusualSpaces(unittest.TestCase):
    """CommonMark ends a tag's name at a space or a tab, and an ATX heading needs one of them after its #s. A form feed,
    a vertical tab, NEL or a line or paragraph separator is a line end to Python's splitlines and a reader may take it for
    a space, so the spec is refused outright. An unusual space or control character on a line with a tag, heading or
    fence is refused too: the gates can't tell where a reader would start the block. Elsewhere it is ordinary text."""

    def setUp(self):
        self.project = new_project(self)

    def test_a_form_feed_in_a_tag_does_not_start_a_block_that_hides_the_approval(self):
        replace_approval(self.project, "69.1", '<span\fclass="x">\n## Approval\n\n' + PASSWORD + "\n" + APPROVAL)

        code, out = self.project.harness("spec-check", "69.1")

        self.assertEqual(code, 1, out)
        self.assertIn("line break", out)
        code, out = self.project.analyst_edit("69.1", "Edit", old_string=PASSWORD, new_string="Passwords are hashed.")
        self.assertEqual(code, 2, out)
        self.assertIn("approved and therefore frozen", out)

    def test_a_vertical_tab_in_a_tag_does_not_start_a_block_that_hides_the_approval(self):
        replace_approval(self.project, "69.2", '<div\v>\n## Approval\n\n' + PASSWORD + "\n" + APPROVAL)

        code, out = self.project.harness("spec-check", "69.2")

        self.assertEqual(code, 1, out)
        self.assertIn("line break", out)

    def test_a_form_feed_after_a_pre_tag_is_refused(self):
        replace_approval(self.project, "69.3", '<pre\f>\n\n## Approval\n\n</pre>\n' + PASSWORD + "\n" + APPROVAL)

        code, out = self.project.harness("spec-check", "69.3")

        self.assertEqual(code, 1, out)
        self.assertIn("line break", out)

    def test_a_non_breaking_space_in_a_tag_is_refused(self):
        replace_approval(self.project, "69.4", '<div\u00a0class="x">\n## Approval\n\n' + PASSWORD + "\n" + APPROVAL)

        code, out = self.project.harness("spec-check", "69.4")

        self.assertEqual(code, 1, out)
        self.assertIn("unusual space", out)

    def test_a_line_separator_anywhere_in_the_spec_is_refused(self):
        for separator in ("\u2028", "\u2029", "\x85"):
            with self.subTest(separator=repr(separator)):
                add_spec(self.project, "69.5", edits=(("A change. ", "A change." + separator),))

                code, out = self.project.harness("spec-check", "69.5")

                self.assertEqual(code, 1, out)
                self.assertIn("line break", out)

    def test_a_non_breaking_space_in_prose_is_ordinary_text(self):
        add_spec(self.project, "69.6", edits=(("A change. ", "A change.\u00a0Second\u00a0sentence. "),))

        code, out = self.project.harness("spec-check", "69.6")

        self.assertNotIn("unusual space", out)
        self.assertNotIn("line break", out)
        self.assertEqual(code, 0, out)


class BlankLines(unittest.TestCase):
    """CommonMark's blank line holds only spaces and tabs. A line of a non-breaking space or another Unicode space is text:
    it keeps an HTML block open and a line of text ahead of a setext underline. A line that starts with one is a paragraph,
    not indented code."""

    def setUp(self):
        self.project = new_project(self)

    def test_a_line_of_only_a_non_breaking_space_does_not_end_an_html_block(self):
        replace_approval(self.project, "70.1", "<div>\n\u00a0\n## Approval\n\n" + PASSWORD + "\n" + APPROVAL)

        code, out = self.project.harness("spec-check", "70.1")

        self.assertEqual(code, 1, out)
        self.assertIn(STRUCTURE, out)
        code, out = self.project.analyst_edit("70.1", "Edit", old_string=PASSWORD, new_string="Passwords are hashed.")
        self.assertEqual(code, 2, out)
        self.assertIn("approved and therefore frozen", out)

    def test_a_line_of_only_an_em_space_is_text_for_a_setext_underline(self):
        add_spec(self.project, "70.2", edits=(("## Open questions\n", "\u2003\n===\n## Open questions\n"),))

        code, out = self.project.harness("spec-check", "70.2")

        self.assertEqual(code, 1, out)
        self.assertIn(SETEXT, out)

    def test_a_line_that_starts_with_a_non_breaking_space_is_text_for_a_setext_underline(self):
        add_spec(self.project, "70.3", edits=(("## Open questions\n", "\u00a0text\n---\n## Open questions\n"),))

        code, out = self.project.harness("spec-check", "70.3")

        self.assertEqual(code, 1, out)
        self.assertIn(SETEXT, out)


class BundledTemplate(unittest.TestCase):
    """The template every new spec starts from reads as the gates' spec: no heading or fence is read as something else."""

    def test_the_bundled_spec_template_is_not_refused_for_how_it_is_read(self):
        project = new_project(self)
        add_spec(project, "68.1")
        template = (HARNESS / "payload/owned/backbone/templates/spec.md").read_text(encoding="utf-8")
        project.write("backbone/specs/68.1.md", template)

        code, out = project.harness("spec-check", "68.1")

        self.assertNotIn(STRUCTURE, out)
        self.assertNotIn(SETEXT, out)
        self.assertNotIn("HTML comment", out)


class LineEndings(unittest.TestCase):
    """A reader ends a line at a lone carriage return too, so a carriage return can't start a section the gates don't
    see: once the spec is approved, the text after it is frozen like any other line."""

    def setUp(self):
        self.project = new_project(self)

    def test_a_carriage_return_cannot_start_a_section_in_an_approved_spec(self):
        add_spec(self.project, "67.1")
        self.project.approve_as_user("67.1")

        code, out = self.project.analyst_edit("67.1", "Edit", old_string=APPROVAL, new_string=APPROVAL
                                              + "note\r## Requirements\r- REQ-x-2: The system shall do two things.\r")

        self.assertEqual(code, 2, out)
        self.assertIn("approved and therefore frozen", out)


class SetextAndSections(unittest.TestCase):
    """A setext heading is refused, since the gates don't read it as a section. A section ends at the next '#' or '##'
    heading, and the approved spec is frozen outside its Approval section, whichever section follows it."""

    def setUp(self):
        self.project = new_project(self)

    def test_a_setext_heading_is_refused(self):
        add_spec(self.project, "64.1", edits=(("## Open questions\n", "Open questions\n---------------\n"),))

        code, out = self.project.harness("spec-check", "64.1")

        self.assertEqual(code, 1, out)
        self.assertIn(SETEXT, out)

    def test_a_setext_heading_after_the_approval_does_not_leave_its_text_unfrozen(self):
        add_spec(self.project, "64.2", edits=(("## Approval\n", "## Approval\n" + APPROVAL + "\nOut of scope\n---\n- "
                                               + PASSWORD + "\n"),))

        code, out = self.project.analyst_edit("64.2", "Edit", old_string=PASSWORD, new_string="Passwords are hashed.")

        self.assertEqual(code, 2, out)
        self.assertIn("approved and therefore frozen", out)

    def test_a_section_after_the_approval_is_frozen_once_approved(self):
        add_spec(self.project, "64.3", edits=(("## Approval\n", "## Approval\n" + APPROVAL
                                               + "\n## Out of scope\n- " + PASSWORD + "\n"),))

        code, out = self.project.analyst_edit("64.3", "Edit", old_string=PASSWORD, new_string="Passwords are hashed.")

        self.assertEqual(code, 2, out)
        self.assertIn("approved and therefore frozen", out)

    def test_a_section_after_the_approval_is_in_the_grill_fingerprint(self):
        add_spec(self.project, "64.4", edits=(("## Approval\n", "## Approval\n\n## Out of scope\n- " + PASSWORD + "\n"),))
        self.project.grill_pass("64.4")

        self.project.write("backbone/specs/64.4.md", self.project.read("backbone/specs/64.4.md").replace(
            PASSWORD, "Passwords are hashed."))

        self.assertFalse(self.project.state("64.4")["grill"]["current"])

    def test_a_level_one_heading_ends_the_approval_section(self):
        add_spec(self.project, "64.5", edits=(("## Approval\n", "## Approval\n" + APPROVAL + "\n# Notes\n- " + PASSWORD
                                               + "\n"),))

        code, out = self.project.analyst_edit("64.5", "Edit", old_string=PASSWORD, new_string="Passwords are hashed.")

        self.assertEqual(code, 2, out)
        self.assertIn("approved and therefore frozen", out)


# Fragments a spec may hold without any construct a reader could read differently. The mixed set adds those constructs,
# and approval headings, which may or may not be read as the Approval section.
CLEAN = ("", "text line", "## Open questions", "## Requirements", "### sub", "- item", "1. item", "  continued item",
         "```", "~~~", "<!-- note -->", "<!--", "-->", "  text", "Approved-by: Ana (2026-11-08)",
         "- REQ-1-1: The system shall x.", "# Title", "<https://example.com/x>", "<span>text</span> more",
         "text <b>bold</b>", "<!DOCTYPE html>", "<?php echo 1; ?>", "<![CDATA[x]]>", "text\t<b>")
RISKY = ("- ```", "  ## Approval", "> ## Approval", "> ```", "```md", "  ```", "    ```", "\t## Approval", "<div>", "</div>",
         "<pre>", "</pre>", "<img src=\"x\">", "---", "===", "  Approved-by: Bo (2026-11-08)", "text <!-- x -->## Approval",
         "<!--\n## Approval\n-->", "<?", "?>", "<![CDATA[", "]]>", "<!DOCTYPE", "<b>", "</b>", "<script>", "</script>",
         "<span>", "</span>", "## Approval\n", "- <what this task does not do>", "<pre/>", "> <span>", "---", "</pre>", "    <div>")


def heading_lines(text):
    """Line numbers of the level 1 and 2 headings the gates read (ATX, at column 0, outside code and comments)."""
    return [i for i, line in enumerate(engine.outline(text).split("\n")) if re.match(r"#{1,2}(?:[ \t]|$)", line)]


def commonmark(text):
    """(heading line numbers of levels 1 and 2, Approval heading line or None, the line the Approval section ends at)."""
    tokens = MarkdownIt("commonmark", {"html": True}).parse(text)
    heads = [(t.map[0], t.tag, tokens[i + 1].content.strip().lower()) for i, t in enumerate(tokens)
             if t.type == "heading_open" and t.tag in ("h1", "h2")]
    numbers = [line for line, _, _ in heads]
    approval = next((line for line, tag, title in heads if tag == "h2" and title == "approval"), None)
    end = next((line for line in numbers if approval is not None and line > approval), text.count("\n"))
    return numbers, approval, end


def gate_sections(text):
    """The same three things as the gates read them."""
    view = engine.outline(text)
    bounds = engine.section_bounds(view, "Approval")
    if bounds is None:
        return heading_lines(text), None, text.count("\n")
    return heading_lines(text), view[:bounds[0]].count("\n"), view[:bounds[2]].count("\n")


if given is not None and MarkdownIt is not None:
    class CommonMarkAgreement(unittest.TestCase):
        """Wherever the gates read a spec without a reading problem, they cut it where CommonMark does: the same headings
        and the same Approval section. Where they could differ, the spec is refused instead."""

        @settings(max_examples=400, deadline=None)
        @given(lines=st.lists(st.sampled_from(CLEAN + RISKY), max_size=14))
        def test_the_gates_cut_sections_where_commonmark_does_or_refuse_the_spec(self, lines):
            text = "\n".join(lines) + "\n"
            if engine.spec_reading_problem(text) is not None:
                return
            numbers, approval, end = commonmark(text)
            gate_numbers, gate_approval, gate_end = gate_sections(text)
            self.assertEqual(gate_numbers, numbers, text)
            self.assertEqual(gate_approval, approval, text)
            self.assertEqual(gate_end, end, text)

        @settings(max_examples=200, deadline=None)
        @given(lines=st.lists(st.sampled_from(CLEAN), max_size=14))
        def test_a_clean_spec_is_never_refused(self, lines):
            text = "\n".join(lines) + "\n"
            self.assertIsNone(engine.spec_reading_problem(text), text)
            self.assertEqual(heading_lines(text), commonmark(text)[0], text)


    # Lines built from tags, headings, fences and blank-looking text, with the spaces around them drawn from the Unicode
    # and control characters a reader may or may not take for a space or a line end.
    SPACE_GAPS = ("", " ", "\t", "\u00a0", "\u2003", "\u200b", "\ufeff", "\v", "\f", "\x1c", "\x01", "\u2028", "\x85")
    SPACED_LINES = ("<div{}>", "<div{}class=\"x\"{}>", "<pre{}>", "</pre{}>", "<span{}>", "<script{}>", "<div{}/>",
                    "<!--{}-->", "<!--{}", "{}-->", "<?{}", "?>{}", "<![CDATA[{}]]>", "<!DOCTYPE{}html>", "{}## Approval",
                    "##{}Approval", "## Approval{}", "{}## Approval{}", "## Open questions{}", "{}# Title", "```{}",
                    "{}```", "~~~{}", "{}text{}", "text{}", "{}", "<b>{}</b>", "<img{}src=\"x\">", "{}- ## Approval",
                    "> {}## Approval", "{}Approved-by: Ana (2026-11-06)", "{}===", "{}---", "    {}## Approval",
                    "\t{}```", "{}- item", "  {}text")

    class WhitespaceAgreement(unittest.TestCase):
        """Wherever the gates read a spec without a reading problem, they cut it where CommonMark does: its headings, its
        fenced code, its Approval section. A line break a reader may take for one, or an unusual space beside a tag,
        heading or fence, is a reading problem instead."""

        @settings(max_examples=600, deadline=None)
        @given(lines=st.lists(st.tuples(st.sampled_from(SPACED_LINES), st.sampled_from(SPACE_GAPS),
                                        st.sampled_from(SPACE_GAPS)).map(lambda t: t[0].format(t[1], t[2])),
                              max_size=12))
        def test_the_gates_cut_the_spec_where_commonmark_does_or_refuse_it(self, lines):
            text = "\n".join(lines) + "\n"
            if re.search("[\v\f\x1c-\x1e\x85\u2028\u2029]", text):
                self.assertIsNotNone(engine.spec_reading_problem(text), text)
                return
            if engine.spec_reading_problem(text) is not None:
                return
            numbers, approval, end = commonmark(text)
            gate_numbers, gate_approval, gate_end = gate_sections(text)
            self.assertEqual(gate_numbers, numbers, text)
            self.assertEqual(gate_approval, approval, text)
            self.assertEqual(gate_end, end, text)
            self.assertEqual(fenced_gate(text), fenced_commonmark(text), text)


    def fenced_commonmark(text):
        """The line numbers CommonMark puts in fenced code blocks, fence lines included."""
        lines = set()
        for token in MarkdownIt("commonmark", {"html": True}).parse(text):
            if token.type == "fence":
                lines.update(range(token.map[0], token.map[1]))
        return lines


    def fenced_gate(text):
        return {i for i, (_, fenced, _, _) in enumerate(engine.scan_lines(text)) if fenced}


if given is not None:
    class LineEndingVerdicts(unittest.TestCase):
        """A spec's line endings don't change what the gates decide: LF, CRLF and a lone CR read the same, in the file and
        in the text a hook proposes."""

        @settings(max_examples=300, deadline=None)
        @given(before=st.lists(st.sampled_from(CLEAN + RISKY), max_size=10),
               after=st.lists(st.sampled_from(CLEAN + RISKY), max_size=10),
               eol_before=st.sampled_from(("\n", "\r\n", "\r")), eol_after=st.sampled_from(("\n", "\r\n", "\r")))
        def test_spec_guard_gives_the_same_verdict_under_any_line_endings(self, before, after, eol_before, eol_after):
            old, new = "\n".join(before) + "\n", "\n".join(after) + "\n"

            self.assertEqual(engine.spec_guard(old.replace("\n", eol_before), new.replace("\n", eol_after)),
                             engine.spec_guard(old, new))


if __name__ == "__main__":
    unittest.main()
