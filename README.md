# Nextcloud News Digest

Fetches unread news items from a [Nextcloud News](https://github.com/nextcloud/news) server, generates output documents (Markdown, Markdown with inline images, PDF, plain text, JSON) and imports them into an AI-powered notebook — [Open-Notebook](https://github.com/nicholasgasior/open-notebook) (Markdown import) or [Google Gemini Notebook](https://notebooklm.google.com/) (NotebookML import). Runs inside a Podman or Docker container.

## Links

| Resource | URL |
|----------|-----|
| Nextcloud | https://nextcloud.com/ |
| Nextcloud News app | https://apps.nextcloud.com/apps/news |
| Nextcloud News API docs | https://github.com/nextcloud/news |
| Open-Notebook | https://github.com/nicholasgasior/open-notebook |
| Google Gemini Notebook | https://notebooklm.google.com/ |
| NotebookML format | https://github.com/google-gemini/notebookml (reference) |

## Prerequisites

- [Podman](https://podman.io/) (rootless) **or** [Docker](https://www.docker.com/) installed on the host
- [Nextcloud](https://nextcloud.com/) with the [News app](https://apps.nextcloud.com/apps/news) enabled and at least one feed subscribed
- Valid Nextcloud News access token (generated in Nextcloud → Settings → Security → App passwords)
- Python installed on host (for `python-dotenv` development only; all runtime dependencies are in the container)

## Configuration

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `NEXTCLOUD_BASE_URL` | Nextcloud server URL (must use `https://`) |
| `NEXTCLOUD_USER` | Nextcloud username |
| `NEXTCLOUD_ACCESS_TOKEN` | App password / access token (generated in Nextcloud settings) |
| `REQUEST_TIMEOUT_SECONDS` | HTTP request timeout in seconds (default: 20) |
| `NEWS_FOLDER` | Folder name in Nextcloud News |
| `NEWS_FEED` | Feed name within the folder |
| `OUTPUT_FORMATS` | Comma-separated output formats: `md`, `md-inline`, `pdf`, `txt`, `json` (default: `md`) |
| `DAYS_PER_FILE` | Split Markdown and PDF output into date windows: `0` = single flat file, `1` = one file per day, `7` = weekly chunks (default: 7) |
| `STATE_MODE` | State tracking strategy: `mark_read` = fetch all unread, mark as read on server (default), `file` = save/load timestamp to `.news-digest/state.json` (legacy), `none` = always fetch all unread, no state saved |

## Build

Builds the container image and runs all tests automatically. Both runtimes default to `Dockerfile`, so the `-f` flag is unnecessary:

```bash
# Podman or Docker
podman build -t nextcloud-news-digest .
docker build -t nextcloud-news-digest .
```

## Run

```bash
# Podman
podman run --rm \
  -v "$(pwd)/.env:/app/.env:ro" \
  -v "$(pwd)/output:/output" \
  -v "$(pwd)/.news-digest:/app/.news-digest" \
  -e PYTHONPATH=/app \
  -e TZ=${TZ:-Europe/Berlin} \
  nextcloud-news-digest \
  python src/main.py

# Docker
docker run --rm \
  -v "$(pwd)/.env:/app/.env:ro" \
  -v "$(pwd)/output:/output" \
  -v "$(pwd)/.news-digest:/app/.news-digest" \
  -e PYTHONPATH=/app \
  -e TZ=${TZ:-Europe/Berlin} \
  nextcloud-news-digest \
  python src/main.py
```

Both runtimes share the same commands and volume mounts. The `Dockerfile` is a standard Dockerfile that works with either Podman or Docker.

### Compose

For a single-command build-and-run experience, use `compose.yaml` which pre-configures all volume mounts and environment variables:

```bash
# Podman
podman-compose -f compose.yaml up --build

# Docker
docker-compose -f compose.yaml up --build
```

Compose reads `.env` from the current directory automatically and mounts `output/` and `.news-digest/` as defined in the compose file.

### Volume Mounts

| Host Path | Container Path | Purpose |
|-----------|---------------|---------|
| `.env` | `/app/.env` (ro) | Configuration file |
| `output/` | `/output` | Generated output files |
| `.news-digest/` | `/app/.news-digest` | Persisted fetch state (cross-run tracking) |

## Output

Generated files are placed in format-specific subdirectories under `output/` with a timestamped name:

```
output/md/
    news_20260718_143000_p001.md      # Markdown (weekly chunk 1)
    news_20260718_143000_p002.md      # Markdown (weekly chunk 2)
    images/                           # downloaded images (multi-format cache)
output/md-inline/
    news_20260718_143000.md           # Markdown with base64-embedded images
    images/
output/pdf/
    news_20260718_143000_p001.pdf     # PDF (weekly chunk 1, images embedded)
    news_20260718_143000_p002.pdf     # PDF (weekly chunk 2)
    images/
output/txt/
    news_20260718_143000.txt          # Plain text
output/json/
    news_20260718_143000.json         # Structured JSON
```

### Format Details

| Format | Description |
|--------|-------------|
| `md` | Markdown with separate `images/` directory. Images downloaded from articles, `<img>` tags replaced with markdown links. Split by date window (configurable via `DAYS_PER_FILE`). |
| `md-inline` | Markdown with base64-embedded images in the document body. Single file regardless of `DAYS_PER_FILE`. |
| `pdf` | Styled PDF via WeasyPrint with images embedded as base64 data-URIs. Split by date window. |
| `txt` | Plain text with stripped HTML content. Single file. |
| `json` | Structured JSON array with all item metadata (title, author, date, time, body, URL). Single file. |

### Markdown Structure (Open-Notebook / NotebookML compatible)

The Markdown files use a structured heading hierarchy designed for AI-powered Q&A:

```markdown
# Feed Name
Fetch Date: 2026-07-18 14:30:00 UTC

## 2026-07-18 (Week 29)

### Title of the Article
Author: Jane Doe
Date: 2026-07-18 10:22:00

Description excerpt (HTML-stripped) with [link to full article](https://...).

![Description image](../images/uuid.jpg)
```

- `# Feed Name` — top-level heading identifying the feed
- `## Date` (or `## Week N`) — items grouped by day or week based on `DAYS_PER_FILE`
- `### Title` — each article heading with author, date, and time metadata
- Body content — HTML-stripped description with inline links and image references
- Long bodies (>2 KB) are truncated with a "(truncated)" suffix

## Import to an AI Notebook

### Open-Notebook (Markdown)

1. Open [Open-Notebook](https://github.com/nicholasgasior/open-notebook)
2. Click **Add Source** → **Upload File**
3. Select the generated `.md` file from the `output/md/` directory
4. The content is processed and ready for AI-powered Q&A

### Google Gemini Notebook (NotebookML)

The Markdown structure is compatible with [Google Gemini Notebook](https://notebooklm.google.com/). Upload generated Markdown files as sources to enable AI-powered summarization, note-taking, and audio overviews. Notebook LM accepts Markdown, MarkdownML, and PDF as source formats.

## Testing

All 98 tests run inside the container. The build step runs tests automatically as its final CMD.

To run tests separately:

```bash
podman run --rm nextcloud-news-digest python -m pytest tests/ -v
# or with Docker:
docker run --rm nextcloud-news-digest python -m pytest tests/ -v

# Run a single test file:
podman run --rm nextcloud-news-digest python -m pytest tests/test_document.py -v

# Run a single test function:
podman run --rm nextcloud-news-digest python -m pytest tests/test_document.py::TestGenerateMarkdown::test_single_item_all_fields -v
```

## Architecture

```
.env  →  config.py  →  NextcloudNewsClient  →  get_feed_items()  →  items
                                                                 │
                                                        .news-digest/state.json
                                                         ◄── save_state()
                                                              │
                                                  sort + _build_content_items()
                                                  (prepares content dicts; images downloaded per-format)
                                                              │
                                               ┌───┼───┬───┬───┐
                                               ▼   ▼   ▼   ▼   ▼
                                         output/md  md-inline  pdf  txt  json
                                         output/news_YYYYMMDD_HHMMSS.{ext}
```

### Module Map

| Module | Responsibility |
|--------|---------------|
| `config.py` | Parses and validates `.env` → frozen `Settings` dataclass |
| `state.py` | JSON-based timestamp persistence across fetch runs |
| `document.py` | Markdown generator — date grouping, 2 KB truncation, file splitting |
| `images.py` | Image download from article HTML — replaces `<img>` tags with markdown links |
| `main.py` | Orchestrator — config → API → content → formatters → filesystem |
| `nextcloud_client.py` | Nextcloud News REST API client (folders, feeds, items) |
| `formats/__init__.py` | Format dispatch — lazy-imports format modules |
| `formats/md_inline.py` | Markdown with base64-embedded images |
| `formats/pdf.py` | PDF via WeasyPrint with embedded images |
| `formats/txt.py` | Plain text output |
| `formats/json_fmt.py` | Structured JSON output |

### Key Behaviour

- **State tracking** (configurable via `STATE_MODE`):
  - `mark_read` (default): fetch all unread items, then mark them as read on the server. No state file needed — the server's read/unread status is the state.
  - `file`: legacy behavior — a `.news-digest/state.json` file stores the last fetched timestamp. Subsequent runs only fetch new items.
  - `none`: always fetch all unread items, no state saved or server mutations.
- **Per-format image downloading**: Each format renderer downloads images independently from the raw article HTML. A shared in-memory cache prevents duplicate downloads within a single run.
- **File splitting**: Markdown and PDF output can be split by configurable date windows (`DAYS_PER_FILE`). Set to `0` for a single flat file.
- **Client-side feed filtering**: The Nextcloud News API ignores the `feedId` query parameter — items are filtered client-side after fetching from `/items/updated`.

## Adding a New Format

1. Create `src/formats/<name>.py` with a `render(content, folder_name, feed_name, fetch_date, output_dir) -> str | bytes` function.
2. Register it in `src/formats/__init__.py` (`_load_format_module` and `_EXTENSION_MAP`).
3. Add to `requirements.txt` and `Dockerfile` if new dependencies are needed.
4. Write tests in `tests/test_formats.py`.