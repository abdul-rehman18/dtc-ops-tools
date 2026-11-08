"""Claude writes the words. Code supplies the numbers.

Claude is given fact ids and must write every number as a placeholder like {{f012}}.
The output is rejected if it contains any digit outside a placeholder, or a placeholder
that is not in the ledger, or leaves out a fact it was told must appear.
If Claude fails the check twice, the tool falls back to a plain template so the brief
still goes out, and says so.
"""
from __future__ import annotations

import json
import os
import re

PLACEHOLDER = re.compile(r"\{\{(f\d{3})\}\}")
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")


def check_grounded(text: str, allowed_ids: set[str], required_ids: set[str] = frozenset()) -> list[str]:
    problems = []
    used = set(PLACEHOLDER.findall(text))
    unknown = used - allowed_ids
    if unknown:
        problems.append(f"uses facts that do not exist: {sorted(unknown)}")
    missing = set(required_ids) - used
    if missing:
        problems.append(f"leaves out required facts: {sorted(missing)}")
    stripped = PLACEHOLDER.sub("", text)
    stray = re.findall(r"\d[\d,.]*", stripped)
    if stray:
        problems.append(f"contains numbers Claude typed itself: {stray[:5]}")
    return problems


def render(text: str, ledger) -> str:
    return PLACEHOLDER.sub(lambda m: ledger.facts[m.group(1)].display(), text)


class ClaudeWriter:
    """Thin wrapper over the Messages API. Pass a fake `call` in tests."""

    def __init__(self, call=None, model: str = DEFAULT_MODEL, max_tokens: int = 4000):
        self.model = model
        self.max_tokens = max_tokens
        self.last_stop_reason = None
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
        if call is not None:
            self._call = call
        elif os.environ.get("ANTHROPIC_API_KEY"):
            import anthropic  # imported here so tests and --no-llm runs do not need it

            client = anthropic.Anthropic()

            def _call(system, user):
                msg = client.messages.create(
                    model=self.model, max_tokens=self.max_tokens, system=system,
                    messages=[{"role": "user", "content": user}],
                )
                self.last_stop_reason = msg.stop_reason
                self.usage["input_tokens"] += msg.usage.input_tokens
                self.usage["output_tokens"] += msg.usage.output_tokens
                return "".join(b.text for b in msg.content if b.type == "text")

            self._call = _call
        else:
            self._call = None

    @property
    def available(self) -> bool:
        return self._call is not None

    def write_items(self, system: str, user: str, allowed: set[str], required: set[str], attempts: int = 2):
        """Returns (items, log). items is None if Claude could not produce a grounded answer."""
        log = []
        prompt = user
        for attempt in range(1, attempts + 1):
            self.usage["calls"] += 1
            raw = self._call(system, prompt)
            try:
                items = parse_json_reply(raw)["items"]
            except (ValueError, KeyError, TypeError) as e:
                log.append(f"attempt {attempt}: not valid JSON ({e})")
                prompt = user + "\n\nYour last answer was not valid JSON. Reply with JSON only."
                continue
            joined = "\n".join(f"{i.get('headline', '')}\n{i.get('body', '')}" for i in items)
            problems = check_grounded(joined, allowed, required)
            if not problems:
                log.append(f"attempt {attempt}: passed the grounding check")
                return items, log
            log.append(f"attempt {attempt}: rejected, " + "; ".join(problems))
            prompt = user + "\n\nYour last answer was rejected: " + "; ".join(problems) + \
                ". Write every number only as a {{fNNN}} placeholder."
        return None, log


def parse_json_reply(raw: str):
    """Parse Claude's JSON reply. Tolerates a code fence or a sentence around it. Raises ValueError if broken."""
    s = _strip_fence(raw)
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in the reply")
    return json.loads(s[start:end + 1])


def _strip_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1].rsplit("```", 1)[0]
    return s
