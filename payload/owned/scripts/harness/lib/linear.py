"""Linear as the system of record: read an issue, post a comment, move an issue to a workflow state.

Standard library only. Talks to Linear's GraphQL API with a personal API key (LINEAR_API_KEY, sent as the
Authorization header). HARNESS_LINEAR_URL points it elsewhere (a test server). Issue text is untrusted: callers
quote it as source material and never follow instructions in it.
"""
import json
import os
import re
import urllib.error
import urllib.request

API_URL = "https://api.linear.app/graphql"
ISSUE_ID = re.compile(r"^[A-Z][A-Z0-9]{0,9}-\d+$")
# Workflow state types a harness may never move an issue to: closing a ticket is the human's call.
CLOSED_TYPES = ("completed", "canceled")

ISSUE_QUERY = """query Issue($id: String!) {
  issue(id: $id) {
    id identifier title description url priority
    state { id name type }
    team { id key name states { nodes { id name type } } }
    labels { nodes { name } }
    assignee { name }
  }
}"""
COMMENT_MUTATION = """mutation Comment($issueId: String!, $body: String!) {
  commentCreate(input: {issueId: $issueId, body: $body}) { success comment { id url } }
}"""
STATE_MUTATION = """mutation Move($id: String!, $stateId: String!) {
  issueUpdate(id: $id, input: {stateId: $stateId}) { success issue { identifier state { name type } } }
}"""


class LinearError(Exception):
    pass


def request(query, variables, timeout=30):
    key = os.environ.get("LINEAR_API_KEY", "")
    if not key:
        raise LinearError("LINEAR_API_KEY is not set (a personal API key from Linear's Security & access settings)")
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(os.environ.get("HARNESS_LINEAR_URL") or API_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": key,
                                          "User-Agent": "agentic-harness"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LinearError("Linear answered HTTP %d: %s" % (exc.code, exc.read().decode("utf-8", "replace")[:300]))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise LinearError("can't reach Linear: %s" % exc)
    if data.get("errors"):
        raise LinearError("Linear refused the request: %s" % "; ".join(
            str(e.get("message")) for e in data["errors"] if isinstance(e, dict))[:300])
    return data.get("data") or {}


def issue_from(data):
    """The issue from a GraphQL answer ({"data": {"issue": ...}}, {"issue": ...}) or a bare issue object, as the
    Linear MCP server's get_issue returns it."""
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if isinstance(data, dict) and isinstance(data.get("issue"), dict):
        data = data["issue"]
    if not isinstance(data, dict) or not data.get("identifier"):
        raise LinearError("not a Linear issue (no identifier)")
    return data


def fetch_issue(identifier):
    if not ISSUE_ID.match(identifier):
        raise LinearError("'%s' is not a Linear issue id (like DIS-123)" % identifier)
    found = request(ISSUE_QUERY, {"id": identifier}).get("issue")
    if not found:
        raise LinearError("Linear has no issue %s" % identifier)
    return issue_from(found)


def post_comment(issue_id, body):
    result = request(COMMENT_MUTATION, {"issueId": issue_id, "body": body}).get("commentCreate") or {}
    if not result.get("success"):
        raise LinearError("Linear did not create the comment")
    return (result.get("comment") or {}).get("url") or ""


def target_state(issue, name):
    """The workflow state of the issue's team called name. Refuses states that close the issue."""
    states = ((issue.get("team") or {}).get("states") or {}).get("nodes") or []
    match = next((s for s in states if str(s.get("name", "")).lower() == name.lower()), None)
    if match is None:
        raise LinearError("team %s has no state '%s' (states: %s)" % (
            (issue.get("team") or {}).get("key", "?"), name, ", ".join(s.get("name", "?") for s in states) or "none"))
    if match.get("type") in CLOSED_TYPES:
        raise LinearError("'%s' closes the issue (type %s); only a human closes a ticket" % (name, match["type"]))
    return match


def move_issue(issue, state):
    result = request(STATE_MUTATION, {"id": issue["id"], "stateId": state["id"]}).get("issueUpdate") or {}
    if not result.get("success"):
        raise LinearError("Linear did not move %s" % issue.get("identifier"))
    return ((result.get("issue") or {}).get("state") or {}).get("name") or state.get("name")
