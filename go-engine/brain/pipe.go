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
// If the brain process exits unexpectedly, it is restarted after a short backoff so the engine can run
// continuously without gaps. Close() stops the process and disables restart.
type Pipe struct {
	cmd       *exec.Cmd
	stdinPipe io.WriteCloser
	stdin     *bufio.Writer
	mu        sync.Mutex
	closed    bool
	shutdown  bool
	cmdLine   string
	done      chan struct{}
	doneOnce  sync.Once
}

const brainRestartBackoff = 5 * time.Second

// StartPipe starts the brain process. cmdLine is the full command, e.g. "python3 python-brain/consumer.py".
// Run from project root so paths in cmdLine resolve. If the process exits, it is restarted after brainRestartBackoff
// until Close() is called.
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
		cmdLine:   cmdLine,
		done:      make(chan struct{}),
	}
	go p.supervisor()
	return p, nil
}

// supervisor waits for the current brain process to exit; if not shutdown, restarts after backoff.
// Edge cases: (1) cmd may be nil after a failed restart (we cleared it to avoid double-Wait).
// (2) done is closed exactly once via doneOnce so Close() always unblocks.
func (p *Pipe) supervisor() {
	defer p.doneOnce.Do(func() { close(p.done) })
	for {
		p.mu.Lock()
		cmd := p.cmd
		p.mu.Unlock()
		if cmd != nil {
			_ = cmd.Wait()
		}
		p.mu.Lock()
		if p.shutdown {
			p.closed = true
			p.mu.Unlock()
			slog.Info("brain process stopped (shutdown)")
			return
		}
		p.closed = true
		p.mu.Unlock()
		slog.Info("brain process exited; restarting", "backoff", brainRestartBackoff)

		time.Sleep(brainRestartBackoff)

		p.mu.Lock()
		if p.shutdown {
			p.mu.Unlock()
			return
		}
		p.mu.Unlock()

		parts := splitCmd(p.cmdLine)
		if len(parts) == 0 {
			return
		}
		newCmd := exec.Command(parts[0], parts[1:]...)
		newCmd.Stderr = nil
		newStdin, err := newCmd.StdinPipe()
		if err != nil {
			slog.Error("brain restart stdin pipe failed", "err", err)
			p.mu.Lock()
			p.cmd = nil
			p.stdinPipe = nil
			p.stdin = nil
			p.mu.Unlock()
			continue
		}
		if err := newCmd.Start(); err != nil {
			slog.Error("brain restart start failed", "err", err)
			p.mu.Lock()
			p.cmd = nil
			p.stdinPipe = nil
			p.stdin = nil
			p.mu.Unlock()
			continue
		}
		p.mu.Lock()
		p.cmd = newCmd
		p.stdinPipe = newStdin
		p.stdin = bufio.NewWriter(newStdin)
		p.closed = false
		p.mu.Unlock()
		slog.Info("brain process restarted", "cmd", p.cmdLine)
	}
}

// Send writes one event as a single JSON line to the brain's stdin.
func (p *Pipe) Send(typ string, payload interface{}) error {
	if p == nil {
		return nil
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.closed || p.stdin == nil {
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

// Close signals shutdown, closes stdin so the process exits, and waits for the supervisor to finish.
func (p *Pipe) Close() error {
	if p == nil {
		return nil
	}
	p.mu.Lock()
	if p.shutdown {
		p.mu.Unlock()
		return nil
	}
	p.shutdown = true
	if !p.closed && p.stdinPipe != nil {
		p.closed = true
		_ = p.stdin.Flush()
		_ = p.stdinPipe.Close()
	}
	p.mu.Unlock()
	<-p.done
	return nil
}

// splitCmd splits the brain command line on spaces so exec.Command gets separate program and args.
func splitCmd(s string) []string {
	var parts []string
	for _, p := range strings.Fields(s) {
		parts = append(parts, p)
	}
	return parts
}
