# Build Go binary (static)
FROM golang:1.21-alpine AS build
WORKDIR /src
COPY go-engine/go.mod go-engine/go.sum ./
RUN go mod download
COPY go-engine/ ./
RUN go vet ./... && CGO_ENABLED=0 go build -o /out/sentry-bridge .

# Run: Go binary + Python brain with FinBERT (Debian base for torch/transformers)
FROM python:3.11-slim
ARG GIT_SHA=
LABEL org.opencontainers.image.revision="${GIT_SHA}"
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/sentry-bridge /app/sentry-bridge
COPY python-brain/ /app/python-brain/
COPY data/ /app/data/
WORKDIR /app
# CPU-only torch to avoid multi-GB CUDA deps (saves disk; FinBERT runs on CPU)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r /app/python-brain/requirements.txt
# Validate Python: compile all .py (syntax) and verify brain package imports (fail build on errors)
RUN python3 -m compileall -q /app/python-brain \
    && python3 -c "import sys; sys.path.insert(0, '/app/python-brain'); from brain import config; from brain.strategy import decide; from brain.executor import place_order, get_account_equity, close_all_positions_from_api, close_all_positions; print('brain OK')"
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
# When ACTIVE_SYMBOLS_FILE is set, entrypoint runs the scanner first, then starts Go (which reads tickers from that file).
ENTRYPOINT ["/app/entrypoint.sh", "/app/sentry-bridge"]
