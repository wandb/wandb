package monitor

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"regexp"
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
	file, err := os.CreateTemp("", ".wandb-system-monitor-portfile-*")
	if err != nil {
		return nil
	}
	_ = file.Close()
	return &portfile{path: file.Name()}
}

// Read reads the port number from the portfile.
func (p *portfile) Read(ctx context.Context) (string, error) {
	for {
		select {
		case <-ctx.Done():
			return "", fmt.Errorf("timeout reading portfile %s", p.path)
		default:
			target, err := p.readFile()
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
func (p *portfile) readFile() (string, error) {
	file, err := os.Open(p.path)
	if err != nil {
		return "", err
	}
	defer func() {
		_ = file.Close()
	}()

	unixPathRe := regexp.MustCompile(`unix=(.+)`)
	tcpPortRe := regexp.MustCompile(`sock=(\d+)`)

	scanner := bufio.NewScanner(file)
	if scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		fmt.Println("+++ ", line)

		matchUnixPath := unixPathRe.FindStringSubmatch(line)
		if matchUnixPath != nil {
			fmt.Println(matchUnixPath)
			return fmt.Sprintf("unix://%s", matchUnixPath[1]), nil
		}

		matchTcpPort := tcpPortRe.FindStringSubmatch(line)
		if matchTcpPort != nil {
			fmt.Println(matchTcpPort)
			port, err := strconv.Atoi(matchTcpPort[1])
			if err != nil {
				return "", fmt.Errorf("failed to parse TCP port number: %v", err)
			}
			return fmt.Sprintf("127.0.0.1:%d", port), nil
		}
	}

	if err := scanner.Err(); err != nil {
		return "", fmt.Errorf("error reading file: %v", err)
	}

	return "", fmt.Errorf("no data found in file %s", p.path)
}

func (p *portfile) Delete() error {
	return os.Remove(p.path)
}
