import json
import logging
import os
import queue
import subprocess
import threading
from dataclasses import dataclass, field

logger = logging.getLogger("phone-bridge.claude")


@dataclass
class ToolEvent:
    """A tool call that Claude is making."""
    name: str
    summary: str


@dataclass
class ClaudeResult:
    text: str
    session_id: str
    cost_usd: float = 0.0
    duration_ms: int = 0
    is_error: bool = False
    stderr: str = ""
    tool_calls: list[str] = field(default_factory=list)


def _summarize_tool(name: str, input_data: dict) -> str:
    """Create a concise one-line summary of a tool call."""
    match name:
        case "Read":
            path = input_data.get("file_path", "?")
            return f"Reading {os.path.basename(path)}"
        case "Write":
            path = input_data.get("file_path", "?")
            return f"Writing {os.path.basename(path)}"
        case "Edit":
            path = input_data.get("file_path", "?")
            return f"Editing {os.path.basename(path)}"
        case "Bash":
            cmd = input_data.get("command", "?")
            return f"Running: {cmd[:60]}"
        case "Glob":
            pattern = input_data.get("pattern", "?")
            return f"Finding files: {pattern}"
        case "Grep":
            pattern = input_data.get("pattern", "?")
            return f"Searching: {pattern[:40]}"
        case "WebSearch":
            q = input_data.get("query", "?")
            return f"Web search: {q[:50]}"
        case "WebFetch":
            url = input_data.get("url", "?")
            return f"Fetching: {url[:50]}"
        case "NotebookEdit":
            path = input_data.get("notebook_path", "?")
            return f"Editing notebook: {os.path.basename(path)}"
        case "Task":
            desc = input_data.get("description", input_data.get("prompt", "?")[:40])
            return f"Agent: {desc}"
        case _:
            return f"{name}"


class ClaudeRunner:
    def __init__(
        self,
        working_dir: str,
        allowed_tools: str,
        max_timeout: int,
        max_budget_usd: float,
        system_prompt: str = "",
    ):
        self.working_dir = working_dir
        self.allowed_tools = allowed_tools
        self.max_timeout = max_timeout
        self.max_budget_usd = max_budget_usd
        self.system_prompt = system_prompt

    def _build_cmd(self, prompt: str, session_id: str | None, file_paths: list[str] | None, streaming: bool) -> list[str]:
        fmt = "stream-json" if streaming else "json"
        cmd = ["claude", "-p", prompt, "--output-format", fmt, "--verbose"]

        if file_paths:
            for path in file_paths:
                cmd.extend(["--add-dir", os.path.dirname(path)])

        if session_id:
            cmd.extend(["--resume", session_id])

        if self.allowed_tools:
            cmd.extend(["--allowedTools", self.allowed_tools])

        if self.max_budget_usd > 0:
            cmd.extend(["--max-budget-usd", str(self.max_budget_usd)])

        if self.system_prompt:
            cmd.extend(["--append-system-prompt", self.system_prompt])

        return cmd

    def run_streaming(
        self,
        prompt: str,
        session_id: str | None = None,
        file_paths: list[str] | None = None,
        event_queue: queue.Queue | None = None,
    ) -> ClaudeResult:
        """Run claude with stream-json, emitting ToolEvents to event_queue as they happen."""
        cmd = self._build_cmd(prompt, session_id, file_paths, streaming=True)
        logger.info(f"Running claude (streaming) in {self.working_dir} (session={session_id or 'new'})")

        tool_calls: list[str] = []
        result_obj = None
        final_session_id = session_id or ""
        stderr_output = ""

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.working_dir,
                env={**os.environ},
            )

            # Read stderr in background thread so it doesn't block
            stderr_parts = []
            def read_stderr():
                for line in proc.stderr:
                    stderr_parts.append(line)
            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stderr_thread.start()

            # Read stdout line by line
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")

                if event_type == "system" and event.get("subtype") == "init":
                    final_session_id = event.get("session_id", final_session_id)

                elif event_type == "assistant":
                    content = event.get("message", {}).get("content", [])
                    for block in content:
                        if block.get("type") == "tool_use":
                            name = block.get("name", "?")
                            input_data = block.get("input", {})
                            summary = _summarize_tool(name, input_data)
                            tool_calls.append(summary)
                            if event_queue:
                                event_queue.put(ToolEvent(name=name, summary=summary))

                elif event_type == "result":
                    result_obj = event
                    final_session_id = event.get("session_id", final_session_id)

            proc.wait(timeout=self.max_timeout)
            stderr_thread.join(timeout=5)
            stderr_output = "".join(stderr_parts)

        except subprocess.TimeoutExpired:
            proc.kill()
            logger.warning(f"Claude timed out after {self.max_timeout}s")
            return ClaudeResult(
                text=f"Request timed out after {self.max_timeout}s. Try a simpler question or increase CLAUDE_MAX_TIMEOUT.",
                session_id=final_session_id,
                is_error=True,
                tool_calls=tool_calls,
            )
        except Exception as e:
            logger.exception("Error running claude")
            return ClaudeResult(
                text=f"Error running Claude: {str(e)[:200]}",
                session_id=final_session_id,
                is_error=True,
                tool_calls=tool_calls,
            )

        if proc.returncode != 0:
            stderr_snippet = stderr_output.strip()[:500]
            logger.error(f"Claude exited with code {proc.returncode}: {stderr_snippet}")
            error_msg = f"Claude error (exit code {proc.returncode})"
            if stderr_snippet:
                error_msg += f":\n\n{stderr_snippet}"
            return ClaudeResult(
                text=error_msg,
                session_id=final_session_id,
                is_error=True,
                stderr=stderr_output,
                tool_calls=tool_calls,
            )

        if not result_obj:
            return ClaudeResult(
                text="Error: No result in Claude's response.",
                session_id=final_session_id,
                is_error=True,
                tool_calls=tool_calls,
            )

        text = result_obj.get("result", "")
        if not text:
            text = "(Claude returned an empty response)"

        return ClaudeResult(
            text=text,
            session_id=result_obj.get("session_id", final_session_id),
            cost_usd=result_obj.get("total_cost_usd", 0),
            duration_ms=result_obj.get("duration_ms", 0),
            is_error=result_obj.get("is_error", False),
            tool_calls=tool_calls,
        )

    def run(self, prompt: str, session_id: str | None = None, file_paths: list[str] | None = None) -> ClaudeResult:
        """Non-streaming fallback."""
        return self.run_streaming(prompt, session_id, file_paths)
