// package launcher manages the execution of a core server
package launcher

import (
	"bufio"
	"errors"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/wandb/wandb/gowandb/internal/execbin"
)

// readLines reads a whole file into memory
// and returns a slice of its lines.
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

type Launcher struct {
	portFilename string
}

func (l *Launcher) tryport() (int, error) {
	lines, err := readLines(l.portFilename)
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

func (l *Launcher) Getport() (int, error) {
	defer os.Remove(l.portFilename)

	// wait for 30 seconds for port
	for i := 0; i < 3000; i++ {
		val, err := l.tryport()
		if err == nil {
			return val, err
		}
		time.Sleep(10 * time.Millisecond)
	}
	return 0, errors.New("prob")
}

func (l *Launcher) prepTempfile() {
	file, err := os.CreateTemp("", ".core-portfile")
	if err != nil {
		panic(err)
	}
	file.Close()
	l.portFilename = file.Name()
}

func (l *Launcher) LaunchCommand(command string) (*execbin.ForkExecCmd, error) {
	l.prepTempfile()
	args := []string{"--port-filename", l.portFilename}
	cmd, err := execbin.ForkExecCommand(command, args)
	if err != nil {
		panic(err)
	}
	return cmd, err
}

func (l *Launcher) LaunchBinary(filePayload []byte) (*execbin.ForkExecCmd, error) {
	l.prepTempfile()

	args := []string{"--port-filename", l.portFilename}
	cmd, err := execbin.ForkExec(filePayload, args)
	if err != nil {
		panic(err)
	}
	return cmd, err
}

func NewLauncher() *Launcher {
	return &Launcher{}
}
