# worth-my-time (`wmt`)

Local-first “content triage” pipeline: save links into a Brave bookmarks folder called **Inbox**, then generate **one Markdown analysis file per bookmark** (synced to your phone via Syncthing).

## What it does (v1)

1. Reads Brave/Chromium `Bookmarks` JSON file (macOS default profile)
2. Finds `roots.bookmark_bar/.../Inbox`
3. Picks **one** unprocessed URL bookmark
4. Pulls **YouTube captions** when available; otherwise relies on Codex web search/browsing to read the URL
5. Runs an LLM triage prompt via Codex CLI (optionally with web search enabled for “reception pulse” links)
6. Writes a single `.md` file into your output folder
7. Records processed state (JSON default; optional sqlite) so each item is handled once

## Repo layout

- `config.yaml` sample config (copy to `~/.config/wmt/config.yaml`)
- `prompts/triage_prompt.md` reference prompt template (the code uses an embedded copy)
- `src/wmt/` implementation
- `tests/` minimal unit tests

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

You also need the `codex` CLI installed and logged in (this tool shells out to it).

YouTube transcripts are fetched automatically via `youtube-transcript-api` (installed as a dependency).

Optional:
- `brew install yt-dlp` (fallback subtitle retrieval when the API fails)

## Configure

```bash
mkdir -p ~/.config/wmt
cp config.yaml ~/.config/wmt/config.yaml
```

Edit `~/.config/wmt/config.yaml`:
- `paths.bookmarks_file` → Brave `Bookmarks` JSON path
- `paths.output_dir` → Syncthing folder where `.md` files should land
- `bookmarks.inbox_folder_name` → must be `Inbox` (case-sensitive)
- `codex.web_search_enabled: true` → enables “reception pulse” lookups

### Finding the Brave bookmarks file (macOS)

Default profile is usually:

`~/Library/Application Support/BraveSoftware/Brave-Browser/Default/Bookmarks`

If you use multiple profiles, check sibling folders like `Profile 1/Bookmarks`.

## Usage

Process one bookmark from Inbox:

```bash
wmt process-one --config ~/.config/wmt/config.yaml
```

Watch forever (polling; processes at most one per loop):

```bash
wmt watch --config ~/.config/wmt/config.yaml
```

Process a URL directly (YouTube transcripts are fetched automatically when available):

```bash
wmt process-url "https://www.youtube.com/watch?v=VIDEO"
```

Process a URL with a transcript you already have (podcasts, paywalled content, etc.):

```bash
wmt process-url "https://example.com/something" --transcript-stdin < transcript.txt
```

Show ledger counts:

```bash
wmt status
```

## Notes / guarantees

- **No-bluff prompt:** the prompt explicitly demands it says what it could/couldn’t access (paywalls, partial content, no transcript, etc.).
- **Paywalls:** the output should clearly say what was/wasn’t accessible.
- **Crash safety:** items are marked `in_progress` first (with TTL) and won’t double-process across runners.
- **One file per bookmark:** the tool writes a fresh file once per processed item (no append-only notebooks).
