# Build Go binary (static)
FROM golang:1.21-alpine AS build
WORKDIR /src
COPY go-engine/go.mod go-engine/go.sum ./
RUN go mod download
COPY go-engine/ ./
RUN CGO_ENABLED=0 go build -o /out/sentry-bridge .

# Run: Go binary + Python brain with FinBERT (Debian base for torch/transformers)
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/sentry-bridge /app/sentry-bridge
COPY python-brain/ /app/python-brain/
WORKDIR /app
RUN pip install --no-cache-dir -r /app/python-brain/requirements.txt
# Go starts on boot; reads BRAIN_CMD from env and launches Python brain (FinBERT + strategy)
ENTRYPOINT ["/app/sentry-bridge"]
