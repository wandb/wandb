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

// portfile is used to communicate the port number of the gRPC service
// started by the gpu_stats binary to the wandb-core process.
type portfile struct {
	path string
}

func NewPortfile() *portfile {
	file, err := os.CreateTemp("", ".system-monitor-portfile")
	if err != nil {
		return nil
	}
	file.Close()
	return &portfile{path: file.Name()}
}

// Read reads the port number from the portfile.
func (p *portfile) Read(ctx context.Context) (int, error) {
	for {
		select {
		case <-ctx.Done():
			return 0, fmt.Errorf("timeout reading portfile %s", p.path)
		default:
			port, err := p.readFile()
			if err != nil {
				time.Sleep(100 * time.Millisecond)
				continue
			}
			return port, nil
		}
	}
}

func (p *portfile) readFile() (int, error) {
	file, err := os.Open(p.path)
	if err != nil {
		return 0, err
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	if scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		port, err := strconv.Atoi(line)
		if err != nil {
			return 0, fmt.Errorf("failed to parse integer: %v", err)
		}
		return port, nil
	}

	if err := scanner.Err(); err != nil {
		return 0, fmt.Errorf("error reading file: %v", err)
	}

	return 0, fmt.Errorf("no data found in file %s", p.path)
}

func (p *portfile) Delete() error {
	return os.Remove(p.path)
}
