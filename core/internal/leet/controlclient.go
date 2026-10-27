package leet

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// ErrSessionReplyError is returned by SessionRequest after printing a reply
// that carries an error.
var ErrSessionReplyError = errors.New("the request failed")

// SessionRequest sends one JSON-RPC request to the LEET showing wandbDir
// and prints its reply line to w.
func SessionRequest(wandbDir, request string, w io.Writer) error {
	var compact bytes.Buffer
	if err := json.Compact(&compact, []byte(request)); err != nil {
		return badRequest("--request must be a JSON-RPC request: %v", err)
	}

	noSession := &QueryError{
		Code: "no_session",
		Message: fmt.Sprintf(
			"no LEET is showing %q: open it with wandb leet %s", wandbDir, wandbDir),
	}
	lock, err := readControlLock(filepath.Join(wandbDir, controlLockName))
	if err != nil {
		return noSession
	}
	conn, err := dialControl(lock, 15*time.Second)
	if err != nil {
		return noSession
	}
	defer conn.Close()

	reply, err := controlRoundTrip(conn, compact.String())
	if err != nil {
		return &QueryError{Code: "internal", Message: fmt.Sprintf("LEET did not reply: %v", err)}
	}
	fmt.Fprintln(w, reply)

	var parsed struct {
		Error *ControlError `json:"error"`
	}
	if json.Unmarshal([]byte(reply), &parsed) == nil && parsed.Error != nil {
		return ErrSessionReplyError
	}
	return nil
}

func readControlLock(path string) (controlLock, error) {
	var lock controlLock
	data, err := os.ReadFile(path)
	if err == nil {
		err = json.Unmarshal(data, &lock)
	}
	return lock, err
}

// dialControl connects to the LEET a lock names, sending the token first
// on TCP. The timeout covers the dial and the conversation that follows.
func dialControl(lock controlLock, timeout time.Duration) (net.Conn, error) {
	network, addr, _ := strings.Cut(lock.Address, ":")
	if network != "unix" && !strings.HasPrefix(lock.Address, "tcp:127.0.0.1:") {
		return nil, fmt.Errorf("control: bad address %q", lock.Address)
	}
	conn, err := net.DialTimeout(network, addr, timeout)
	if err != nil {
		return nil, err
	}
	_ = conn.SetDeadline(time.Now().Add(timeout))
	if lock.Token != nil {
		hello, _ := json.Marshal(map[string]string{"token": *lock.Token})
		if _, err := fmt.Fprintf(conn, "%s\n", hello); err != nil {
			conn.Close()
			return nil, err
		}
	}
	return conn, nil
}

// controlRoundTrip writes one request line and reads one reply line.
func controlRoundTrip(conn net.Conn, request string) (string, error) {
	if _, err := fmt.Fprintf(conn, "%s\n", request); err != nil {
		return "", err
	}
	reply, err := bufio.NewReader(conn).ReadString('\n')
	return strings.TrimSuffix(reply, "\n"), err
}
