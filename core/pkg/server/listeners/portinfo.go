package listeners

import (
	"fmt"
	"os"
)

type PortInfo struct {
	// UnixPath is the path of a Unix domain socket for connecting to
	// the server.
	//
	// An empty string means a Unix domain socket cannot be used to connect.
	UnixPath string

	// LocalhostPort is the port for connecting to the server via localhost.
	//
	// The zero value means localhost cannot be used to connect.
	LocalhostPort int
}

// WriteToFile saves the port information to the file at the given path.
func (info PortInfo) WriteToFile(path string) error {
	// We write to a temporary file first then rename it to the target path
	// so that if another process is also writing to the file, the contents
	// don't get mangled.
	tempFile := fmt.Sprintf("%s.tmp", path)

	if err := info.writeToNewFile(tempFile); err != nil {
		return err
	}

	if err := os.Rename(tempFile, path); err != nil {
		return fmt.Errorf("server/listeners: rename port file: %v", err)
	}

	return nil
}

// writeToNewFile creates a new file and writes the info to it.
func (info PortInfo) writeToNewFile(path string) (err error) {
	f, err := os.Create(path)
	if err != nil {
		return fmt.Errorf("server/listeners: create port file: %v", err)
	}

	defer func() {
		closeErr := f.Close()
		if err == nil && closeErr != nil {
			err = fmt.Errorf("server/listeners: close port file: %v", closeErr)
		}
	}()

	if info.UnixPath != "" {
		if _, err = fmt.Fprintf(f, "unix=%s\n", info.UnixPath); err != nil {
			return fmt.Errorf(
				"server/listeners: write Unix path to port file: %v", err)
		}
	}
	if info.LocalhostPort != 0 {
		if _, err = fmt.Fprintf(f, "sock=%d\n", info.LocalhostPort); err != nil {
			return fmt.Errorf("server/listeners: write port to port file: %v", err)
		}
	}

	if _, err = f.WriteString("EOF"); err != nil {
		return fmt.Errorf("server/listeners: write EOF to port file: %v", err)
	}

	return nil
}
