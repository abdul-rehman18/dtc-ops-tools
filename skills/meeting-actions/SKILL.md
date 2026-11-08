---
name: meeting-actions
description: Turn a meeting transcript into a checked list of who agreed to do what and by when, plus anything nobody took on. Use after the weekly ops call or when someone pastes or points to a transcript.
---

# Meeting action list

## When to use
"What did we agree on the call?", "send me the actions from Thursday", or a transcript file is shared.

## Steps
1. Call the `meeting_actions` tool from the `dtc-ops` MCP server. Pass the transcript path if one was given.
2. Show the result as returned: actions grouped by person, then "No owner yet", then ideas.
3. If the person wants to post it to Slack, keep the same three sections and wording.

## Rules
- Only list someone as an owner if the tool did. Do not move items out of "No owner yet" on your own.
- Do not add deadlines. Dates come from the tool, which works them out from what was said.
- If the tool says the transcript needs a person this week, say that plainly.

## Example
Person: "Who's doing the freight bill check?"
You: call `meeting_actions` and answer that nobody took it on, quoting the "No owner yet" item.
