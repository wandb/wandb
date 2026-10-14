//go:build !linux && !darwin

package monitor

import (
	"github.com/shirou/gopsutil/v4/process"
)

// openWandbFiles is not supported on this platform.
func openWandbFiles(*process.Process) []string {
	return nil
}
