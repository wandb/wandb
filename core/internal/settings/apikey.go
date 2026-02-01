package settings

import (
	"bufio"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

// readNetrcAPIKey reads the API key from the user's netrc file for the given base URL.
//
// The netrc file is located at:
//   - The path specified by the NETRC environment variable, or
//   - ~/.netrc on Unix-like systems
//   - ~/_netrc on Windows
//
// Returns the API key (password field in netrc) if found, or an empty string otherwise.
func readNetrcAPIKey(baseURL string) (string, error) {
	netrcPath := getNetrcPath()
	if netrcPath == "" {
		return "", nil
	}

	parsedURL, err := url.Parse(baseURL)
	if err != nil {
		return "", fmt.Errorf("invalid base URL %q: %w", baseURL, err)
	}
	host := parsedURL.Hostname()
	if host == "" {
		return "", fmt.Errorf("could not extract hostname from base URL %q", baseURL)
	}

	file, err := os.Open(netrcPath)
	if err != nil {
		return "", fmt.Errorf("error opening netrc file: %w", err)
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	var currentMachine string
	var password string

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		// Skip empty lines and comments
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}

		fields := strings.Fields(line)
		for i := 0; i < len(fields); i++ {
			switch fields[i] {
			case "machine":
				if i+1 < len(fields) {
					currentMachine = fields[i+1]
					i++
				}
			case "password":
				if i+1 < len(fields) && currentMachine == host {
					password = fields[i+1]
					return password, nil
				}
				i++
			case "login":
				i++
			}
		}
	}

	if err := scanner.Err(); err != nil {
		return "", fmt.Errorf("error reading netrc file: %w", err)
	}

	return "", nil
}

// getNetrcPath returns the path to the netrc file.
//
// It checks the following locations in order:
//  1. NETRC environment variable
//  2. ~/.netrc (Unix) or ~/_netrc (Windows) if they exist
//  3. Platform-specific default
func getNetrcPath() string {
	if netrcPath := os.Getenv("NETRC"); netrcPath != "" {
		return expandHome(netrcPath)
	}

	homeDir, err := os.UserHomeDir()
	if err != nil {
		return ""
	}

	var netrcPath string
	if runtime.GOOS == "windows" {
		netrcPath = filepath.Join(homeDir, "_netrc")
	} else {
		netrcPath = filepath.Join(homeDir, ".netrc")
	}

	if _, err := os.Stat(netrcPath); err == nil {
		return netrcPath
	}
	return ""
}
