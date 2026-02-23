FROM swift:6.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV REPO_ROOT=/repo
ENV SEMANTIC_INDEX_STATE_DIR=/state

WORKDIR /app

COPY semantic_index /app/semantic_index
COPY docker/mcp-entrypoint.sh /usr/local/bin/semantic-index-mcp

RUN chmod +x /usr/local/bin/semantic-index-mcp \
    && mkdir -p /state

ENTRYPOINT ["semantic-index-mcp"]
CMD ["serve-mcp","--bootstrap-index","--watch","--watch-interval","2.0"]
