# Dependencies are installed in a separate stage so application edits don't
# invalidate the (slow) pip layer.
FROM python:3.12-slim AS deps

WORKDIR /install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install/prefix -r requirements.txt


FROM python:3.12-slim

LABEL org.opencontainers.image.title="soulseek-web" \
      org.opencontainers.image.description="A minimalist web UI for slskd" \
      org.opencontainers.image.source="https://github.com/sgutierrezbe/soulseek-web" \
      org.opencontainers.image.licenses="MIT"

# Settings and the cover cache land in /config, so one mounted volume persists
# everything the app writes and the image itself stays read-only.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CONFIG_DIR=/config

COPY --from=deps /install/prefix /usr/local

WORKDIR /app
COPY . .

RUN useradd --system --uid 1000 --create-home slskweb \
 && mkdir -p /config \
 && chown -R slskweb:slskweb /app /config

USER slskweb
VOLUME ["/config"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
