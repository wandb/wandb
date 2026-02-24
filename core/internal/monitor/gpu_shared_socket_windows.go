//go:build windows

package monitor

import (
	"fmt"

	"google.golang.org/grpc"
)

func connectOrStartSharedCollector(string, bool) (*grpc.ClientConn, error) {
	return nil, fmt.Errorf("monitor: shared gpu-stats not supported on Windows")
}
