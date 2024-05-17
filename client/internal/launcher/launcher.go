// package launcher manages the execution of a core server
package launcher

import (
	"bufio"
	"errors"
	"os"
	"strconv"
	"strings"
	"time"
)

type Launcher struct {
	portFilename string
	command      *forkExecCmd
}

func New() *Launcher {
	return &Launcher{}
}

// GetPort waits for the port file to be created and reads the port number
func (l *Launcher) GetPort() (int, error) {
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

// LaunchCommand launches a command with the port filename as an argument
func (l *Launcher) LaunchCommand(command string) error {
	l.prepTempfile()
	args := []string{"--port-filename", l.portFilename}
	cmd, err := execCommand(command, args)
	if err != nil {
		return err
	}
	l.command = cmd
	return nil
}

// Close waits for the command to finish
func (l *Launcher) Close() error {
	// closing on nil is a no-op
	if l.command == nil {
		return nil
	}
	return l.command.wait()
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
