package monitor

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// portfile is used to communicate the token of the gRPC service
// started by the gpu_stats binary to the wandb-core process.
type portfile struct {
	Path string
}

func NewPortfile() *portfile {
	file, err := os.CreateTemp("", "wandb-system-monitor-portfile-*")
	if err != nil {
		return nil
	}
	_ = file.Close()
	return &portfile{Path: file.Name()}
}

// Read reads the target URI from the portfile.
func (p *portfile) Read(ctx context.Context) (string, error) {
	for {
		select {
		case <-ctx.Done():
			return "", fmt.Errorf("timeout reading portfile %s", p.Path)
		default:
			target, err := p.ReadFile()
			if err != nil {
				time.Sleep(100 * time.Millisecond)
				continue
			}
			return target, nil
		}
	}
}

// readFile reads a portfile to find a TCP port or a Unix socket path,
// then returns a gRPC-compatible target URI string.
func (p *portfile) ReadFile() (string, error) {
	file, err := os.Open(p.Path)
	if err != nil {
		return "", err
	}
	defer func() {
		_ = file.Close()
	}()

	scanner := bufio.NewScanner(file)
	if !scanner.Scan() {
		if err := scanner.Err(); err != nil {
			return "", fmt.Errorf("error reading portfile: %v", err)
		}
		return "", fmt.Errorf("portfile is empty: %s", p.Path)
	}

	line := scanner.Text()

	if path, found := strings.CutPrefix(line, "unix="); found {
		return fmt.Sprintf("unix:%s", path), nil
	}

	if portStr, found := strings.CutPrefix(line, "sock="); found {
		port, err := strconv.Atoi(portStr)
		if err != nil {
			return "", fmt.Errorf("invalid port in portfile: %q, %v", portStr, err)
		}
		return fmt.Sprintf("127.0.0.1:%d", port), nil
	}

	return "", fmt.Errorf("unknown format in portfile: %s", p.Path)
}

func (p *portfile) Delete() error {
	return os.Remove(p.Path)
}
