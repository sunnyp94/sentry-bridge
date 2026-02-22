package brain

import (
	"bufio"
	"encoding/json"
	"io"
	"log/slog"
	"os/exec"
	"strings"
	"sync"
	"time"
)

// Pipe starts a child process (the Python brain) and sends events as newline-delimited JSON to its stdin.
// Keeps the brain closest to the data (same machine, no Redis in the hot path).
type Pipe struct {
	cmd       *exec.Cmd
	stdinPipe io.WriteCloser
	stdin     *bufio.Writer
	mu        sync.Mutex
	closed    bool
}

// StartPipe starts the brain process. cmdLine is the full command, e.g. "python3 python-brain/consumer.py".
// Run from project root so paths in cmdLine resolve.
func StartPipe(cmdLine string) (*Pipe, error) {
	parts := splitCmd(cmdLine)
	if len(parts) == 0 {
		return nil, nil
	}
	cmd := exec.Command(parts[0], parts[1:]...)
	cmd.Stderr = nil
	stdinPipe, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	p := &Pipe{
		cmd:       cmd,
		stdinPipe: stdinPipe,
		stdin:     bufio.NewWriter(stdinPipe),
	}
	go func() {
		_ = cmd.Wait()
		p.mu.Lock()
		p.closed = true
		p.mu.Unlock()
		slog.Info("brain process exited")
	}()
	return p, nil
}

// Send writes one event as a single JSON line to the brain's stdin.
func (p *Pipe) Send(typ string, payload interface{}) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.closed {
		return nil
	}
	ts := time.Now().UTC().Format(time.RFC3339Nano)
	obj := map[string]interface{}{"type": typ, "ts": ts, "payload": payload}
	line, err := json.Marshal(obj)
	if err != nil {
		return err
	}
	if _, err := p.stdin.Write(line); err != nil {
		return err
	}
	if err := p.stdin.WriteByte('\n'); err != nil {
		return err
	}
	return p.stdin.Flush()
}

// Close closes stdin and waits for the process to exit.
func (p *Pipe) Close() error {
	p.mu.Lock()
	if p.closed {
		p.mu.Unlock()
		return nil
	}
	p.closed = true
	_ = p.stdin.Flush()
	_ = p.stdinPipe.Close()
	p.mu.Unlock()
	return p.cmd.Wait()
}

// splitCmd splits the brain command line on spaces so exec.Command gets separate program and args.
func splitCmd(s string) []string {
	var parts []string
	for _, p := range strings.Fields(s) {
		parts = append(parts, p)
	}
	return parts
}
