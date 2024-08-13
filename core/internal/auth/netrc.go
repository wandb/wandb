// Modified from: https://go.dev/src/cmd/go/internal/auth/netrc.go

// Copyright 2019 The Go Authors. All rights reserved.
// Use of this source code is governed by a BSD-style
// license that can be found in the LICENSE file.

package auth

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

type netrcLine struct {
	Machine  string
	Login    string
	Password string
}

func parseNetrc(data string) []netrcLine {
	// See https://www.gnu.org/software/inetutils/manual/html_node/The-_002enetrc-file.html
	// for documentation on the .netrc format.
	var nrc []netrcLine
	var l netrcLine
	inMacro := false
	for _, line := range strings.Split(data, "\n") {
		if inMacro {
			if line == "" {
				inMacro = false
			}
			continue
		}

		f := strings.Fields(line)
		i := 0
		for ; i < len(f)-1; i += 2 {
			// Reset at each "machine" token.
			// “The auto-login process searches the .netrc file for a machine token
			// that matches […]. Once a match is made, the subsequent .netrc tokens
			// are processed, stopping when the end of file is reached or another
			// machine or a default token is encountered.”
			switch f[i] {
			case "machine":
				l = netrcLine{Machine: f[i+1]}
			case "default":
				break
			case "login":
				l.Login = f[i+1]
			case "password":
				l.Password = f[i+1]
			case "macdef":
				// “A macro is defined with the specified name; its contents begin with
				// the next .netrc line and continue until a null line (consecutive
				// new-line characters) is encountered.”
				inMacro = true
			}
			if l.Machine != "" && l.Login != "" && l.Password != "" {
				nrc = append(nrc, l)
				l = netrcLine{}
			}
		}

		if i < len(f) && f[i] == "default" {
			// “There can be only one default token, and it must be after all machine tokens.”
			break
		}
	}

	return nrc
}

func NetrcPath() (string, error) {
	if env := os.Getenv("NETRC"); env != "" {
		return env, nil
	}
	dir, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}

	// if either .netrc or _netrc file exists, use it
	for _, name := range []string{".netrc", "_netrc"} {
		if _, err := os.Stat(filepath.Join(dir, name)); err == nil {
			return filepath.Join(dir, name), nil
		}
	}

	// otherwise, use _netrc on Windows and .netrc on other systems
	base := ".netrc"
	if runtime.GOOS == "windows" {
		base = "_netrc"
	}
	return filepath.Join(dir, base), nil
}

func ReadNetrc() ([]netrcLine, error) {
	path, err := NetrcPath()
	if err != nil {
		// netrcErr = err
		return []netrcLine{}, err
	}

	data, err := os.ReadFile(path)
	if err != nil {
		return []netrcLine{}, err
	}

	return parseNetrc(string(data)), nil
}

func GetNetrcLogin(machine string) (string, string, error) {
	netrcLines, err := ReadNetrc()
	if err != nil {
		return "", "", err
	}
	for _, l := range netrcLines {
		if l.Machine == machine {
			return l.Login, l.Password, nil
		}
	}
	return "", "", fmt.Errorf("no entry for %s in %s", machine, netrcLines)
}
