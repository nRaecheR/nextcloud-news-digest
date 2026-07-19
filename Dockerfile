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