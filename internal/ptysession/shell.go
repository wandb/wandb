package ptysession

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"
)

func getLinuxUserShell(username string) (string, error) {
	file, err := os.Open("/etc/passwd")
	if err == nil {
		defer file.Close()
		scanner := bufio.NewScanner(file)
		for scanner.Scan() {
			line := scanner.Text()
			fields := strings.Split(line, ":")
			if len(fields) < 7 {
				continue
			}
			if fields[0] == username {
				shell := fields[6]
				return shell, nil
			}
		}
		if err := scanner.Err(); err != nil {
			return "", err
		}
	}

	return "", fmt.Errorf("user %s not found in /etc/passwd", username)
}

func getDarwinUserShell(username string) (string, error) {
	cmd := exec.Command("dscl", ".", "-read", fmt.Sprintf("/Users/%s", username), "UserShell")
	output, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("failed to get user shell on macOS: %v", err)
	}

	// Parse the output
	lines := strings.Split(string(output), "\n")
	for _, line := range lines {
		if strings.HasPrefix(line, "UserShell:") {
			fields := strings.Fields(line)
			if len(fields) >= 2 {
				return fields[1], nil
			}
		}
	}
	return "", fmt.Errorf("shell not found in dscl output")
}

func getUserShell(username string) (string, error) {
	if runtime.GOOS == "linux" {
		return getLinuxUserShell(username)
	}

	if runtime.GOOS == "darwin" {
		return getDarwinUserShell(username)
	}

	return "", fmt.Errorf("operating system %s not supported", runtime.GOOS)
}
