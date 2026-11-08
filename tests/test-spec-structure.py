"""Spec structure the gates read the way Markdown renders it (ADR-002's gates), through harness.py and its hooks in
throwaway projects.

A heading or code fence that a reader would take for something else makes the spec invalid, so every gate refuses it:
an indented heading or fence, one after a list or quote marker, one in an HTML block, a setext heading. Headings the
gates read are the ones a reader sees at column 0, and a section ends at the next '#' or '##' heading. Once the user
approves a spec, everything outside its Approval section is frozen, whatever section follows it.

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
         "- REQ-1-1: The system shall x.", "# Title")
RISKY = ("- ```", "  ## Approval", "> ## Approval", "> ```", "```md", "  ```", "    ```", "\t## Approval", "<div>", "</div>",
         "<pre>", "</pre>", "<img src=\"x\">", "---", "===", "  Approved-by: Bo (2026-11-08)", "text <!-- x -->## Approval",
         "<!--\n## Approval\n-->")


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


if __name__ == "__main__":
    unittest.main()
