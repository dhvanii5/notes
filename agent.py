#!/usr/bin/env python3
"""
Minimal AI coding agent.

Usage:
    export GROQ_API_KEY=gsk_...
    python agent.py --repo ./node-easy-notes-app \
        --task "Improve the application so users can better organise and search their notes."

The agent explores the given repo with read-only tools, writes a short plan,
then uses write_file to implement the change, and finally prints/saves a summary.
All file access is sandboxed to the repo path.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from groq import Groq

DEFAULT_MODEL = "llama-3.1-8b-instant"  # smaller model, separate/higher daily quota than 70b
MAX_TURNS = 40  # hard cap so the loop can't run forever
MAX_RETRIES_PER_TURN = 3

SYSTEM_PROMPT = """You are a senior software engineer acting as an autonomous coding agent.

You will be given a path to an existing code repository and a single, high-level
product request. You must:

1. EXPLORE the repository using list_dir / read_file / search_code before writing
   any code. Do not assume file names or structure — verify them.
2. Once you understand the codebase, output a short PLAN as plain text (5-10 bullet
   points max): what you will build, which files you will touch/create, and why this
   is the right scope for the request. Do this BEFORE calling write_file.
3. Implement the plan using write_file. Make minimal, targeted edits. Preserve all
   existing functionality (existing endpoints/behavior must keep working).
4. Write the PLAN to a file named PLAN.md (via write_file) in addition to stating it,
   BEFORE you make any other edits.
5. Implement the plan using write_file. Make minimal, targeted edits. Preserve all
   existing functionality (existing endpoints/behavior must keep working).
6. VERIFY your own work: use run_command to (a) syntax-check any changed JS file with
   `node -c <file>`, (b) start the server in the background
   (`node server.js > /tmp/server.log 2>&1 & sleep 2`), (c) use curl to exercise the
   NEW functionality you added, and (d) use curl to confirm the PRE-EXISTING endpoints
   (create/list/get/update/delete) still respond correctly, unchanged. Include the raw
   curl output as evidence. If anything fails, fix it and re-verify before finishing.
7. Write a SUMMARY to a file named CHANGES.md (via write_file): what changed, new
   endpoints/fields, the curl evidence from step 6, and any assumptions/trade-offs.
   Also state the SUMMARY as plain text in your final reply.

Rules:
- Never invent APIs or files that don't exist without first checking.
- Keep changes idiomatic to the existing codebase's language/framework/style.
- If the request is ambiguous, pick the most reasonable, minimal-scope interpretation
  and state that assumption explicitly in your PLAN and SUMMARY rather than asking
  the user (no user is available to answer follow-up questions).
- Do not rewrite the project in a different language or framework.
- Do not consider the task done until step 6's verification has actually passed.
- CRITICAL: NEVER fabricate, guess, or invent a tool's output. Only ever report what a
  tool call actually returned. If a run_command call returns an ERROR, you must say so
  explicitly in your PLAN/SUMMARY/CHANGES.md — do not write a fake success result. If
  verification keeps failing after a couple of fix attempts, report the failure
  honestly as a known limitation rather than claiming it passed.
- When writing CHANGES.md, copy the ACTUAL text returned by your last successful (or
  failed) run_command/curl calls verbatim — do not paraphrase or reconstruct output
  from memory.
- IMPORTANT: all tool paths are ALREADY relative to the repository root. Use "." for
  the root itself (e.g. list_dir(".")). Never prefix paths with the repo's own folder
  name or a "../" segment — the sandbox handles that internally.
- Call exactly one tool at a time, with valid JSON arguments matching the tool's schema.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and folders under a directory (relative to repo root), recursively up to 3 levels.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative path, e.g. '.' or 'app'"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full contents of a file (relative to repo root).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search the repo for a regex/text pattern (like grep -rn), returns matching file:line:text.",
            "parameters": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}},
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file or overwrite an existing file (relative to repo root) with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a whitelisted, read-only sanity-check command inside the repo (e.g. 'node -c server.js', 'ls -R app'). No network or package installs.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]

ALLOWED_COMMANDS_PREFIXES = (
    "node -c ", "ls", "find", "cat", "wc",
    "curl", "node server.js", "pkill -f server.js", "sleep",
)


import shutil

def _resolve_bash() -> str:
    """On Windows, plain 'bash' can resolve to the WSL launcher shim in System32
    instead of Git Bash's real bash.exe, which fails with no WSL distro installed.
    Prefer Git Bash's actual binary if present."""
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        shutil.which("bash"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return "bash"

BASH = _resolve_bash()


class Sandbox:
    def __init__(self, repo_root: Path):
        self.root = repo_root.resolve()

    def _resolve(self, rel_path: str) -> Path:
        p = (self.root / rel_path).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError(f"Path escapes repo sandbox: {rel_path}")
        return p

    def list_dir(self, rel_path: str) -> str:
        base = self._resolve(rel_path)
        lines = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
            depth = len(Path(dirpath).relative_to(base).parts)
            if depth > 2:
                dirnames[:] = []
                continue
            rel = Path(dirpath).relative_to(self.root)
            for f in sorted(filenames):
                lines.append(str(rel / f))
        return "\n".join(lines) or "(empty)"

    def read_file(self, rel_path: str) -> str:
        p = self._resolve(rel_path)
        if not p.exists():
            return f"ERROR: {rel_path} does not exist"
        return p.read_text(errors="replace")

    def write_file(self, rel_path: str, content: str) -> str:
        p = self._resolve(rel_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"Wrote {len(content)} bytes to {rel_path}"

    def search_code(self, pattern: str) -> str:
        try:
            out = subprocess.run(
                ["grep", "-rn", "--include=*.js", "--exclude-dir=node_modules",
                 "--exclude-dir=.git", "-E", pattern, str(self.root)],
                capture_output=True, text=True, timeout=15,
            )
            result = out.stdout.strip()
            return result.replace(str(self.root) + "/", "") if result else "No matches"
        except subprocess.TimeoutExpired:
            return "ERROR: search timed out after 15s (try a more specific pattern)"
        except Exception as e:
            return f"ERROR: {e}"

    def run_command(self, command: str) -> str:
        if not command.startswith(ALLOWED_COMMANDS_PREFIXES):
            return "ERROR: command not permitted by sandbox whitelist"
        try:
            # Backgrounded commands (server start) must not be waited on, or they hang forever.
            if command.rstrip().endswith("&") or " & " in command:
                subprocess.Popen(
                    [BASH, "-c", command], cwd=self.root,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return "Started in background (not waited on). Give it a couple seconds before curling it."
            out = subprocess.run(
                [BASH, "-c", command], cwd=self.root,
                capture_output=True, text=True, timeout=15,
            )
            return (out.stdout + out.stderr).strip() or "(no output, exit 0)"
        except subprocess.TimeoutExpired:
            return "ERROR: command timed out after 15s"
        except Exception as e:
            return f"ERROR: {e}"


MAX_TOOL_RESULT_CHARS = 2500  # keep conversation small enough for free-tier TPM limits


def execute_tool(sandbox: Sandbox, name: str, tool_input: dict) -> str:
    try:
        if name == "list_dir":
            return sandbox.list_dir(tool_input["path"])
        if name == "read_file":
            return sandbox.read_file(tool_input["path"])
        if name == "write_file":
            return sandbox.write_file(tool_input["path"], tool_input["content"])
        if name == "search_code":
            return sandbox.search_code(tool_input["pattern"])
        if name == "run_command":
            return sandbox.run_command(tool_input["command"])
        return f"ERROR: unknown tool {name}"
    except Exception as e:
        return f"ERROR: {e}"


def run_agent(repo_path: str, task: str, model: str, fallback_model: str | None):
    sandbox = Sandbox(Path(repo_path))
    client = Groq()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content":
            f"Repository root: {repo_path}\n\nProduct request:\n{task}"},
    ]

    transcript_log = []

    for turn in range(MAX_TURNS):
        response = None
        last_err = None
        for attempt in range(MAX_RETRIES_PER_TURN):
            use_fallback = fallback_model and attempt == MAX_RETRIES_PER_TURN - 1
            model_to_use = fallback_model if use_fallback else model
            try:
                response = client.chat.completions.create(
                    model=model_to_use,
                    max_tokens=4096,
                    tools=TOOLS,
                    messages=messages,
                )
                break
            except Exception as e:
                last_err = e
                err_str = str(e)
                if "rate_limit_exceeded" in err_str or "429" in err_str:
                    print(f"FATAL: rate limit hit on model={model_to_use}. "
                          f"Not retrying (won't help immediately) — "
                          f"switch --model to a different one or wait as the error suggests.\n{e}")
                    response = None
                    break
                print(f"[warn] generation failed on attempt {attempt + 1} "
                      f"(model={model_to_use}): {e}\nRetrying...")
        if response is None:
            print(f"FATAL: stopping run. Last error: {last_err}")
            break

        msg = response.choices[0].message

        if msg.content and msg.content.strip():
            print("\n--- AGENT ---\n" + msg.content)
            transcript_log.append("AGENT:\n" + msg.content)

        if not msg.tool_calls:
            break

        # Append the assistant's own message (with tool_calls) back into history
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            import json
            try:
                tool_input = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                tool_input = {}
            print(f"\n[tool] {tc.function.name}({tool_input})")
            result = execute_tool(sandbox, tc.function.name, tool_input)
            preview = result if len(result) < 400 else result[:400] + " ...(truncated)"
            print(f"[result] {preview}")
            transcript_log.append(f"TOOL {tc.function.name}({tool_input}) -> {preview}")
            result_for_model = (
                result if len(result) <= MAX_TOOL_RESULT_CHARS
                else result[:MAX_TOOL_RESULT_CHARS] + "\n...(truncated to save context, "
                     "re-read a narrower range or specific section if you need more)"
            )
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_for_model,
            })
    else:
        print("WARNING: hit MAX_TURNS without a natural stop.")

    Path(repo_path, "AGENT_LOG.md").write_text("\n\n".join(transcript_log))
    print("\nDone. Full trace saved to AGENT_LOG.md inside the repo.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, help="Path to the local clone of the target repo")
    parser.add_argument("--task", required=True, help="The single product request")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Groq model id to use")
    parser.add_argument("--fallback-model", default=None,
                         help="Optional Groq model id to try if --model keeps emitting malformed tool calls")
    args = parser.parse_args()

    if not os.environ.get("GROQ_API_KEY"):
        sys.exit("Set GROQ_API_KEY first.")

    run_agent(args.repo, args.task, args.model, args.fallback_model)