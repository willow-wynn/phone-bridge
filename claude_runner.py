import json
import logging
import os
import subprocess
from dataclasses import dataclass

logger = logging.getLogger("phone-bridge.claude")


@dataclass
class ClaudeResult:
    text: str
    session_id: str
    cost_usd: float = 0.0
    duration_ms: int = 0
    is_error: bool = False


class ClaudeRunner:
    def __init__(
        self,
        working_dir: str,
        allowed_tools: str,
        max_timeout: int,
        max_budget_usd: float,
    ):
        self.working_dir = working_dir
        self.allowed_tools = allowed_tools
        self.max_timeout = max_timeout
        self.max_budget_usd = max_budget_usd

    def run(self, prompt: str, session_id: str | None = None) -> ClaudeResult:
        cmd = ["claude", "-p", prompt, "--output-format", "json"]

        if session_id:
            cmd.extend(["--resume", session_id])

        if self.allowed_tools:
            cmd.extend(["--allowedTools", self.allowed_tools])

        if self.max_budget_usd > 0:
            cmd.extend(["--max-budget-usd", str(self.max_budget_usd)])

        logger.info(f"Running claude in {self.working_dir} (session={session_id or 'new'})")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.max_timeout,
                cwd=self.working_dir,
                env={**os.environ},
            )
        except subprocess.TimeoutExpired:
            logger.warning(f"Claude timed out after {self.max_timeout}s")
            return ClaudeResult(
                text=f"Request timed out after {self.max_timeout}s. Try a simpler question or increase CLAUDE_MAX_TIMEOUT.",
                session_id=session_id or "",
                is_error=True,
            )

        if proc.returncode != 0:
            logger.error(f"Claude exited with code {proc.returncode}: {proc.stderr[:500]}")
            return ClaudeResult(
                text=f"Claude error (exit {proc.returncode}): {proc.stderr[:300]}",
                session_id=session_id or "",
                is_error=True,
            )

        try:
            items = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Claude JSON output: {e}")
            logger.error(f"Raw stdout (first 500 chars): {proc.stdout[:500]}")
            return ClaudeResult(
                text="Error: Could not parse Claude's response.",
                session_id=session_id or "",
                is_error=True,
            )

        # Extract the result object (last item with type="result")
        result_obj = None
        for item in reversed(items):
            if item.get("type") == "result":
                result_obj = item
                break

        if not result_obj:
            logger.error("No result object found in Claude output")
            return ClaudeResult(
                text="Error: No result in Claude's response.",
                session_id=session_id or "",
                is_error=True,
            )

        text = result_obj.get("result", "")
        if not text:
            # Fall back to extracting text from assistant message
            for item in items:
                if item.get("type") == "assistant":
                    content = item.get("message", {}).get("content", [])
                    text = "".join(
                        block.get("text", "") for block in content if block.get("type") == "text"
                    )
                    break

        if not text:
            text = "(Claude returned an empty response)"

        return ClaudeResult(
            text=text,
            session_id=result_obj.get("session_id", session_id or ""),
            cost_usd=result_obj.get("total_cost_usd", 0),
            duration_ms=result_obj.get("duration_ms", 0),
            is_error=result_obj.get("is_error", False),
        )
