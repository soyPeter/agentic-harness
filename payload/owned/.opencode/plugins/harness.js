// Agentic harness: OpenCode adapter (harness-owned).
// Sends every OpenCode tool call through the harness hooks (scripts/harness/lib/harness.py --from opencode), so the
// same gates apply as in Claude Code and Codex. A refused call throws, which OpenCode turns into a tool error.
// It also records the griller's and judge's verdicts from the result of the subagent tool, and gives each session the
// session-start context, which OpenCode has no hook for. OpenCode 2 and 1.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const SCRIPT = "scripts/harness/lib/harness.py";
const LAUNCHER = join(dirname(fileURLToPath(import.meta.url)), "../../../../plugin/launcher.py");
const NAMES = { shell: "Bash", bash: "Bash", edit: "Edit", write: "Write", read: "Read", skill: "Skill",
  patch: "apply_patch", apply_patch: "apply_patch" };
const VERDICT_AGENTS = new Set(["griller", "judge", "tester", "debugger", "reviewer", "deliverer"]);

function projectRoot(start) {
  const startDir = start || process.cwd();
  const top = spawnSync("git", ["-C", startDir, "rev-parse", "--show-toplevel"], { encoding: "utf8" });
  if (top.status === 0) return top.stdout.trim();
  let dir = startDir;
  for (;;) {
    if (existsSync(join(dir, SCRIPT))) return dir;
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

function translate(tool, input) {
  const args = input || {};
  const knowledge = /^knowledge[_:]+/.test(tool || "");
  const name = NAMES[tool] || (knowledge ? "mcp__knowledge__" + tool.replace(/^knowledge[_:]+/, "") : tool);
  const path = args.path || args.filePath;
  switch (name) {
    case "Bash": return [name, { command: args.command || "" }];
    case "Edit": return [name, { file_path: path, old_string: args.oldString || "", new_string: args.newString || "",
      replace_all: Boolean(args.replaceAll) }];
    case "Write": return [name, { file_path: path, content: args.content || "" }];
    case "Read": return [name, { file_path: path }];
    case "Skill": return [name, { skill: args.name || args.skill || "" }];
    case "apply_patch": return [name, { command: args.patchText || args.patch || "" }];
    default: return [name, args];
  }
}

function hook(root, event, payload) {
  const script = existsSync(join(root, SCRIPT)) ? join(root, SCRIPT) : LAUNCHER;
  return spawnSync("python3", [script, "hook", event, "--from", "opencode"],
    { input: JSON.stringify(payload), encoding: "utf8", cwd: root, timeout: event === "subagent-stop" ? 1200000 : 30000 });
}

function resultText(result) {
  if (result == null) return "";
  if (typeof result === "string") return result;
  return result.output ?? result.info?.output ?? result.text ?? JSON.stringify(result);
}

async function before(event) {
  const root = projectRoot(event.cwd);
  if (!root) return;
  const [name, input] = translate(event.tool, event.input);
  const run = hook(root, "pre-tool-use", { tool_name: name, tool_input: input, session_id: event.sessionID,
    agent_type: event.agent, cwd: root });
  // Fail closed: a refusal (exit 2), a crash, a timeout or a missing python3 all stop the call.
  if (run.error || run.signal || run.status !== 0) {
    throw new Error((run.stderr || "").trim() || "The harness hook could not check this call, so it is refused.");
  }
}

async function after(event) {
  const root = projectRoot(event.cwd);
  if (!root) return;
  const agent = event.input?.agent;
  if (event.tool === "subagent" && VERDICT_AGENTS.has(agent) && event.status !== "error") {
    hook(root, "subagent-stop", { agent_type: agent, session_id: event.sessionID, stop_hook_active: true,
      last_assistant_message: resultText(event.result) });
    return;
  }
  const [name, input] = translate(event.tool, event.input);
  hook(root, "post-tool-use", { tool_name: name, tool_input: input, session_id: event.sessionID,
    agent_type: event.agent, cwd: root });
}

// The session-start hook scans the project, so it runs once per session. Context changes don't persist between model
// requests, so the text is added to every request.
const SESSION_CONTEXT = new Map();

function sessionContext(start, sessionID) {
  const root = projectRoot(start);
  if (!root) return "";
  const key = sessionID || root;
  if (!SESSION_CONTEXT.has(key)) {
    const run = hook(root, "session-start", { session_id: sessionID, cwd: root });
    if (run.error || run.signal || run.status !== 0) return "";
    let text = (run.stdout || "").trim();
    try {
      text = JSON.parse(text).hookSpecificOutput.additionalContext ?? text;
    } catch {}
    SESSION_CONTEXT.set(key, text);
  }
  return SESSION_CONTEXT.get(key);
}

async function setup(ctx) {
  if (!ctx || typeof ctx.tool?.hook !== "function") return async () => {};
  const a = await ctx.tool.hook("execute.before", before);
  const b = await ctx.tool.hook("execute.after", after);
  const c = typeof ctx.session?.hook === "function"
    ? await ctx.session.hook("context", (event) => {
      const text = sessionContext(ctx.directory || ctx.worktree, event.sessionID);
      if (text) event.system.push({ type: "text", text });
    })
    : null;
  return async () => { await a?.dispose?.(); await b?.dispose?.(); await c?.dispose?.(); };
}

// OpenCode 1: a callable returning event hooks.
async function server(ctx) {
  return {
    "experimental.chat.system.transform": async (input, output) => {
      const text = sessionContext(ctx?.directory || ctx?.worktree, input?.sessionID);
      if (text) output.system.push(text);
    },
    "tool.execute.before": async (input, output) =>
      before({ tool: input.tool, input: output?.args, sessionID: input.sessionID, agent: input.agent }),
    "tool.execute.after": async (input, output) =>
      after({ tool: input.tool, input: input.args ?? output?.args, sessionID: input.sessionID, agent: input.agent,
        result: output, status: "completed" }),
  };
}

export default process.env.HARNESS_OPENCODE_PLUGIN_API === "v1" ? server : { id: "agentic-harness", server, setup };
