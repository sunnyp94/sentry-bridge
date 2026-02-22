package redis

import (
	"context"
	"encoding/json"
	"log"
	"time"

	"github.com/redis/go-redis/v9"
)

// Publisher pushes brain events to a Redis Stream.
type Publisher struct {
	client *redis.Client
	stream string
}

// NewPublisher creates a publisher. addr is Redis address (e.g. "localhost:6379" or full URL).
func NewPublisher(addr, stream string) (*Publisher, error) {
	opts, err := redis.ParseURL(addr)
	if err != nil {
		opts = &redis.Options{Addr: addr}
	}
	client := redis.NewClient(opts)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := client.Ping(ctx).Err(); err != nil {
		return nil, err
	}
	return &Publisher{client: client, stream: stream}, nil
}

// BrainEvent is the envelope for every message (type + ts + payload).
type BrainEvent struct {
	Type    string      `json:"type"`
	TS      string      `json:"ts"`
	Payload interface{} `json:"payload"`
}

// Publish sends a brain event to the stream. Payload is JSON-serialized.
func (p *Publisher) Publish(ctx context.Context, event BrainEvent) error {
	if event.TS == "" {
		event.TS = time.Now().UTC().Format(time.RFC3339Nano)
	}
	payloadBytes, err := json.Marshal(event.Payload)
	if err != nil {
		return err
	}
	return p.client.XAdd(ctx, &redis.XAddArgs{
		Stream: p.stream,
		Values: map[string]interface{}{
			"type":    event.Type,
			"ts":      event.TS,
			"payload": string(payloadBytes),
		},
	}).Err()
}

// PublishJSON sends a pre-built payload map as the event (type and ts added if missing).
func (p *Publisher) PublishJSON(ctx context.Context, eventType string, payload map[string]interface{}) error {
	if payload == nil {
		payload = make(map[string]interface{})
	}
	payload["ts"] = time.Now().UTC().Format(time.RFC3339Nano)
	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return p.client.XAdd(ctx, &redis.XAddArgs{
		Stream: p.stream,
		Values: map[string]interface{}{
			"type":    eventType,
			"ts":      payload["ts"],
			"payload": string(payloadBytes),
		},
	}).Err()
}

// Close closes the Redis client.
func (p *Publisher) Close() error {
	return p.client.Close()
}

// NoopPublisher is used when Redis is not configured; all Publish calls no-op.
type NoopPublisher struct{}

func (NoopPublisher) Publish(ctx context.Context, event BrainEvent) error { return nil }
func (NoopPublisher) PublishJSON(ctx context.Context, eventType string, payload map[string]interface{}) error {
	return nil
}
func (NoopPublisher) Close() error { return nil }

// PublisherInterface allows main to use either real or noop publisher.
type PublisherInterface interface {
	Publish(ctx context.Context, event BrainEvent) error
	PublishJSON(ctx context.Context, eventType string, payload map[string]interface{}) error
	Close() error
}

// Ensure both implement the interface
var (
	_ PublisherInterface = (*Publisher)(nil)
	_ PublisherInterface = NoopPublisher{}
)

// LogErr logs a Redis publish error without failing the stream.
func LogErr(err error, eventType string) {
	if err != nil {
		log.Printf("[redis] %s publish error: %v", eventType, err)
	}
}
