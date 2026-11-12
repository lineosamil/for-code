# Code Explorer reliability checklist

## What the HTML means
- **Observed**: a symbol declaration from a real line; Python AST call edges for names matching local or explicitly imported symbols.
- **Candidate**: regex-detected non-Python functions, entrypoint heuristics, import hints and inferred roles.
- **Not established**: actual runtime order, asynchronous scheduling, reflective dispatch, coverage, race conditions, side effects, performance, absence of bugs, full dynamic feature graph.

## Before analysis
- Ensure repository root is correct, do not execute untrusted programs by default.
- Identify true UI/API/CLI entrypoints by reading representative files and app configuration.
- Exclude secrets and sensitive configuration. `--no-code` when HTML might leave a trusted machine.
- If repository has uncommitted changes, warn before edit and retain user's work.

## HTML QA after generation
- The script created ONE project output: `code-explorer.html`, no companion `.css`, `.js`, `.json`, `.md` or directory.
- No external CDN or `fetch`/network usage. HTML works with `file://` when opened on the same computer.
- `PROJECT_DATA` payload is present once and valid JSON; all project-provided text is encoded/escaped in the HTML.
- Search, tabs, file details, function details, entrypoint flow, reverse impact graph, copy prompts function.
- Screen remains useful at 375px and desktop width; flow can scroll horizontally.
- If only HTML/CSS/SQL is present, function graph may be blank; say so rather than invent edges.
- If old `code-explorer.html` exists, verify it is ours before overwriting; regenerate after edits, never append more output files.
- If Python AST parser fails, mark the affected file as unparsable rather than fabricating functions.

## When user requests a modification
- Explain change target and upstream/downstream impact in ordinary language.
- Ask for explicit approval of a concrete modification plan before touching source.
- After approval use tests appropriate for the technology; don't say tests passed unless actually run.
- Regenerate the HTML, verify Git commit/working tree metadata and output link.
