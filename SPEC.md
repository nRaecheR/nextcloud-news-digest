# Nextcloud News to Podcast Document Fetcher — Specification

## 1. Overview

A read-only tool that fetches unread news items from a [Nextcloud News](https://github.com/nextcloud/news) server via its REST API, generates output documents in multiple configurable formats (Markdown, Markdown with inline images, PDF, plain text, JSON), and runs inside a Podman or Docker container.

**Key design goals:**
- Zero host-side dependencies — everything runs in the container.
- Automated tests gate every container build.
- State persistence across runs avoids re-fetching old items.
- Output in multiple formats, each with optimized image handling.

## 2. Architecture

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
| `src/config.py` | `.env` parser → frozen `Settings` dataclass |
| `src/state.py` | JSON-based timestamp persistence |
| `src/document.py` | Markdown document generator (date grouping, 2KB truncation, image downloading) |
| `src/images.py` | Image download from article HTML — downloads to `output/images/`, replaces `<img>` tags with markdown image links |
| `src/main.py` | Orchestrator — config → API → content → formatters → filesystem |
| `src/nextcloud_client.py` | Nextcloud News REST API client |
| `src/formats/__init__.py` | Format dispatch (lazy-imports format modules) |
| `src/formats/md_inline.py` | Markdown with base64-embedded images |
| `src/formats/pdf.py` | PDF via WeasyPrint (inline image download + base64 embedding) |
| `src/formats/txt.py` | Plain text output |
| `src/formats/json_fmt.py` | Structured JSON output |
| `tests/test_config.py` | Config parsing tests (13 tests) |
| `tests/test_state.py` | State persistence tests (7 tests) |
| `tests/test_document.py` | Markdown generation tests (16 tests) |
| `tests/test_images.py` | Image download + replacement tests (14 tests) |
| `tests/test_nextcloud_client.py` | API client tests (21 tests) |
| `tests/test_formats.py` | Format dispatch and format-specific tests (22 tests) |

**Total: 98 unit tests, all using mocked HTTP (no real network calls).**

## 3. Configuration

### Environment Variables (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXTCLOUD_BASE_URL` | Yes | Nextcloud server URL, must start with `https://` |
| `NEXTCLOUD_USER` | Yes | Nextcloud username |
| `NEXTCLOUD_ACCESS_TOKEN` | Yes | App password / access token (generated in Nextcloud settings) |
| `REQUEST_TIMEOUT_SECONDS` | No (default: 20) | HTTP request timeout in seconds |
| `DAYS_PER_FILE` | No (default: 7) | Number of calendar days per output file (0 = single flat file, 1 = one per day, 7 = weekly chunks) |
| `NEWS_FOLDER` | Yes | Folder name in Nextcloud News |
| `NEWS_FEED` | Yes | Feed name within the folder |
| `OUTPUT_FORMATS` | No (default: `md`) | Comma-separated list: `md,md-inline,pdf,txt,json` |
| `STATE_MODE` | No (default: `mark_read`) | State tracking strategy: `none`, `file`, `mark_read` |

### Settings Dataclass

```python
@dataclass(frozen=True)
class Settings:
    base_url: str
    user: str
    access_token: str
    timeout_seconds: int
    news_folder: str
    news_feed: str
    state_mode: str  # "none", "file", "mark_read"
    state_file: Path  # Resolved as Path("/app/.news-digest/state.json")
    days_per_file: int  # Split output into files by date range (0 = no split)
    output_formats: list[str]
```

### Validation Rules

- Missing required keys → `ConfigurationError` with message listing missing keys.
- Empty string values → `ConfigurationError`.
- `NEXTCLOUD_BASE_URL` must start with `https://`.
- `REQUEST_TIMEOUT_SECONDS` must be a positive integer.
- `DAYS_PER_FILE` must be a non-negative integer (0 = no splitting, 1+ = split by that many days).
- `STATE_MODE` must be one of `none`, `file`, `mark_read`.

## 4. State Persistence

### Storage Format

File: `.news-digest/state.json`

```json
{
  "last_fetched_timestamp": 1784367941
}
```

### Load Behavior

- Missing file → returns default `{last_fetched_timestamp: 0}` (first run, fetch all).
- Corrupted JSON → returns default (resets to fetch all, does not crash).

### Save Behavior

- Creates parent directories (`.news-digest/`) if they don't exist.
- Atomic-ish write: writes then renames (Python's `open(..., "w")`).

## 5. API Client

### Version Negotiation

1. Probe `/index.php/apps/news/api/v1-3/version`
2. If that fails, fall back to `/index.php/apps/news/api/v1-2/version`
3. Version must be ≥ 28.4.0; otherwise raise `RuntimeError`
4. `api_base` is set to whichever path responded successfully

### Key Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/folders` | List all folders |
| `GET` | `/feeds` | List all feeds |
| `GET` | `/items/updated?lastModified=N&feedId=M` | Fetch updated items |
| `PUT` | `/items/{id}/read` | Mark single item as read |
| `POST` | `/items/read/multiple` | Batch mark items as read (v1-3) |

### Critical API Behavior

- **`feedId` filter is ignored by the server** — the endpoint returns all items regardless. Client-side filtering by `feedId` is required.
- **`description` field is empty** — use `body` (full HTML content) instead.
- **`lastModified` timestamp** — if the API doesn't return `lastModified`, the client uses `int(time.time())` as fallback.

### Items Data Model

Each item returned from the API is a dict with these keys:

| Key | Type | Description |
|-----|------|-------------|
| `id` | int | Unique item ID |
| `feedId` | int | Feed ID (used for client-side filtering) |
| `title` | str | Article title |
| `author` | str | Author (may be `"Unknown"` or empty) |
| `pubDate` | int | Unix timestamp (Nextcloud News API field name) |
| `body` | str | Full HTML content (primary content source) |
| `description` | str | Short description (often empty, fallback) |
| `url` | str | Canonical URL |

## 6. Markdown Document Generation

### Document Structure

```markdown
# Feed Name

**Folder:** My Folder
**Fetch Date:** 2026-07-17 15:11:35 Berlin
**Total Items:** 4145

---
## 2026-07-17

### Article Title

Some stripped text from the article body content... up to 2000 characters.
![Alt text](images/a1b2c3d4e5f6.jpg)

*Author: John Doe | Date: 2026-07-17 | Time: 12:00:00*

[https://example.com/article](https://example.com/article)
```

- **Fetch date** uses the container's local timezone (set via `TZ` env var, e.g. `Berlin` for `Europe/Berlin`).
- **Item timestamps** use the container's local timezone (converted from the API's Unix `pubDate` timestamp).
- **Images** referenced via relative markdown links to `images/` subdirectory.

### Generation Rules

1. **Header:** Feed name as `#` heading, followed by folder, fetch date (local timezone), total items.
2. **Sorting:** Items sorted `pubDate` ascending (oldest → newest), regardless of input order.
3. **Date grouping:** Items grouped under `## YYYY-MM-DD` with a `---` separator before each date.
4. **Body content:** Use `body` field first; fall back to `description`. Images are downloaded from raw HTML before stripping. HTML tags are removed (regex `<[^>]+>` → space). Content truncated to 2000 characters with `"(truncated)"` suffix.
5. **Metadata row:** Italicized `Author: ... | Date: ... | Time: ...` separated by ` | `. Author line is omitted if author is empty or `"Unknown"`. All timestamps use the container's local timezone (from `TZ` env var).
6. **Link:** Markdown link `[url](url)` if `url` field is present.
7. **Empty items:** Produces header + "No new items found."

### Image Downloading (`src/images.py`)

Images are extracted from article body HTML before content is stripped, replaced with relative markdown links, then HTML is stripped.

**Two HTML patterns are handled:**

| Pattern | Description | Example |
|---------|-------------|---------|
| `<img src="...">` | Direct image tags | `<img src="//example.com/i/abc.jpg">` |
| `<img alt="...">` + `<a href="...">` | Empty placeholder where URL is in a nearby `<a>` tag | `<img alt="Photo">` followed by `<a href="photo.jpg">` |

**Algorithm:**

1. Scan body HTML with regex for `<img src="...">` and `<img alt="...">` patterns.
2. For empty `<img>` tags, search preceding and following `<a>` tags (up to 3000 chars ahead) for a media URL.
3. For each unique URL (deduplicated via cache dict across all items):
   - `HEAD` request to validate Content-Type is `image/*`
   - `GET` download to `output_dir/images/`
   - Filename from `Content-Disposition` header, URL path, or MD5 hash of URL
   - Resolves protocol-relative URLs (`//example.com` → `https://example.com`)
4. Replace HTML image tags with markdown syntax (`![alt](images/filename.jpg)`) before HTML stripping.
5. Remove the accompanying `<a>` link tag for placeholder patterns.

**Error handling:** Failed downloads log a warning and are skipped (non-fatal).

### Content Truncation Rationale

- Nextcloud News `body` field can be 8KB+ per item.
- 2000 characters keeps Markdown files manageable while preserving article substance.
- 4,145 items → ~33,000 lines total.

## 7. Output Formats

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

The PDF renderer uses a 4-step pipeline per item:
1. Download images from raw `body` HTML to `output_dir/images/`
2. Replace `<img>` tags with markdown image links
3. Strip HTML tags (markdown image links survive)
4. Convert markdown image links to base64 data-URI `<img>` tags so WeasyPrint embeds them directly

This ensures images are embedded in the PDF binary, not just referenced as external files.

### Adding a New Format

1. Create `src/formats/<name>.py` with a `render()` function matching the signature above.
2. Register it in `src/formats/__init__.py` (`_load_format_module` and `_EXTENSION_MAP`).
3. Add to `requirements.txt` and `Dockerfile` if new dependencies are needed.
4. Write tests in `tests/test_formats.py`.

## 8. Orchestrator (`main.py`)

### Pipeline Steps

1. Load `.env` → `Settings` (exit 1 on config error).
2. Initialize `NextcloudNewsClient` (exit 1 on API connection error).
3. Find feed by `folder_name` + `feed_name`:
   - List folders, find folder by `title` match.
   - List feeds, find feed by `folderId` + `title` match.
   - Exit 1 if folder or feed not found (shows available folders as hint).
4. Load persisted state → `last_timestamp` (only when `state_mode="file"`).
5. Fetch items: `client.get_feed_items(feed_id, last_modified=last_timestamp)`.
6. Sort items by `pubDate` ascending.
7. For each requested format, delegate to the appropriate renderer.
8. Post-fetch (mode-dependent):
   - `mark_read`: call `_mark_items_read()` to mark all fetched items as read via batch API.
   - `file`: save `new_timestamp` to state file.
   - `none`: no post-fetch action.
9. Log summary: files generated, items processed.

### Markdown Output (`md` format)

- If `DAYS_PER_FILE > 1`: uses `generate_markdown_files()` to split items into multiple files by date range (shared image cache).
- If `DAYS_PER_FILE == 1`: same as above (one file per day).
- If `DAYS_PER_FILE == 0`: single flat file with all items (`generate_markdown()`).

### File Splitting

When `DAYS_PER_FILE` is set to a value greater than 1 (default 7), the output is split into multiple files:

| `DAYS_PER_FILE` | Behavior |
|-----------------|----------|
| 1 or 2 | Maximum one file per day |
| 7 (default) | Files cover a week each |
| 0 | Single flat file with all items (no splitting) |

Items are distributed into consecutive time windows of `DAYS_PER_FILE` calendar days. Each file contains the same full header (feed name, folder, fetch date, total item count) and a subset of items grouped by date. Image downloading is shared across all files via a common cache.

### Output

- Directory: `/output/` (mounted from host `output/`)
- Filename: `news_YYYYMMDD_HHMMSS.md` (single file, `DAYS_PER_FILE=0`) or `news_YYYYMMDD_HHMMSS_p001.md` … (multiple files when splitting)
- Return code: 0 on success, 1 on error

## 9. Container Build & Run

This project supports both **Podman** and **Docker**. The same container image works with either runtime — the build command and run command only differ by the binary name (`podman` vs `docker`).

### Build Specification (`Dockerfile`)

The `Dockerfile` is a standard Dockerfile that works with both Podman and Docker. Both runtimes look for `Dockerfile` by default.

```dockerfile
FROM docker.io/library/python:3.12-slim

# WeasyPrint requires GTK/GObject libraries for PDF rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libharfbuzz0b \
        libpangoft2-1.0-0 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir requests python-dotenv pytest responses weasyprint

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY tests/ ./tests/

RUN mkdir -p /output

# Tests always use UTC for deterministic output
ENV TZ=UTC

# Default: run tests on every build
CMD ["python", "-m", "pytest", "tests/", "-v"]
```

- **Base image:** Python 3.12-slim (~140MB).
- **Dependencies:** `requests` (runtime), `python-dotenv` (runtime), `pytest` + `responses` (tests), `weasyprint` (PDF rendering).
- **GTK libs:** Installed via `apt` for WeasyPrint's rendering engine.
- **CMD = pytest** — every build runs all tests automatically. Build failure = test failure.
- **`ENV TZ=UTC`** — tests run under UTC for deterministic output; the run command overrides this with the host timezone.
- **Dual runtime:** The Dockerfile works with both Podman and Docker out of the box.

### Timezone Configuration

The container reads its timezone from the `TZ` environment variable (e.g. `Europe/Berlin`). All timestamps in the output document use the container's local timezone, derived from `os.environ["TZ"]`.

| Component | Timezone |
|-----------|----------|
| Container runtime (logs, file names) | `TZ` env var |
| Document header (`Fetch Date`) | `TZ` env var (labelled, e.g. "Berlin") |
| Item timestamps (`pubDate`) | `TZ` env var (Unix timestamp converted to local time) |
| Test output | `UTC` (hardcoded via `ENV TZ=UTC` in Dockerfile) |

### Container Compose (`compose.yaml`)

A `compose.yaml` file is provided that works with both `podman-compose` and `docker-compose`. Use the `--dockerfile` flag to select which build file to use:

```bash
# Podman
podman-compose -f compose.yaml up --build

# Docker
docker-compose -f compose.yaml up --build
```

Equivalent to the longhand `podman run` (replace `podman` with `docker` for Docker):

```bash
podman run --rm \
  -v "$(pwd)/.env:/app/.env:ro" \
  -v "$(pwd)/output:/output" \
  -v "$(pwd)/.news-digest:/app/.news-digest" \
  -e PYTHONPATH=/app \
  -e TZ=${TZ:-Europe/Berlin} \
  nextcloud-news-digest \
  python src/main.py
```

### Build Command

```bash
# Podman or Docker (both default to Dockerfile)
podman build -t nextcloud-news-digest .
docker build -t nextcloud-news-digest .
```

## 10. Filesystem Layout

```
nextcloud-news-digest/
├── .env                          # Live config (git-ignored)
├── .env.example                  # Template with placeholders
├── .gitignore                    # Ignores .news-digest/, output/, __pycache__/, *.pyc, .env
├── Dockerfile                    # Container build spec (CMD = pytest, GTK deps for WeasyPrint, ENV TZ=UTC)
├── compose.yaml                  # docker-compose build+run config
├── README.md                     # Usage instructions
├── requirements.txt              # requests>=2.31.0, python-dotenv>=1.0.0, weasyprint>=60.0
├── .news-digest/
│   └── state.json                # Persisted last_fetched_timestamp
├── src/
│   ├── __init__.py               # Package init
│   ├── colors.py                 # ANSI color helpers
│   ├── config.py                 # .env parser + Settings dataclass
│   ├── state.py                  # JSON state persistence
│   ├── document.py               # Markdown generator (generate_markdown, generate_markdown_files)
│   ├── images.py                 # Image download from article HTML → markdown links
│   ├── main.py                   # Orchestrator (find_feed, _build_content_items, _write_output, main)
│   ├── nextcloud_client.py       # API client
│   └── formats/
│       ├── __init__.py           # Format dispatch (render, format_ext, supported_formats)
│       ├── md_inline.py          # Markdown with inline base64 images
│       ├── pdf.py                # PDF via WeasyPrint (embedded images)
│       ├── txt.py                # Plain text
│       └── json_fmt.py           # Structured JSON
├── tests/
│   ├── __init__.py               # Package init
│   ├── test_config.py            # 13 tests
│   ├── test_state.py             # 7 tests
│   ├── test_document.py          # 16 tests
│   ├── test_images.py            # 14 tests
│   ├── test_nextcloud_client.py  # 21 tests
│   └── test_formats.py           # 22 tests (dispatch, md-inline, txt, json, pdf)
└── output/
    ├── md/
    │   ├── news_YYYYMMDD_HHMMSS.md  # Markdown with separate images/ (if splitting enabled)
    │   └── images/                   # Downloaded images
    ├── md-inline/
    │   └── news_YYYYMMDD_HHMMSS.md  # Markdown with base64-embedded images
    ├── pdf/
    │   ├── news_YYYYMMDD_HHMMSS.pdf  # PDF with embedded images
    │   └── images/                   # Downloaded images (for PDF rendering)
    ├── txt/
    │   └── news_YYYYMMDD_HHMMSS.txt  # Plain text
    └── json/
        └── news_YYYYMMDD_HHMMSS.json  # Structured JSON
```

## 11. Design Decisions & Rationale

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Feed scope | Single feed (`NEWS_FEED`) | Simpler, focused use case; no need to scan entire folder |
| Feed update trigger | None; assume already updated | Admin-only API endpoints; adds unnecessary complexity |
| Content source | `body` > `description` | `description` is empty in Nextcloud News API; `body` has full content |
| Client-side filtering | Filter by `feedId` after fetch | Server ignores `feedId` query parameter on `/items/updated` |
| HTML stripping | Regex `<[^>]+>` → space | Simple, effective for extracting readable text from RSS HTML |
| Content truncation | 2000 chars + "(truncated)" | Balances content richness with file size (4K items → ~33K lines) |
| Timestamp fallback | `int(time.time())` | Some API responses omit `lastModified`; prevents re-fetching everything |
| Folder name normalization | Map `name` → `title` | API returns `name`; code and user config use `title` |
| Container CMD = pytest | Every build runs tests | Tests are a build-time gate; no separate test step needed |
| Timestamped output files | `news_YYYYMMDD_HHMMSS.md` | Allows keeping history; no overwrite across runs |
| JSON state format | Simple `{last_fetched_timestamp: N}` | No external database dependency; single key-value |
| Local timezone via TZ env var | Host timezone propagated to container | Output timestamps match user's local time; tests forced UTC |
| File splitting via DAYS_PER_FILE | Configurable (0 = flat, 1 = daily, 7 = weekly) | Keeps output manageable; `DAYS_PER_FILE=0` for single large file |
| Shared image cache across files | `image_cache` dict persists through all `generate_markdown_files()` calls | Avoids re-downloading the same image across split files |
| Images downloaded locally | `src/images.py` downloads images to `output/images/` | Portable local copies regardless of what Open-Notebook can do |
| IMAGE_RE patterns | Regex for `<img src>`, empty `<img alt>`, and `<a href media>` | Two HTML patterns cover all observed Nextcloud News image references |
| HEAD-then-GET for images | HEAD validates Content-Type before GET download | Avoids wasting bandwidth on non-image resources |
| PDF inline image pipeline | Download → replace → strip → base64 embed | Ensures images are embedded in PDF binary, not external references |
| Format dispatch via lazy import | `src/formats/__init__.py` loads modules on demand | New formats are plug-in modules; no code changes to main pipeline |

## 12. Error Handling

| Scenario | Behavior |
|----------|----------|
| Missing/invalid `.env` | `ConfigurationError` → exit 1 with message |
| Non-HTTPS URL | `ValueError` → exit 1 |
| API version < 28.4.0 | `RuntimeError` → exit 1 |
| Network failure | `logging.exception()` → empty items → save state → exit 0 |
| Folder not found | Warning log + list available folders → exit 1 |
| Feed not found | Warning log → exit 1 |
| Corrupted state file | Treated as first run (timestamp = 0) |
| HTTP error on item fetch | Empty items + current time → save state → exit 0 (graceful) |
| Image HEAD/GET failure | Warning logged, image skipped, continues processing |
| Invalid TZ env var | Falls back to `UTC` (os.environ.get("TZ", "UTC")) |
| DAYS_PER_FILE < 0 | `ConfigurationError` → exit 1 |
| DAYS_PER_FILE=0 | Single flat file (legacy behavior) |

## 13. Test Coverage

| Module | Tests | Coverage Scope |
|--------|-------|---------------|
| `config.py` | 13 | Valid env, missing keys, empty values, timeout validation, URL validation, DAYS_PER_FILE default/zero/custom, invalid values, OUTPUT_FORMATS parsing |
| `state.py` | 7 | Save/load, missing file, corrupted JSON, default values, directory creation |
| `document.py` | 16 | Empty items, single/multi items, date grouping, missing fields, HTML stripping, truncation, sort order, metadata rendering, multi-file generation, date splitting, shared cache |
| `images.py` | 14 | img src download, protocol-relative URL, non-image skip, HTTP error skip, dedup, empty img placeholder, non-media href skip, HEAD failure, replace images, remove preceding link, no-refs passthrough, multiple images, full pipeline |
| `nextcloud_client.py` | 21 | URL validation, folders, feeds, feed items, filtering, version check, fallback, HTTP errors, batch operations |
| `formats` | 22 | Dispatch (unknown format, supported list), md-inline rendering, txt rendering, json rendering, pdf rendering |
| **Total** | **98** | All public APIs exercised via mocked HTTP (`responses`) |