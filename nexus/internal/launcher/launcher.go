package launcher

import (
	"bufio"
	_ "embed"
	"errors"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/wandb/wandb/nexus/internal/execbin"
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

func tryport() (int, error) {
	lines, err := readLines("junk-pid.txt")
	if err != nil {
		return 0, err
	}
	if len(lines) < 2 {
		return 0, errors.New("can't work with 1")
	}
	pair := strings.SplitN(lines[0], "=", 2)
	if len(pair) != 2 {
		return 0, errors.New("can't work with 3")
	}
	if pair[0] != "sock" {
		return 0, errors.New("can't work with 2")
	}
	intVar, err := strconv.Atoi(pair[1])
	if err != nil {
		return 0, err
	}
	return intVar, nil
}

func Getport() (int, error) {
	// wait for 30 seconds for port
	for i := 0; i < 3000; i++ {
		val, err := tryport()
		if err == nil {
			return val, err
		}
		time.Sleep(10 * time.Millisecond)
	}
	return 0, errors.New("prob")
}

func Launch(filePayload []byte) (*execbin.ForkExecCmd, error) {
	os.Remove("junk-pid.txt")

	args := []string{"--port-filename", "junk-pid.txt"}
	cmd, err := execbin.ForkExec(filePayload, args)
	if err != nil {
		panic(err)
	}
	return cmd, err
}
