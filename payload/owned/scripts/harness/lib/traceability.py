"""Traceability export (ADR-004): the trace model harness.py builds, written as ReqIF 1.2, Sphinx-Needs needs.json
(format 1) or a self-contained HTML matrix. Pure functions of the model, standard library only.

Harness-owned file: the harness update replaces it.

Ids are the spec's own (REQ-, NFR- and AC-<task>-<n>), TASK-<task> for a task and TEST-<task>-<hash of its path> for a
test file. Results, verdicts, fingerprints and commits are strings: ReqIF has no type for them, and ADR-004 defines
what they mean.
"""
import html
import json
import xml.etree.ElementTree as ET

REQIF_NS = "http://www.omg.org/spec/ReqIF/20110401/reqif.xsd"
NOTE = "Derived from backbone/ and git; not the system of record (ADR-004)."
REQUIREMENT_ATTRS = ("ReqIF.ForeignID", "ReqIF.Text", "Harness.Kind", "Harness.Task", "Harness.EARSPattern")
CRITERION_ATTRS = ("ReqIF.ForeignID", "ReqIF.Text", "Harness.Task", "Harness.Result", "Harness.Verdict",
                   "Harness.Evidence", "Harness.JudgeTests", "Harness.JudgedAt", "Harness.CodeFingerprint",
                   "Harness.Commits")
TEST_ATTRS = ("ReqIF.ForeignID", "ReqIF.Name", "Harness.Task")
TASK_ATTRS = ("ReqIF.ForeignID", "ReqIF.Name", "Harness.Status", "Harness.Spec", "Harness.SpecFingerprint",
              "Harness.ChangeClass", "Harness.Grill", "Harness.Approval", "Harness.Verdict", "Harness.JudgedAt",
              "Harness.CodeFingerprint", "Harness.Commits", "Harness.TestRun", "Harness.TestFilesFrom",
              "Harness.Reviews", "Harness.Gaps")
# key -> (element, IDENTIFIER, LONG-NAME, attribute definitions)
SPEC_TYPES = {
    "requirement": ("SPEC-OBJECT-TYPE", "AH-T-REQUIREMENT", "Requirement", REQUIREMENT_ATTRS),
    "criterion": ("SPEC-OBJECT-TYPE", "AH-T-CRITERION", "Acceptance criterion", CRITERION_ATTRS),
    "test": ("SPEC-OBJECT-TYPE", "AH-T-TEST", "Test", TEST_ATTRS),
    "verifies": ("SPEC-RELATION-TYPE", "AH-T-VERIFIES", "Verifies", ()),
    "tests": ("SPEC-RELATION-TYPE", "AH-T-TESTS", "Tests", ()),
    "task": ("SPECIFICATION-TYPE", "AH-T-TASK", "Task", TASK_ATTRS),
}


def commits_text(task):
    """The commits that carry the judged code; "none" when a judged code is in no commit, "" when nothing was judged."""
    return " ".join(task["commits"]) or ("none" if task["judged_at"] else "")


def task_values(task):
    return {"Status": task["status"], "Spec": task["spec"], "SpecFingerprint": task["spec_fingerprint"],
            "ChangeClass": task["change_class"], "Grill": task["grill"], "Approval": "\n".join(task["approval"]),
            "Verdict": task["verdict"], "JudgedAt": task["judged_at"], "CodeFingerprint": task["code_fingerprint"],
            "Commits": commits_text(task), "TestRun": task["test_run"], "TestFilesFrom": task["test_files_from"],
            "Reviews": task["reviews"], "Gaps": "\n".join(task["gaps"])}


def criterion_values(task, c):
    return {"Result": c["result"], "Verdict": task["verdict"], "Evidence": c["evidence"],
            "JudgeTests": ", ".join(c["judge_tests"]), "JudgedAt": task["judged_at"],
            "CodeFingerprint": task["code_fingerprint"], "Commits": commits_text(task)}


# --------------------------------------------------------------------------- ReqIF 1.2

def indent(element, level=0):
    pad = "\n" + "  " * level
    if len(element):
        element.text = pad + "  "
        for child in element:
            indent(child, level + 1)
            child.tail = pad + "  "
        child.tail = pad


def reqif(model):
    time = model["time"]
    stamp = {"LAST-CHANGE": time}

    def sub(parent, tag, text=None, **attrs):
        child = ET.SubElement(parent, tag, {k.replace("_", "-"): v for k, v in attrs.items()})
        child.text = text
        return child

    def ref(parent, wrapper, tag, ident):
        sub(sub(parent, wrapper), tag, ident)

    root = ET.Element("REQ-IF", {"xmlns": REQIF_NS})
    header = sub(sub(root, "THE-HEADER"), "REQ-IF-HEADER", IDENTIFIER="AH-HEADER")
    sub(header, "COMMENT", "%s HEAD %s; the code %s HEAD." % (
        NOTE, model["head"] or "(no commit)", "matches" if model["code_matches_head"] else "differs from"))
    sub(header, "CREATION-TIME", time)
    sub(header, "REPOSITORY-ID", model["project"])
    sub(header, "REQ-IF-TOOL-ID", model["tool"])
    sub(header, "REQ-IF-VERSION", "1.0")
    sub(header, "SOURCE-TOOL-ID", model["tool"])
    sub(header, "TITLE", "Traceability: %s" % model["project"])
    content = sub(sub(root, "CORE-CONTENT"), "REQ-IF-CONTENT")
    datatype = sub(sub(content, "DATATYPES"), "DATATYPE-DEFINITION-STRING", IDENTIFIER="AH-D-STRING",
                   LONG_NAME="String", **stamp)
    types = sub(content, "SPEC-TYPES")
    definitions = {}
    for key, (element, ident, name, attrs) in SPEC_TYPES.items():
        spec_type = sub(types, element, IDENTIFIER=ident, LONG_NAME=name, **stamp)
        if attrs:
            holder = sub(spec_type, "SPEC-ATTRIBUTES")
        for attr in attrs:
            definitions[key, attr] = "%s-%s" % (ident.replace("-T-", "-A-"), attr)
            definition = sub(holder, "ATTRIBUTE-DEFINITION-STRING", IDENTIFIER=definitions[key, attr],
                             LONG_NAME=attr, **stamp)
            ref(definition, "TYPE", "DATATYPE-DEFINITION-STRING-REF", "AH-D-STRING")
    objects, relations = sub(content, "SPEC-OBJECTS"), sub(content, "SPEC-RELATIONS")
    specifications = sub(content, "SPECIFICATIONS")
    longest = [0]

    def values(parent, key, given):
        holder = None
        for attr in SPEC_TYPES[key][3]:
            value = given.get(attr) or given.get(attr.split(".", 1)[1])
            if value:
                holder = holder if holder is not None else sub(parent, "VALUES")
                longest[0] = max(longest[0], len(value))
                ref(sub(holder, "ATTRIBUTE-VALUE-STRING", THE_VALUE=value), "DEFINITION",
                    "ATTRIBUTE-DEFINITION-STRING-REF", definitions[key, attr])

    def spec_object(ident, key, given):
        obj = sub(objects, "SPEC-OBJECT", IDENTIFIER=ident, LONG_NAME=ident, **stamp)
        values(obj, key, dict(given, **{"ReqIF.ForeignID": ident}))
        ref(obj, "TYPE", "SPEC-OBJECT-TYPE-REF", SPEC_TYPES[key][1])
        return ident

    def relation(source, key, target):
        rel = sub(relations, "SPEC-RELATION", IDENTIFIER="REL-%s-%s-%s" % (source, key, target), **stamp)
        ref(rel, "SOURCE", "SPEC-OBJECT-REF", source)
        ref(rel, "TARGET", "SPEC-OBJECT-REF", target)
        ref(rel, "TYPE", "SPEC-RELATION-TYPE-REF", SPEC_TYPES[key][1])

    for task in model["tasks"]:
        held = [spec_object(r["id"], "requirement", {"Text": r["text"], "Kind": r["kind"], "Task": task["id"],
                                                     "EARSPattern": r["ears_pattern"]})
                for r in task["requirements"]]
        for c in task["criteria"]:
            held.append(spec_object(c["id"], "criterion", dict(criterion_values(task, c), Text=c["text"],
                                                                Task=task["id"])))
            for target in c["proves"]:
                relation(c["id"], "verifies", target)
        for t in task["tests"]:
            held.append(spec_object(t["id"], "test", {"ReqIF.Name": t["path"], "Task": task["id"]}))
            for target in t["criteria"]:
                relation(t["id"], "tests", target)
        specification = sub(specifications, "SPECIFICATION", IDENTIFIER="TASK-" + task["id"],
                            LONG_NAME="Task %s: %s" % (task["id"], task["title"]), **stamp)
        values(specification, "task", dict(task_values(task), **{"ReqIF.ForeignID": task["id"],
                                                                 "ReqIF.Name": task["title"]}))
        children = sub(specification, "CHILDREN")
        for ident in held:
            ref(sub(children, "SPEC-HIERARCHY", IDENTIFIER="H-" + ident, **stamp), "OBJECT", "SPEC-OBJECT-REF", ident)
        ref(specification, "TYPE", "SPECIFICATION-TYPE-REF", SPEC_TYPES["task"][1])
    datatype.set("MAX-LENGTH", str(max(65535, longest[0])))
    indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


# --------------------------------------------------------------------------- Sphinx-Needs needs.json, format 1

def needs(model):
    found = {}

    def need(ident, kind, kind_name, title, status, **fields):
        entry = {"id": ident, "type": kind, "type_name": kind_name, "title": title or ident, "content": "",
                 "status": status, "tags": [], "links": []}
        entry.update({k: v for k, v in fields.items() if v not in (None, "")})
        found[ident] = entry

    for task in model["tasks"]:
        need("TASK-" + task["id"], "task", "Task", "Task %s: %s" % (task["id"], task["title"]), task["status"],
             harness_task=task["id"], **{"harness_" + _snake(k): v for k, v in task_values(task).items()
                                         if k != "Status"})
        for r in task["requirements"]:
            need(r["id"], "req", "Requirement", r["text"], None, harness_task=task["id"], harness_kind=r["kind"],
                 harness_ears_pattern=r["ears_pattern"])
        for c in task["criteria"]:
            need(c["id"], "ac", "Acceptance criterion", c["text"], c["result"], verifies=c["proves"],
                 harness_task=task["id"], **{"harness_" + _snake(k): v for k, v in criterion_values(task, c).items()})
        for t in task["tests"]:
            need(t["id"], "test", "Test", t["path"], None, tests=t["criteria"], harness_task=task["id"],
                 harness_path=t["path"])
    version = model["head"] or "working-tree"
    document = {"project": model["project"], "current_version": version,
                "versions": {version: {"creator": {"program": "agentic-harness", "version": model["version"]},
                                       "needs": found, "needs_amount": len(found)}}}
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _snake(name):
    return "".join("_" + ch.lower() if ch.isupper() else ch for ch in name).lstrip("_")


# --------------------------------------------------------------------------- HTML matrix

STYLE = """body{font:14px/1.45 system-ui,sans-serif;margin:24px;color:#1b1b1b;background:#fff}
table{border-collapse:collapse;margin:8px 0 16px;width:100%}th,td{border:1px solid #c8c8c8;padding:4px 8px;
text-align:left;vertical-align:top}th{background:#f2f2f2}table.facts{width:auto}table.facts th{width:14em}
.note{color:#555}@media (prefers-color-scheme:dark){body{background:#161616;color:#e6e6e6}th{background:#262626}
th,td{border-color:#444}.note{color:#aaa}}"""


def html_matrix(model):
    e = lambda value: html.escape(str(value), quote=True)
    ears = model["req_style"] == "ears"
    out = ["<!DOCTYPE html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
           "<title>Traceability: %s</title>" % e(model["project"]), "<style>%s</style>" % STYLE, "</head>", "<body>",
           "<h1>Traceability: %s</h1>" % e(model["project"]),
           '<p class="note">%s HEAD %s (%s); the code %s HEAD. %s</p>' % (
               e(NOTE), e(model["head"] or "(no commit)"), e(model["time"]),
               "matches" if model["code_matches_head"] else "differs from", e(model["tool"]))]
    if not model["tasks"]:
        out.append("<p>No task has a spec in backbone/specs/.</p>")
    for task in model["tasks"]:
        short = " ".join(c[:12] for c in task["commits"]) or ("none" if task["judged_at"] else "-")
        facts = (("Status", task["status"]), ("Change-Class", task["change_class"]),
                 ("Spec", "%s, fingerprint %s" % (task["spec"], task["spec_fingerprint"])), ("Grill", task["grill"]),
                 ("Approval", "; ".join(task["approval"]) or "none"), ("Judge verdict", task["verdict"]),
                 ("Judged at", task["judged_at"] or "-"), ("Judged code", task["code_fingerprint"] or "-"),
                 ("Judged code in commits", " ".join(task["commits"]) or short),
                 ("Test run", task["test_run"] or "-"), ("Test files from", task["test_files_from"]),
                 ("Reviews", task["reviews"]))
        out += ['<section id="task-%s">' % e(task["id"]), "<h2>Task %s: %s</h2>" % (e(task["id"]), e(task["title"])),
                '<table class="facts"><tbody>']
        out += ["<tr><th>%s</th><td>%s</td></tr>" % (e(k), e(v)) for k, v in facts]
        out += ["</tbody></table>", '<table class="matrix"><thead><tr><th>Requirement</th>%s<th>Acceptance criterion'
                "</th><th>Test files</th><th>Result</th><th>Verdict</th><th>Commits</th></tr></thead><tbody>"
                % ("<th>EARS pattern</th>" if ears else "")]
        paths = {t["id"]: t["path"] for t in task["tests"]}

        def row(requirement, pattern, criterion):
            cells = [requirement] + ([pattern] if ears else [])
            if criterion is None:
                cells += ["no acceptance criterion", "-", "-", task["verdict"], short]
            else:
                files = ", ".join(paths[t] for t in criterion["tests"]) or (
                    "unknown" if task["test_files_from"] == "unknown" else "none")
                cells += ["%s %s" % (criterion["id"], criterion["text"]), files, criterion["result"], task["verdict"],
                          short]
            out.append("<tr>%s</tr>" % "".join("<td>%s</td>" % e(cell) for cell in cells))

        for r in task["requirements"]:
            proving = [c for c in task["criteria"] if r["id"] in c["proves"]]
            for criterion in proving or [None]:
                row("%s %s" % (r["id"], r["text"]), r["ears_pattern"] or "-", criterion)
        for criterion in task["criteria"]:
            if not criterion["proves"]:
                row("no known requirement", "-", criterion)
        out += ["</tbody></table>", "<h3>Gaps</h3>"]
        out += ["<ul>"] + ["<li>%s</li>" % e(g) for g in task["gaps"]] + ["</ul>"] if task["gaps"] else \
            ["<p>None the harness can see.</p>"]
        out.append("</section>")
    out += ["</body>", "</html>"]
    return "\n".join(out) + "\n"


FORMATS = {"reqif": (reqif, "traceability.reqif"), "needs": (needs, "needs.json"),
           "html": (html_matrix, "traceability.html")}
