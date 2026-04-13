FROM python:3.12-slim

LABEL maintainer="arunrajiah"
LABEL description="cctvQL — Conversational query layer for CCTV systems"

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[mqtt,onvif]"

# Copy source
COPY cctvql/ ./cctvql/
COPY config/example.yaml ./config/config.yaml

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["cctvql", "serve", "--host", "0.0.0.0", "--port", "8000"]
