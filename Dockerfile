FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/opencode-core
COPY pyproject.toml README.md ./
COPY ai ./ai
COPY docs ./docs
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 opencode \
    && mkdir -p /workspace /state \
    && chown -R opencode:opencode /workspace /state

USER opencode
VOLUME ["/workspace", "/state"]
WORKDIR /workspace
ENTRYPOINT ["opencode-core"]
CMD ["--worker-loop", "--project-root", "/workspace", "--queue-db", "/state/queue.sqlite3", "--workers", "2"]
