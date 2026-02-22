# Build Go binary
FROM golang:1.21-alpine AS build
WORKDIR /src
COPY go-engine/go.mod go-engine/go.sum ./
RUN go mod download
COPY go-engine/ ./
RUN CGO_ENABLED=0 go build -o /out/sentry-bridge .

# Run: Go binary + Python brain
FROM alpine:3.19
RUN apk add --no-cache python3
COPY --from=build /out/sentry-bridge /app/sentry-bridge
COPY python-brain/ /app/python-brain/
WORKDIR /app
ENTRYPOINT ["/app/sentry-bridge"]
