"""Decision layer: typed decisions (choice / score / yes-no) from a pluggable provider.

Harness-owned. Decisions are advisory: they are logged (shadow) or shown as warnings (advise) and
never block anything. Deterministic checks stay in harness.py; a decision only adds a judgement that
code cannot compute (e.g. "does this commit message describe the staged change?").

Questions and thresholds live in scripts/harness/decisions.json (versioned, reviewable).
Providers:
  none     no calls (default)
  command  HARNESS_DECISION_CMD gets {"decision", "state", "questions"} as JSON on stdin and prints
           the answers as JSON (format below); any local or remote model can sit behind it
  ollama   a local Jev-style decision endpoint (Ollama /v1/systemone, e.g. the nimble model);
           data stays on the machine; HARNESS_DECISION_URL overrides the endpoint
  claude   Claude Messages API over plain HTTPS (standard library), structured outputs;
           needs ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) in the environment
  jev      TypeSafe Jev via `typesafe_sdk` (written from published examples; unverified)

Answers (normalised): {question id: {"type": "choice", "choice": str, "confidence": float}
                                   | {"type": "score", "score": float, "confidence": float}
                                   | {"type": "yesno", "p": float}}
"""
import hashlib
import json
import os
import shlex
import subprocess
import time

PROVIDERS = ("none", "command", "ollama", "claude", "jev")
MODES = ("off", "shadow", "advise")
DEFAULT_MODELS = {"claude": "claude-opus-5-5", "ollama": "nimble"}
DEFAULT_OLLAMA_URL = "http://localhost:11434/v1/systemone"


class DecisionError(Exception):
    pass


# --------------------------------------------------------------------------- definitions

def load_definitions(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise DecisionError("cannot read %s: %s" % (path, exc))


def validate_definitions(definitions):
    problems = []
    for name, decision in sorted((definitions.get("decisions") or {}).items()):
        for qid, question in sorted((decision.get("questions") or {}).items()):
            kind = question.get("type")
            where = "%s.%s" % (name, qid)
            if kind not in ("choice", "score", "yesno"):
                problems.append("%s: type must be choice, score or yesno" % where)
            if not question.get("instructions"):
                problems.append("%s: instructions are required (the model never sees the id)" % where)
            if kind == "choice" and len(question.get("options") or {}) < 2:
                problems.append("%s: a choice needs at least two options" % where)
            if kind == "score" and len(question.get("legend") or {}) < 2:
                problems.append("%s: a score needs a legend with at least two rungs" % where)
    return problems


# --------------------------------------------------------------------------- providers

def _clamp(value, low=0.0, high=1.0):
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


def normalise(questions, raw):
    """Validate provider output against the declared questions; raise on anything off-schema."""
    if not isinstance(raw, dict):
        raise DecisionError("provider returned %s, expected an object" % type(raw).__name__)
    answers = {}
    for qid, question in questions.items():
        item = raw.get(qid)
        if not isinstance(item, dict):
            raise DecisionError("no answer for question %s" % qid)
        kind = question["type"]
        if kind == "choice":
            if item.get("choice") not in question["options"]:
                raise DecisionError("%s: %r is not one of the declared options" % (qid, item.get("choice")))
            answers[qid] = {"type": kind, "choice": item["choice"], "confidence": _clamp(item.get("confidence"))}
            if isinstance(item.get("probabilities"), dict):
                answers[qid]["probabilities"] = {k: _clamp(v) for k, v in item["probabilities"].items()
                                                 if k in question["options"]}
        elif kind == "score":
            top = len(question["legend"]) - 1
            answers[qid] = {"type": kind, "score": _clamp(item.get("score"), 0, top),
                            "confidence": _clamp(item.get("confidence"))}
        else:
            answers[qid] = {"type": kind, "p": _clamp(item.get("p"))}
    return answers


def ask_command(command, name, state, questions, timeout):
    if not command:
        raise DecisionError("HARNESS_DECISION_CMD is empty")
    payload = json.dumps({"decision": name, "state": state, "questions": questions})
    try:
        result = subprocess.run(shlex.split(command), input=payload, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DecisionError("decision command failed: %s" % exc)
    if result.returncode != 0:
        raise DecisionError("decision command exited %d: %s" % (result.returncode, result.stderr.strip()[:200]))
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise DecisionError("decision command printed invalid JSON")


def _answer_schema(questions):
    properties = {}
    for qid, question in questions.items():
        if question["type"] == "choice":
            fields = {"choice": {"type": "string", "enum": sorted(question["options"])},
                      "confidence": {"type": "number"}}
        elif question["type"] == "score":
            fields = {"score": {"type": "number"}, "confidence": {"type": "number"}}
        else:
            fields = {"p": {"type": "number"}}
        properties[qid] = {"type": "object", "properties": fields, "required": sorted(fields),
                           "additionalProperties": False}
    return {"type": "object", "properties": properties, "required": sorted(properties), "additionalProperties": False}


def _question_text(questions):
    lines = []
    for qid, question in questions.items():
        lines.append("Question %s (%s): %s" % (qid, question["type"], question["instructions"]))
        for key, label in sorted((question.get("options") or {}).items()):
            lines.append("  option %s: %s" % (key, label))
        for key, label in sorted((question.get("legend") or {}).items()):
            lines.append("  rung %s: %s" % (key, label))
        if question["type"] == "yesno":
            lines.append("  answer p = probability (0-1) that the statement is true")
    return "\n".join(lines)


SYSTEM = ("You are a decision function inside a software project's commit and review tooling. Answer every "
          "question only from the given state. Do not explain. For a choice, pick one declared option and give "
          "your confidence (0-1) that it is right; for a score, a number on the declared scale and a confidence; "
          "for yes/no, the probability (0-1) that the statement is true. Report real uncertainty: a close call "
          "must get a low confidence.")


CLAUDE_URL = "https://api.anthropic.com/v1/messages"


def ask_claude(model, name, state, questions, timeout):
    """Claude Messages API over plain HTTPS (standard library only, no SDK to install).

    Auth: ANTHROPIC_API_KEY (x-api-key), else ANTHROPIC_AUTH_TOKEN (OAuth bearer).
    ANTHROPIC_BASE_URL overrides the endpoint host (e.g. a proxy).
    """
    import socket
    import urllib.error
    import urllib.request

    api_key, auth_token = os.environ.get("ANTHROPIC_API_KEY"), os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not api_key and not auth_token:
        raise DecisionError("provider claude needs ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) in the environment")
    betas = ["server-side-fallback-2026-07-01"]
    headers = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
    if api_key:
        headers["x-api-key"] = api_key
    else:
        headers["authorization"] = "Bearer %s" % auth_token
        betas.append("oauth-2025-04-20")
    headers["anthropic-beta"] = ",".join(betas)
    content = "Decision: %s\n\nState:\n%s\n\n%s" % (name, json.dumps(state, indent=1, sort_keys=True),
                                                    _question_text(questions))
    body = {
        "model": model,
        "max_tokens": 4000,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": content}],
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": _answer_schema(questions)}},
        "fallbacks": "default",
    }
    base = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    url = base + "/v1/messages" if base else CLAUDE_URL
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            response = json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except (ValueError, OSError):
            detail = ""
        raise DecisionError("Claude API error %s%s" % (exc.code, ": " + detail[:200] if detail else ""))
    except (socket.timeout, TimeoutError):
        raise DecisionError("Claude request timed out after %ss" % timeout)
    except urllib.error.URLError as exc:
        raise DecisionError("cannot reach the Claude API (%s)" % exc.reason)
    except ValueError:
        raise DecisionError("Claude API returned invalid JSON")
    if response.get("stop_reason") == "refusal":
        raise DecisionError("Claude declined the request")
    text = next((block.get("text") for block in response.get("content") or []
                 if isinstance(block, dict) and block.get("type") == "text"), None)
    if text is None:
        raise DecisionError("Claude returned no answer (stop reason %s)" % response.get("stop_reason"))
    try:
        return json.loads(text)
    except ValueError:
        raise DecisionError("Claude returned invalid JSON")


def ask_ollama(url, model, name, state, questions, timeout):
    """Local Jev-style decision endpoint (Ollama /v1/systemone). Standard library only."""
    import socket
    import urllib.error
    import urllib.request

    built = {}
    for qid, question in questions.items():
        if question["type"] == "choice":
            built[qid] = {"type": "choice", "instructions": question["instructions"], "criteria": question["options"]}
        elif question["type"] == "score":
            rungs = [question["legend"][key] for key in sorted(question["legend"], key=lambda k: int(k))]
            built[qid] = {"type": "score", "instructions": question["instructions"], "criteria": rungs}
        else:
            built[qid] = {"type": "noul", "instructions": question["instructions"]}
    body = json.dumps({"model": model, "state": state, "questions": built}).encode("utf-8")
    request = urllib.request.Request(url or DEFAULT_OLLAMA_URL, data=body,
                                     headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            response = json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise DecisionError("decision endpoint error %s" % exc.code)
    except (socket.timeout, TimeoutError):
        raise DecisionError("decision endpoint timed out after %ss" % timeout)
    except urllib.error.URLError as exc:
        raise DecisionError("cannot reach the decision endpoint (%s); is Ollama running?" % exc.reason)
    except ValueError:
        raise DecisionError("decision endpoint returned invalid JSON")
    answers = response.get("answers") if isinstance(response, dict) else None
    if not isinstance(answers, dict):
        raise DecisionError("decision endpoint returned no answers")
    raw = {}
    for qid, question in questions.items():
        item = answers.get(qid) or {}
        if question["type"] == "choice":
            raw[qid] = {"choice": item.get("choice"), "confidence": item.get("confidence"),
                        "probabilities": item.get("probabilities")}
        elif question["type"] == "score":
            raw[qid] = {"score": item.get("score"), "confidence": item.get("confidence")}
        else:
            raw[qid] = {"p": item.get("noul", item.get("p"))}
    return raw


def ask_jev(model, name, state, questions, timeout):
    """Unverified: written from TypeSafe's published SDK examples (TypeSafeClient.system_one)."""
    try:
        from typesafe_sdk import Choice, Noul, Score, TypeSafeClient
    except ImportError:
        raise DecisionError("provider jev needs the typesafe-sdk package")
    if not model:
        raise DecisionError("provider jev needs HARNESS_DECISION_MODEL (pin the Jev version)")
    built = {}
    for qid, question in questions.items():
        if question["type"] == "choice":
            built[qid] = Choice(instructions=question["instructions"], criteria=question["options"])
        elif question["type"] == "score":
            built[qid] = Score(instructions=question["instructions"], legend=question["legend"])
        else:
            built[qid] = Noul(instructions=question["instructions"])
    try:
        with TypeSafeClient(model=model) as client:
            result = client.system_one(state=state, questions=built)
    except Exception as exc:  # unknown SDK surface: never let it break the hook
        raise DecisionError("Jev call failed: %s" % exc)
    raw = {}
    for qid, question in questions.items():
        if question["type"] == "choice":
            answer = result.choices[qid]
            raw[qid] = {"choice": answer.choice, "confidence": answer.confidence,
                        "probabilities": dict(getattr(answer, "probabilities", {}) or {})}
        elif question["type"] == "score":
            answer = result.scores[qid]
            raw[qid] = {"score": answer.score, "confidence": answer.confidence}
        else:
            raw[qid] = {"p": result.nouls[qid].p}
    return raw


# --------------------------------------------------------------------------- decide, advise, log

def advice(questions, answers):
    """Messages for answers that cross their declared warn_if thresholds."""
    notes = []
    for qid, question in questions.items():
        rule, answer = question.get("warn_if"), answers.get(qid)
        if not rule or not answer:
            continue
        if answer["type"] == "choice" and answer["choice"] in rule.get("choices", []):
            probability = (answer.get("probabilities") or {}).get(answer["choice"])
            confident = answer["confidence"] >= rule.get("min_confidence", 0)
            likely = probability is not None and "min_probability" in rule and probability >= rule["min_probability"]
            if confident or likely:
                notes.append(rule.get("message", "%s: %s" % (qid, answer["choice"])))
        elif answer["type"] == "score" and answer["score"] >= rule.get("min_score", float("inf")) \
                and answer["confidence"] >= rule.get("min_confidence", 0):
            notes.append(rule.get("message", "%s: %.2f" % (qid, answer["score"])))
        elif answer["type"] == "yesno" and answer["p"] >= rule.get("min_p", float("inf")):
            notes.append(rule.get("message", "%s: p=%.2f" % (qid, answer["p"])))
    return notes


def decide(name, state, definitions, values, log_path):
    """Run one decision if configured. Returns (answers or None, advice list). Never raises."""
    provider, mode = values.get("HARNESS_DECISION_PROVIDER", "none"), values.get("HARNESS_DECISION_MODE", "off")
    decision = (definitions.get("decisions") or {}).get(name)
    if provider == "none" or mode == "off" or decision is None:
        return None, []
    questions = decision["questions"]
    model = values.get("HARNESS_DECISION_MODEL") or DEFAULT_MODELS.get(provider, "")
    timeout = float(values.get("HARNESS_DECISION_TIMEOUT") or 20)
    started = time.time()
    answers, error, notes = None, None, []
    try:
        if provider == "command":
            raw = ask_command(values.get("HARNESS_DECISION_CMD", ""), name, state, questions, timeout)
        elif provider == "ollama":
            raw = ask_ollama(values.get("HARNESS_DECISION_URL", ""), model, name, state, questions, timeout)
        elif provider == "claude":
            raw = ask_claude(model, name, state, questions, timeout)
        elif provider == "jev":
            raw = ask_jev(model, name, state, questions, timeout)
        else:
            raise DecisionError("unknown provider %s" % provider)
        answers = normalise(questions, raw)
        notes = advice(questions, answers)
    except DecisionError as exc:
        error = str(exc)
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "decision": name,
        "definitions_version": definitions.get("version"), "provider": provider, "model": model, "mode": mode,
        "latency_ms": int((time.time() - started) * 1000),
        "state_sha256": hashlib.sha256(json.dumps(state, sort_keys=True).encode("utf-8")).hexdigest(),
        "state": state, "questions": questions, "answers": answers, "advice": notes, "error": error,
    }
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError:
        pass
    return answers, (notes if mode == "advise" else [])


def report(log_path, last=10):
    try:
        with open(log_path, encoding="utf-8") as handle:
            entries = [json.loads(line) for line in handle if line.strip()]
    except (OSError, ValueError):
        entries = []
    if not entries:
        return "No decisions logged yet (%s)." % log_path
    lines = []
    for name in sorted({e["decision"] for e in entries}):
        rows = [e for e in entries if e["decision"] == name]
        ok = [e for e in rows if not e.get("error")]
        lines.append("%s: %d call(s), %d error(s), %d with advice, median latency %d ms"
                     % (name, len(rows), len(rows) - len(ok), sum(1 for e in ok if e.get("advice")),
                        sorted(e["latency_ms"] for e in rows)[len(rows) // 2]))
        for qid in sorted((ok[-1]["answers"] if ok else {}) or {}):
            answers = [e["answers"][qid] for e in ok if qid in (e.get("answers") or {})]
            if answers and answers[0]["type"] == "choice":
                counts = {}
                for a in answers:
                    counts[a["choice"]] = counts.get(a["choice"], 0) + 1
                low = sum(1 for a in answers if a["confidence"] < 0.5)
                lines.append("  %s: %s; %d low-confidence" % (qid, ", ".join("%s=%d" % kv for kv in sorted(counts.items())), low))
            elif answers and answers[0]["type"] == "yesno":
                lines.append("  %s: mean p=%.2f, %d >= 0.5" % (qid, sum(a["p"] for a in answers) / len(answers),
                                                             sum(1 for a in answers if a["p"] >= 0.5)))
            elif answers:
                lines.append("  %s: mean score=%.2f" % (qid, sum(a["score"] for a in answers) / len(answers)))
    lines.append("\nLast %d:" % min(last, len(entries)))
    for e in entries[-last:]:
        summary = e.get("error") or "; ".join("%s=%s" % (q, a.get("choice", a.get("p", a.get("score"))))
                                             for q, a in sorted((e.get("answers") or {}).items()))
        lines.append("  %s %s [%s/%s] %s%s" % (e["at"], e["decision"], e["provider"], e["mode"], summary,
                                             "  -> advice" if e.get("advice") else ""))
    return "\n".join(lines)
