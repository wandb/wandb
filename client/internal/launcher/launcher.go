// package launcher manages the execution of a core server
package launcher

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"sync/atomic"
	"time"
)

const (
	localHost = "127.0.0.1"
)

type Launcher struct {
	// portFilename is the path to the file that contains the port number
	portFilename string

	// command is the command that is being run
	command *forkExecCmd

	// started is an atomic boolean that indicates whether the session has been
	// started
	started *atomic.Bool

	// address is the address of the server that the session is connected to
	address string
}

func New() *Launcher {
	return &Launcher{
		started: &atomic.Bool{},
	}
}

// Launch starts the core server and waits for the port file to be created
func (l *Launcher) Launch(path string) error {
	if err := l.launchCommand(path); err != nil {
		return err
	}

	port, err := l.getPort()
	if err != nil {
		return err
	}
	l.address = fmt.Sprintf("%s:%d", localHost, port)
	l.started.Store(true)
	return nil
}

// Close gracefully shuts down the core server
func (l *Launcher) Close() error {
	if !l.started.Load() {
		return nil
	}

	// closing on nil is a no-op
	if l.command == nil {
		return nil
	}
	// close the internal process and log the exit code
	if err := l.command.wait(); err != nil {
		return err
	}

	l.started.Store(false)
	return nil
}

// Address returns the address of the wandb-core server that the session is
// connected to
func (l *Launcher) Address() string {
	return l.address
}

// getPort waits for the port file to be created and reads the port number
func (l *Launcher) getPort() (int, error) {
	defer os.Remove(l.portFilename)

	// wait for 30 seconds for port
	for i := 0; i < 3000; i++ {
		val, err := extractPort(l.portFilename)
		if err == nil {
			return val, err
		}
		time.Sleep(10 * time.Millisecond)
	}
	return 0, errors.New("prob")
}

// prepTempfile creates a temporary file to store the port number
func (l *Launcher) prepTempfile() {
	file, err := os.CreateTemp("", ".core-portfile-")
	if err != nil {
		panic(err)
	}
	file.Close()
	l.portFilename = file.Name()
}

// launchCommand launches a command with the port filename as an argument
func (l *Launcher) launchCommand(command string) error {
	l.prepTempfile()
	args := []string{"--port-filename", l.portFilename}
	cmd, err := execCommand(command, args)
	if err != nil {
		return err
	}
	l.command = cmd
	return nil
}

// readLines reads a whole file into memory and returns a slice of its lines.
func readLines(path string) ([]string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var lines []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}
	return lines, scanner.Err()
}

// extractPort reads a file and extracts the port number from the first line
// of the file.
func extractPort(path string) (int, error) {
	lines, err := readLines(path)
	if err != nil {
		return 0, err
	}
	if len(lines) < 2 {
		return 0, errors.New("expecting at least 2 lines")
	}
	pair := strings.SplitN(lines[0], "=", 2)
	if len(pair) != 2 {
		return 0, errors.New("expecting split into 2")
	}
	if pair[0] != "sock" {
		return 0, errors.New("expecting sock key")
	}
	intVar, err := strconv.Atoi(pair[1])
	if err != nil {
		return 0, err
	}
	return intVar, nil
}
