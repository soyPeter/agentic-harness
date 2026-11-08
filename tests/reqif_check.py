"""A minimal check of a ReqIF document against the OMG ReqIF 1.2 schema, vendored for the tests, and readers for one.

The rules are copied by hand from reqif.xsd (http://www.omg.org/spec/ReqIF/20110401/reqif.xsd, the schema ReqIF 1.0.1
to 1.2 share), for the elements the harness writes: the children and attributes each one requires or allows, the
order where the schema fixes one (xsd:sequence) and none where it doesn't (xsd:all), the fixed REQ-IF-VERSION, and the
xsd:ID, xsd:IDREF, xsd:dateTime and xsd:integer values. On top, what an importer relies on: every reference names an
element of the kind it says, a value's attribute definition belongs to its element's type, and a string fits its
datatype's MAX-LENGTH. An element the schema allows but this subset doesn't list is reported, so the check is extended
from reqif.xsd deliberately rather than passing it unseen. Nothing is downloaded.
"""
import re
import xml.etree.ElementTree as ET

NS = "{http://www.omg.org/spec/ReqIF/20110401/reqif.xsd}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
NCNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]*$")
DATETIME = re.compile(r"^-?\d{4,}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)?$")
IDENTIFIABLE = {"IDENTIFIER": "ID", "LAST-CHANGE": "dateTime"}
NAMED = {"DESC": "string", "LONG-NAME": "string"}
VALUE_KINDS = ["ATTRIBUTE-VALUE-STRING"]
SPEC_TYPE = ("all", [("ALTERNATIVE-ID", False), ("SPEC-ATTRIBUTES", False)], IDENTIFIABLE, NAMED)


def one(*names):
    """A wrapper element holding exactly one of names (xsd:choice, minOccurs 1)."""
    return ("one", list(names), {}, {})


def many(*names):
    """A list element holding any number of names (xsd:choice, maxOccurs unbounded)."""
    return ("many", list(names), {}, {})


# element, or "PARENT/ELEMENT" where the schema reuses a name -> (content, children, required attrs, optional attrs).
# content: "sequence" (children in this order), "all" (any order, each at most once), "one", "many", or "text:<type>".
# Children of sequence and all are (name, required).
RULES = {
    "REQ-IF": ("sequence", [("THE-HEADER", True), ("CORE-CONTENT", True), ("TOOL-EXTENSIONS", False)], {},
               {XML_LANG: "string"}),
    "THE-HEADER": one("REQ-IF-HEADER"),
    "CORE-CONTENT": one("REQ-IF-CONTENT"),
    "REQ-IF-HEADER": ("sequence", [("COMMENT", False), ("CREATION-TIME", True), ("REPOSITORY-ID", False),
                                   ("REQ-IF-TOOL-ID", True), ("REQ-IF-VERSION", True), ("SOURCE-TOOL-ID", True),
                                   ("TITLE", True)], {"IDENTIFIER": "ID"}, {}),
    "COMMENT": ("text:string", [], {}, {}),
    "CREATION-TIME": ("text:dateTime", [], {}, {}),
    "REPOSITORY-ID": ("text:string", [], {}, {}),
    "REQ-IF-TOOL-ID": ("text:string", [], {}, {}),
    "REQ-IF-VERSION": ("text:fixed 1.0", [], {}, {}),
    "SOURCE-TOOL-ID": ("text:string", [], {}, {}),
    "TITLE": ("text:string", [], {}, {}),
    "REQ-IF-CONTENT": ("sequence", [("DATATYPES", False), ("SPEC-TYPES", False), ("SPEC-OBJECTS", False),
                                    ("SPEC-RELATIONS", False), ("SPECIFICATIONS", False),
                                    ("SPEC-RELATION-GROUPS", False)], {}, {}),
    "DATATYPES": many("DATATYPE-DEFINITION-STRING"),
    "DATATYPE-DEFINITION-STRING": ("all", [("ALTERNATIVE-ID", False)], dict(IDENTIFIABLE, **{"MAX-LENGTH": "integer"}),
                                   NAMED),
    "SPEC-TYPES": many("SPEC-OBJECT-TYPE", "SPEC-RELATION-TYPE", "SPECIFICATION-TYPE"),
    "SPEC-OBJECT-TYPE": SPEC_TYPE,
    "SPEC-RELATION-TYPE": SPEC_TYPE,
    "SPECIFICATION-TYPE": SPEC_TYPE,
    "SPEC-ATTRIBUTES": many("ATTRIBUTE-DEFINITION-STRING"),
    "ATTRIBUTE-DEFINITION-STRING": ("all", [("ALTERNATIVE-ID", False), ("DEFAULT-VALUE", False), ("TYPE", True)],
                                    IDENTIFIABLE, dict(NAMED, **{"IS-EDITABLE": "boolean"})),
    "ATTRIBUTE-DEFINITION-STRING/TYPE": one("DATATYPE-DEFINITION-STRING-REF"),
    "SPEC-OBJECTS": many("SPEC-OBJECT"),
    "SPEC-OBJECT": ("all", [("ALTERNATIVE-ID", False), ("VALUES", False), ("TYPE", True)], IDENTIFIABLE, NAMED),
    "SPEC-OBJECT/TYPE": one("SPEC-OBJECT-TYPE-REF"),
    "VALUES": many(*VALUE_KINDS),
    "ATTRIBUTE-VALUE-STRING": ("all", [("DEFINITION", True)], {"THE-VALUE": "string"}, {}),
    "ATTRIBUTE-VALUE-STRING/DEFINITION": one("ATTRIBUTE-DEFINITION-STRING-REF"),
    "SPEC-RELATIONS": many("SPEC-RELATION"),
    "SPEC-RELATION": ("all", [("ALTERNATIVE-ID", False), ("VALUES", False), ("SOURCE", True), ("TARGET", True),
                              ("TYPE", True)], IDENTIFIABLE, NAMED),
    "SPEC-RELATION/SOURCE": one("SPEC-OBJECT-REF"),
    "SPEC-RELATION/TARGET": one("SPEC-OBJECT-REF"),
    "SPEC-RELATION/TYPE": one("SPEC-RELATION-TYPE-REF"),
    "SPECIFICATIONS": many("SPECIFICATION"),
    "SPECIFICATION": ("all", [("ALTERNATIVE-ID", False), ("VALUES", False), ("CHILDREN", False), ("TYPE", True)],
                      IDENTIFIABLE, NAMED),
    "SPECIFICATION/TYPE": one("SPECIFICATION-TYPE-REF"),
    "CHILDREN": many("SPEC-HIERARCHY"),
    "SPEC-HIERARCHY": ("all", [("ALTERNATIVE-ID", False), ("CHILDREN", False), ("EDITABLE-ATTS", False),
                               ("OBJECT", True)], IDENTIFIABLE,
                       dict(NAMED, **{"IS-EDITABLE": "boolean", "IS-TABLE-INTERNAL": "boolean"})),
    "SPEC-HIERARCHY/OBJECT": one("SPEC-OBJECT-REF"),
}
# A reference element -> the element kind it must name. SPEC-RELATION's ends are GLOBAL-REFs (strings) in the schema,
# which may point into another document; an export is self-contained, so here they must resolve too.
REFERENCES = {name + "-REF": name for name in ("DATATYPE-DEFINITION-STRING", "SPEC-OBJECT-TYPE", "SPEC-RELATION-TYPE",
                                               "SPECIFICATION-TYPE", "ATTRIBUTE-DEFINITION-STRING", "SPEC-OBJECT")}
VALUE_TYPE = {"text:string": "string", "text:dateTime": "dateTime"}


def local(tag):
    return tag[len(NS):] if tag.startswith(NS) else None


def value_problem(kind, value):
    if kind == "ID" and not NCNAME.match(value):
        return "is not an xsd:ID (NCName)"
    if kind == "dateTime" and not DATETIME.match(value):
        return "is not an xsd:dateTime"
    if kind == "integer" and not re.match(r"^[+-]?\d+$", value):
        return "is not an xsd:integer"
    if kind == "boolean" and value not in ("true", "false", "1", "0"):
        return "is not an xsd:boolean"
    return None


def structure(element, parent, path, problems):
    name = local(element.tag)
    where = "%s/%s" % (path, name or element.tag)
    if name is None:
        problems.append("%s: not in the ReqIF namespace" % where)
        return
    if name in REFERENCES:
        if len(element) or not (element.text or "").strip():
            problems.append("%s: a reference holds one identifier and nothing else" % where)
        return
    rule = RULES.get("%s/%s" % (parent, name)) or RULES.get(name)
    if rule is None:
        problems.append("%s: not an element this check knows (extend tests/reqif_check.py from reqif.xsd)" % where)
        return
    content, children, required, optional = rule
    for attr, kind in required.items():
        if attr not in element.attrib:
            problems.append("%s: attribute %s is required" % (where, attr))
    for attr, value in element.attrib.items():
        kind = required.get(attr) or optional.get(attr)
        if kind is None:
            problems.append("%s: attribute %s is not allowed" % (where, attr))
        elif value_problem(kind, value):
            problems.append("%s: %s=%r %s" % (where, attr, value, value_problem(kind, value)))
    names = [local(child.tag) or child.tag for child in element]
    if content.startswith("text:"):
        if names:
            problems.append("%s: holds only text" % where)
        text = element.text or ""
        if content == "text:fixed 1.0" and text != "1.0":
            problems.append("%s: the schema fixes it to 1.0, not %r" % (where, text))
        elif value_problem(VALUE_TYPE.get(content), text):
            problems.append("%s: %r %s" % (where, text, value_problem(VALUE_TYPE.get(content), text)))
        return
    if (element.text or "").strip():
        problems.append("%s: has text outside its child elements" % where)
    if content in ("sequence", "all"):
        allowed = [child for child, _ in children]
        for child, needed in children:
            if needed and child not in names:
                problems.append("%s: element %s is required" % (where, child))
            if names.count(child) > 1:
                problems.append("%s: element %s appears %d times, at most once" % (where, child, names.count(child)))
        for child in names:
            if child not in allowed:
                problems.append("%s: element %s is not allowed here" % (where, child))
        present = [child for child in names if child in allowed]
        if content == "sequence" and present != sorted(present, key=allowed.index):
            problems.append("%s: children out of the schema's order (%s; expected %s)"
                            % (where, ", ".join(present), ", ".join(sorted(present, key=allowed.index))))
    else:
        for child in names:
            if child not in children:
                problems.append("%s: element %s is not allowed here" % (where, child))
        if content == "one" and len(names) != 1:
            problems.append("%s: holds exactly one of %s, not %d elements" % (where, ", ".join(children), len(names)))
    for child in element:
        structure(child, name, where, problems)


def problems(document):
    """Every way document breaks the vendored rules, as readable lines; [] for a valid export."""
    try:
        root = ET.fromstring(document.encode("utf-8") if isinstance(document, str) else document)
    except ET.ParseError as exc:
        return ["not well-formed XML: %s" % exc]
    found = []
    if root.tag != NS + "REQ-IF":
        found.append("the root element is %s, not REQ-IF in %s" % (root.tag, NS))
    structure(root, "", "", found)
    by_id = {}
    for element in root.iter():
        ident = element.get("IDENTIFIER")
        if ident is not None and local(element.tag) != "ALTERNATIVE-ID":
            if ident in by_id:
                found.append("IDENTIFIER %s is used twice (xsd:ID values are unique)" % ident)
            by_id.setdefault(ident, element)
    for element in root.iter():
        kind = REFERENCES.get(local(element.tag) or "")
        target = by_id.get((element.text or "").strip())
        if kind and (target is None or local(target.tag) != kind):
            found.append("%s %r names no %s" % (local(element.tag), (element.text or "").strip(), kind))
    for holder in root.iter():
        values = holder.find(NS + "VALUES")
        type_ref = holder.find("%sTYPE/*" % NS)
        if values is None or type_ref is None:
            continue
        spec_type = by_id.get((type_ref.text or "").strip())
        definitions = {d.get("IDENTIFIER"): d for d in spec_type.iter(NS + "ATTRIBUTE-DEFINITION-STRING")} \
            if spec_type is not None else {}
        seen = set()
        for value in values:
            ref = value.find("%sDEFINITION/%sATTRIBUTE-DEFINITION-STRING-REF" % (NS, NS))
            ident = (ref.text or "").strip() if ref is not None else None
            if ident not in definitions:
                found.append("%s %s: a value for %s, which its type %s doesn't define"
                             % (local(holder.tag), holder.get("IDENTIFIER"), ident, type_ref.text))
                continue
            if ident in seen:
                found.append("%s %s: two values for %s" % (local(holder.tag), holder.get("IDENTIFIER"), ident))
            seen.add(ident)
            datatype = by_id.get((definitions[ident].findtext("%sTYPE/%sDATATYPE-DEFINITION-STRING-REF" % (NS, NS))
                                  or "").strip())
            limit = datatype.get("MAX-LENGTH") if datatype is not None else None
            if limit and limit.isdigit() and len(value.get("THE-VALUE") or "") > int(limit):
                found.append("%s %s: the value for %s is longer than MAX-LENGTH %s"
                             % (local(holder.tag), holder.get("IDENTIFIER"), ident, limit))
    return found


def _values(holder, by_id):
    named = {}
    for value in holder.iter(NS + "ATTRIBUTE-VALUE-STRING"):
        definition = by_id.get(value.findtext("%sDEFINITION/%sATTRIBUTE-DEFINITION-STRING-REF" % (NS, NS)))
        if definition is not None:
            named[definition.get("LONG-NAME")] = value.get("THE-VALUE")
    return named


def _index(document):
    root = ET.fromstring(document.encode("utf-8") if isinstance(document, str) else document)
    return root, {e.get("IDENTIFIER"): e for e in root.iter() if e.get("IDENTIFIER")}


def objects(document):
    """{ReqIF.ForeignID: {attribute definition LONG-NAME: value}} for every SPEC-OBJECT and SPECIFICATION, with the
    element's kind under "element", its type's LONG-NAME under "type" and its IDENTIFIER under "identifier"."""
    root, by_id = _index(document)
    found = {}
    for kind in ("SPEC-OBJECT", "SPECIFICATION"):
        for holder in root.iter(NS + kind):
            values = _values(holder, by_id)
            spec_type = by_id.get(holder.findtext("%sTYPE/*" % NS))
            values.update({"element": kind, "type": spec_type.get("LONG-NAME") if spec_type is not None else None,
                           "identifier": holder.get("IDENTIFIER")})
            found[values.get("ReqIF.ForeignID")] = values
    return found


def relations(document):
    """[(relation type LONG-NAME, source ReqIF.ForeignID, target ReqIF.ForeignID)], sorted."""
    root, by_id = _index(document)
    foreign = {ident: _values(e, by_id).get("ReqIF.ForeignID") for ident, e in by_id.items()
               if local(e.tag) == "SPEC-OBJECT"}
    found = []
    for relation in root.iter(NS + "SPEC-RELATION"):
        spec_type = by_id.get(relation.findtext("%sTYPE/%sSPEC-RELATION-TYPE-REF" % (NS, NS)))
        found.append((spec_type.get("LONG-NAME") if spec_type is not None else None,
                      foreign.get(relation.findtext("%sSOURCE/%sSPEC-OBJECT-REF" % (NS, NS))),
                      foreign.get(relation.findtext("%sTARGET/%sSPEC-OBJECT-REF" % (NS, NS)))))
    return sorted(found, key=lambda r: tuple(str(x) for x in r))


def hierarchy(document):
    """{specification ReqIF.ForeignID: [ReqIF.ForeignID of each object its hierarchy holds, in order]}."""
    root, by_id = _index(document)
    found = {}
    for specification in root.iter(NS + "SPECIFICATION"):
        found[_values(specification, by_id).get("ReqIF.ForeignID")] = [
            _values(by_id[ref.text], by_id).get("ReqIF.ForeignID") if ref.text in by_id else None
            for ref in specification.iter(NS + "SPEC-OBJECT-REF")]
    return found


def header(document):
    """{element name: text} of REQ-IF-HEADER."""
    root, _ = _index(document)
    head = root.find("%sTHE-HEADER/%sREQ-IF-HEADER" % (NS, NS))
    return {local(e.tag): e.text for e in head} if head is not None else {}
