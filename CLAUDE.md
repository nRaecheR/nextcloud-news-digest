# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A read-only tool that fetches unread news items from a Nextcloud News server via its REST API, generates output documents in configurable formats (Markdown, Markdown with inline images, PDF, plain text, JSON), and runs inside a Podman or Docker container.

## Big-Picture Architecture

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

| File | Responsibility |
|------|---------------|
| `src/__init__.py` | Empty — makes `src/` a Python package |
| `src/colors.py` | ANSI terminal color helpers: `green()`, `orange()`, `red()` |
| `src/config.py` | `.env` parser → frozen `Settings` dataclass (`state_mode` field: `"none"`, `"file"`, `"mark_read"`) |
| `src/state.py` | JSON-based timestamp persistence (used only when `state_mode="file"`) |
| `src/main.py:_mark_items_read()` | Marks fetched items as read via batch API (used when `state_mode="mark_read"`) |
| `src/document.py` | Markdown document generator (date grouping, 2KB truncation, image downloading) |
| `src/images.py` | Image download from article HTML — downloads to `output/images/`, replaces `<img>` tags with markdown image links |
| `src/main.py` | Orchestrator — config → API → content → formatters → filesystem |
| `src/nextcloud_client.py` | Nextcloud News REST API client |
| `src/formats/__init__.py` | Format dispatch (lazy-imports format modules) |
| `src/formats/md_inline.py` | Markdown with base64-embedded images |
| `src/formats/pdf.py` | PDF via WeasyPrint (inline image download + base64 embedding) |
| `src/formats/txt.py` | Plain text output |
| `src/formats/json_fmt.py` | Structured JSON output |

## Critical API Quirks (from `nextcloud_client.py`)

- `feedId` query parameter on `/items/updated` is **ignored by the server** — returns all items. Client-side filtering by `feedId` is mandatory.
- `description` field is **empty** in the API response — always use `body` (full HTML content, ~8KB+) as the content source. `document.py` already handles this: `body` first, `description` fallback.
- `folders` endpoint returns `name` not `title` — code normalizes `folder["title"] = folder["name"]` in `get_folders()`.
- If the API omits `lastModified` from the response, the client falls back to `int(time.time())`.
- `/feeds/{id}/items` returns 405 — always use `/items/updated` instead.

## Output Formats

Configurable via `OUTPUT_FORMATS` env var (comma-separated). Each format writes to a dedicated subdirectory under `/output/` (e.g., `output/pdf/`, `output/txt/`).

| Format | Description | File Extension | Dependencies |
|--------|-------------|---------------|-------------|
| `md` | Markdown with separate `images/` directory | `.md` | None (built-in) |
| `md-inline` | Markdown with base64-embedded images | `.md` | None (built-in) |
| `pdf` | Styled PDF via WeasyPrint (images embedded) | `.pdf` | `weasyprint` + GTK libs |
| `txt` | Plain text (stripped content) | `.txt` | None (built-in) |
| `json` | Structured JSON with all item data | `.json` | None (built-in) |

Each format module exposes a `render(content, folder_name, feed_name, fetch_date, output_dir) -> str | bytes` function. Content dicts contain: `title`, `author`, `date_str`, `time_str`, `html_body`, `markdown_body` (HTML-stripped), `link`, `pubDate`.

### PDF Image Embedding

The PDF renderer uses a 4-step pipeline per item to embed images directly in the PDF binary:
1. Download images from raw `body` HTML to `output_dir/images/`
2. Replace `<img>` tags with markdown image links
3. Strip HTML tags (markdown image links survive)
4. Convert markdown image links to base64 data-URI `<img>` tags so WeasyPrint embeds them

### Adding a New Format

1. Create `src/formats/<name>.py` with a `render()` function matching the signature above.
2. Register it in `src/formats/__init__.py` (`_load_format_module` and `_EXTENSION_MAP`).
3. Add to `requirements.txt` and `Dockerfile` if new dependencies are needed.
4. Write tests in `tests/test_formats.py`.

## File Splitting

Configurable via `DAYS_PER_FILE` env var:
- `0` — Single flat file with all items (no splitting)
- `1` — One file per day
- `7` (default) — Weekly chunks

When splitting, each file gets the same header (feed name, folder, fetch date, total item count) and items are distributed into consecutive time windows. Image downloading is shared across all files via a common cache.

## Development Commands

All development runs inside a container. Both Podman and Docker are supported — the same `Dockerfile` (a standard Dockerfile) works with either runtime. There is no local pip/pytest setup needed.

```bash
# Build (compiles tests automatically as CMD, no -f flag needed)
podman build -t nextcloud-news-digest .
docker build -t nextcloud-news-digest .

# Run the fetcher (standalone)
podman run --rm \
  -v $(pwd)/.env:/app/.env:ro \
  -v $(pwd)/output:/output \
  -v $(pwd)/.news-digest:/app/.news-digest \
  -e PYTHONPATH=/app \
  -e TZ=${TZ:-Europe/Berlin} \
  nextcloud-news-digest \
  python src/main.py
# or with Docker: docker run ... (same flags)

# Alternative: use podman-compose (single command)
podman-compose -f compose.yaml up --build
# or: docker-compose -f compose.yaml up --build
```

Run tests only (same as build CMD, but you can add flags):
```bash
podman run --rm nextcloud-news-digest python -m pytest tests/ -v
# or: docker run --rm nextcloud-news-digest python -m pytest tests/ -v

# Run a single test file
podman run --rm nextcloud-news-digest python -m pytest tests/test_document.py -v

# Run a single test function
podman run --rm nextcloud-news-digest python -m pytest tests/test_document.py::TestGenerateMarkdown::test_single_item_all_fields -v
```

## Configuration

Copy `.env.example` to `.env` and fill in values:

```bash
cp .env.example .env
```

Required keys: `NEXTCLOUD_BASE_URL` (must be HTTPS), `NEXTCLOUD_USER`, `NEXTCLOUD_ACCESS_TOKEN`, `NEWS_FOLDER`, `NEWS_FEED`.
Optional: `REQUEST_TIMEOUT_SECONDS` (default 20), `DAYS_PER_FILE` (default 7, 0 = single file), `OUTPUT_FORMATS` (default `md`), `STATE_MODE` (default `mark_read`, values: `none`, `file`, `mark_read`).

## File Structure

```
README.md           # User-facing usage instructions
requirements.txt    # Runtime deps: requests, python-dotenv, weasyprint
Dockerfile          # Container build spec (CMD = pytest, GTK deps for WeasyPrint, ENV TZ=UTC)
.env.example        # Template
.gitignore          # Ignores .env, .news-digest/, output/, __pycache__/
src/
  __init__.py       # Package init
  colors.py         # ANSI color helpers
  config.py         # .env parser + Settings dataclass
  state.py          # JSON state persistence (load_state, save_state)
  document.py       # Markdown generator (generate_markdown, generate_markdown_files)
  images.py         # Image download + markdown link replacement
  main.py           # Orchestrator (find_feed, _build_content_items, _write_output, main)
  nextcloud_client.py  # API client
  formats/
    __init__.py     # Format dispatch (render, format_ext, supported_formats)
    md_inline.py    # Markdown with inline base64 images
    pdf.py          # PDF via WeasyPrint (embedded images)
    txt.py          # Plain text
    json_fmt.py     # Structured JSON
tests/
  __init__.py
  test_config.py          # 13 tests
  test_state.py           # 7 tests
  test_document.py        # 16 tests
  test_images.py          # 14 tests
  test_nextcloud_client.py  # 21 tests (uses responses for HTTP mocking)
  test_formats.py         # 22 tests (dispatch, md-inline, txt, json, pdf)
  test_main.py            # 9 tests (mark_read helper, mode dispatch)
```

## Testing

- 112 tests total, all use mocked HTTP via `responses` library — no real network calls.
- Tests run automatically on every build (`podman build` or `docker build`) — CMD in Dockerfile is pytest.
- To iterate quickly, add `-k <test_name_fragment>` or `-k <class_name>` to the pytest command.
- Test files follow a `Class<Method>` naming convention for readability.
- PDF tests require `weasyprint` with GTK dependencies (installed in the container via the Dockerfile).