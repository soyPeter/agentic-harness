"""A minimal check of a ReqIF document against the OMG ReqIF 1.2 schema, vendored for the tests, and readers for one.

The rules are copied by hand from reqif.xsd (http://www.omg.org/spec/ReqIF/20110401/reqif.xsd, the schema ReqIF 1.0.1
to 1.2 share), for the elements the harness writes: the children and attributes each one requires or allows, the
order where the schema fixes one (xsd:sequence) and none where it doesn't (xsd:all), the fixed REQ-IF-VERSION, and the
xsd:ID, xsd:IDREF, xsd:dateTime and xsd:integer values. On top, what an importer relies on: every reference names an
element of the kind it says, a value's attribute definition belongs to its element's type, and a string fits its
datatype's MAX-LENGTH, an enumeration value names a value of its definition's datatype, and a definition that isn't
MULTI-VALUED takes one. An element the schema allows but this subset doesn't list is reported, so the check is extended
from reqif.xsd deliberately rather than passing it unseen. Nothing is downloaded.

XHTML values (the schema's XHTML-CONTENT, xhtml.BlkStruct.class) hold one xhtml:div or xhtml:p. The export writes only
xhtml:object in them, which the ReqIF Implementation Guide uses for a file exchanged with the document: it needs data
and type. A .reqifz is a ZIP archive with the .reqif documents at its top level and the files their objects name,
relative to the document (prostep ivip PSI 18, "ReqIFz"); archive_problems checks that every named file is there.
"""
import io
import re
import xml.etree.ElementTree as ET
import zipfile

NS = "{http://www.omg.org/spec/ReqIF/20110401/reqif.xsd}"
XHTML = "{http://www.w3.org/1999/xhtml}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
NCNAME = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]*$")
DATETIME = re.compile(r"^-?\d{4,}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)?$")
IDENTIFIABLE = {"IDENTIFIER": "ID", "LAST-CHANGE": "dateTime"}
NAMED = {"DESC": "string", "LONG-NAME": "string"}
KINDS = ("STRING", "ENUMERATION", "XHTML")
VALUE_KINDS = ["ATTRIBUTE-VALUE-" + kind for kind in KINDS]
DEFINITION_KINDS = ["ATTRIBUTE-DEFINITION-" + kind for kind in KINDS]
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
    "DATATYPES": many(*["DATATYPE-DEFINITION-" + kind for kind in KINDS]),
    "DATATYPE-DEFINITION-STRING": ("all", [("ALTERNATIVE-ID", False)], dict(IDENTIFIABLE, **{"MAX-LENGTH": "integer"}),
                                   NAMED),
    "DATATYPE-DEFINITION-ENUMERATION": ("all", [("ALTERNATIVE-ID", False), ("SPECIFIED-VALUES", False)], IDENTIFIABLE,
                                        NAMED),
    "SPECIFIED-VALUES": many("ENUM-VALUE"),
    "ENUM-VALUE": ("all", [("ALTERNATIVE-ID", False), ("PROPERTIES", True)], IDENTIFIABLE, NAMED),
    "PROPERTIES": one("EMBEDDED-VALUE"),
    "EMBEDDED-VALUE": ("all", [], {"KEY": "integer", "OTHER-CONTENT": "string"}, {}),
    "DATATYPE-DEFINITION-XHTML": ("all", [("ALTERNATIVE-ID", False)], IDENTIFIABLE, NAMED),
    "SPEC-TYPES": many("SPEC-OBJECT-TYPE", "SPEC-RELATION-TYPE", "SPECIFICATION-TYPE"),
    "SPEC-OBJECT-TYPE": SPEC_TYPE,
    "SPEC-RELATION-TYPE": SPEC_TYPE,
    "SPECIFICATION-TYPE": SPEC_TYPE,
    "SPEC-ATTRIBUTES": many(*DEFINITION_KINDS),
    "ATTRIBUTE-DEFINITION-STRING": ("all", [("ALTERNATIVE-ID", False), ("DEFAULT-VALUE", False), ("TYPE", True)],
                                    IDENTIFIABLE, dict(NAMED, **{"IS-EDITABLE": "boolean"})),
    "ATTRIBUTE-DEFINITION-STRING/TYPE": one("DATATYPE-DEFINITION-STRING-REF"),
    "ATTRIBUTE-DEFINITION-ENUMERATION": ("all", [("ALTERNATIVE-ID", False), ("DEFAULT-VALUE", False), ("TYPE", True)],
                                         dict(IDENTIFIABLE, **{"MULTI-VALUED": "boolean"}),
                                         dict(NAMED, **{"IS-EDITABLE": "boolean"})),
    "ATTRIBUTE-DEFINITION-ENUMERATION/TYPE": one("DATATYPE-DEFINITION-ENUMERATION-REF"),
    "ATTRIBUTE-DEFINITION-XHTML": ("all", [("ALTERNATIVE-ID", False), ("DEFAULT-VALUE", False), ("TYPE", True)],
                                   IDENTIFIABLE, dict(NAMED, **{"IS-EDITABLE": "boolean"})),
    "ATTRIBUTE-DEFINITION-XHTML/TYPE": one("DATATYPE-DEFINITION-XHTML-REF"),
    "SPEC-OBJECTS": many("SPEC-OBJECT"),
    "SPEC-OBJECT": ("all", [("ALTERNATIVE-ID", False), ("VALUES", False), ("TYPE", True)], IDENTIFIABLE, NAMED),
    "SPEC-OBJECT/TYPE": one("SPEC-OBJECT-TYPE-REF"),
    "VALUES": many(*VALUE_KINDS),
    "ATTRIBUTE-VALUE-STRING": ("all", [("DEFINITION", True)], {"THE-VALUE": "string"}, {}),
    "ATTRIBUTE-VALUE-STRING/DEFINITION": one("ATTRIBUTE-DEFINITION-STRING-REF"),
    "ATTRIBUTE-VALUE-ENUMERATION": ("all", [("DEFINITION", True), ("VALUES", False)], {}, {}),
    "ATTRIBUTE-VALUE-ENUMERATION/DEFINITION": one("ATTRIBUTE-DEFINITION-ENUMERATION-REF"),
    "ATTRIBUTE-VALUE-ENUMERATION/VALUES": many("ENUM-VALUE-REF"),
    "ATTRIBUTE-VALUE-XHTML": ("all", [("THE-VALUE", True), ("THE-ORIGINAL-VALUE", False), ("DEFINITION", True)], {},
                              {"IS-SIMPLIFIED": "boolean"}),
    "ATTRIBUTE-VALUE-XHTML/DEFINITION": one("ATTRIBUTE-DEFINITION-XHTML-REF"),
    "ATTRIBUTE-VALUE-XHTML/THE-VALUE": ("xhtml", [], {}, {}),
    "ATTRIBUTE-VALUE-XHTML/THE-ORIGINAL-VALUE": ("xhtml", [], {}, {}),
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
REFERENCES = {name + "-REF": name for name in ["DATATYPE-DEFINITION-" + kind for kind in KINDS] + DEFINITION_KINDS +
              ["SPEC-OBJECT-TYPE", "SPEC-RELATION-TYPE", "SPECIFICATION-TYPE", "SPEC-OBJECT", "ENUM-VALUE"]}
VALUE_TYPE = {"text:string": "string", "text:dateTime": "dateTime"}
# The XHTML elements the export writes -> the attributes each needs.
XHTML_ELEMENTS = {"div": (), "p": (), "object": ("data", "type")}


def local(tag):
    return tag[len(NS):] if tag.startswith(NS) else None


def xhtml_problems(element, where, problems):
    """An XHTML-CONTENT element: one xhtml:div or xhtml:p, and below it only the XHTML this check knows."""
    blocks = [child.tag[len(XHTML):] if child.tag.startswith(XHTML) else child.tag for child in element]
    if (element.text or "").strip() or len(blocks) != 1 or blocks[0] not in ("div", "p"):
        problems.append("%s: holds exactly one xhtml:div or xhtml:p" % where)
    for child in element.iter():
        if child is element:
            continue
        name = child.tag[len(XHTML):] if child.tag.startswith(XHTML) else None
        if name not in XHTML_ELEMENTS:
            problems.append("%s: %s is not XHTML this check knows (extend tests/reqif_check.py)" % (where, child.tag))
            continue
        for attr in XHTML_ELEMENTS[name]:
            if not child.get(attr):
                problems.append("%s: xhtml:%s needs %s" % (where, name, attr))


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
    if content == "xhtml":
        xhtml_problems(element, where, problems)
        return
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
        definitions = {d.get("IDENTIFIER"): d for d in spec_type.iter() if local(d.tag) in DEFINITION_KINDS} \
            if spec_type is not None else {}
        seen = set()
        for value in values:
            ref = value.find("%sDEFINITION/*" % NS)
            ident = (ref.text or "").strip() if ref is not None else None
            where = "%s %s" % (local(holder.tag), holder.get("IDENTIFIER"))
            if ident not in definitions:
                found.append("%s: a value for %s, which its type %s doesn't define" % (where, ident, type_ref.text))
                continue
            if ident in seen:
                found.append("%s: two values for %s" % (where, ident))
            seen.add(ident)
            definition = definitions[ident]
            datatype = by_id.get((definition.findtext("%sTYPE/*" % NS) or "").strip())
            if datatype is None:
                continue
            if local(value.tag) == "ATTRIBUTE-VALUE-STRING":
                limit = datatype.get("MAX-LENGTH")
                if limit and limit.isdigit() and len(value.get("THE-VALUE") or "") > int(limit):
                    found.append("%s: the value for %s is longer than MAX-LENGTH %s" % (where, ident, limit))
            elif local(value.tag) == "ATTRIBUTE-VALUE-ENUMERATION":
                allowed = {e.get("IDENTIFIER") for e in datatype.iter(NS + "ENUM-VALUE")}
                chosen = [(r.text or "").strip() for r in value.iter(NS + "ENUM-VALUE-REF")]
                found += ["%s: the value for %s names %s, which is not a value of its datatype %s"
                          % (where, ident, c, datatype.get("IDENTIFIER")) for c in chosen if c not in allowed]
                if definition.get("MULTI-VALUED") in ("false", "0") and len(chosen) > 1:
                    found.append("%s: the value for %s holds %d values; its definition isn't MULTI-VALUED"
                                 % (where, ident, len(chosen)))
    return found


def archive(data):
    """{file name: bytes} of a .reqifz."""
    with zipfile.ZipFile(io.BytesIO(data)) as handle:
        return {info.filename: handle.read(info) for info in handle.infolist()}


def archive_problems(data):
    """Every way a .reqifz breaks the archive rules or holds a document that breaks the vendored ones; [] if none."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as handle:
            names = [info.filename for info in handle.infolist()]
    except zipfile.BadZipFile as exc:
        return ["not a ZIP archive: %s" % exc]
    files = archive(data)
    found = ["%s: appears %d times in the archive" % (n, names.count(n)) for n in sorted(set(names))
             if names.count(n) > 1]
    found += ["%s: not a path inside the archive" % n for n in names
              if n.startswith("/") or "\\" in n or ".." in n.split("/")]
    documents = sorted(n for n in files if n.endswith(".reqif") and "/" not in n)
    if not documents:
        found.append("no .reqif document at the archive's top level")
    for name in documents:
        wrong = problems(files[name])
        found += ["%s: %s" % (name, p) for p in wrong]
        if wrong:
            continue
        for ident, objects in sorted(attachments(files[name]).items()):
            found += ["%s: %s's xhtml:object names %s, which the archive doesn't hold" % (name, ident, path)
                      for path, _ in objects if path not in files]
    return found


def _values(holder, by_id):
    """{attribute definition LONG-NAME: value}: a string as written, an enumeration as its values' LONG-NAMEs (comma
    separated), XHTML as its text."""
    named = {}
    for value in holder.find(NS + "VALUES") if holder.find(NS + "VALUES") is not None else []:
        definition = by_id.get(value.findtext("%sDEFINITION/*" % NS))
        if definition is None:
            continue
        kind = local(value.tag)
        if kind == "ATTRIBUTE-VALUE-ENUMERATION":
            text = ", ".join(by_id[r.text].get("LONG-NAME") for r in value.iter(NS + "ENUM-VALUE-REF")
                             if r.text in by_id)
        elif kind == "ATTRIBUTE-VALUE-XHTML":
            text = " ".join("".join(value.find(NS + "THE-VALUE").itertext()).split())
        else:
            text = value.get("THE-VALUE")
        named[definition.get("LONG-NAME")] = text
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


def attribute_types(document):
    """{spec type LONG-NAME: {attribute LONG-NAME: (STRING, ENUMERATION or XHTML, [its enumeration's value LONG-NAMEs in
    KEY order])}}."""
    root, by_id = _index(document)
    found = {}
    for spec_type in root.find("%sCORE-CONTENT/%sREQ-IF-CONTENT/%sSPEC-TYPES" % (NS, NS, NS)):
        attrs = found.setdefault(spec_type.get("LONG-NAME"), {})
        for definition in spec_type.iter():
            if local(definition.tag) not in DEFINITION_KINDS:
                continue
            datatype = by_id.get(definition.findtext("%sTYPE/*" % NS))
            values = sorted(datatype.iter(NS + "ENUM-VALUE"),
                            key=lambda e: int(e.find("%sPROPERTIES/%sEMBEDDED-VALUE" % (NS, NS)).get("KEY"))) \
                if datatype is not None else []
            attrs[definition.get("LONG-NAME")] = (local(definition.tag).rsplit("-", 1)[1],
                                                 [e.get("LONG-NAME") for e in values])
    return found


def attachments(document):
    """{ReqIF.ForeignID: [(data, type) of each xhtml:object in its values]} for each SPEC-OBJECT and SPECIFICATION that
    has one."""
    root, by_id = _index(document)
    found = {}
    for kind in ("SPEC-OBJECT", "SPECIFICATION"):
        for holder in root.iter(NS + kind):
            objects = [(o.get("data"), o.get("type")) for value in holder.findall("%sVALUES/*" % NS)
                       for o in value.iter(XHTML + "object")]
            if objects:
                found[_values(holder, by_id).get("ReqIF.ForeignID")] = objects
    return found
