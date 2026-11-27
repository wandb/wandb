package leet

import (
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestDeriveRates(t *testing.T) {
	prev := map[string]float64{"network.recv": 1000, "disk.disk0.in": 1, "disk.disk0.out": 5}
	cur := map[string]float64{
		"network.recv":   5096,
		"network.sent":   10,
		"disk.disk0.in":  2,
		"disk.disk0.out": 4,
		"memory_percent": 50,
	}

	deriveRates(prev, cur, 2*time.Second)

	require.Equal(t, map[string]float64{
		"network.recvBps":    2048,
		"disk.disk0.readBps": 512 * 1024,
		"memory_percent":     50,
	}, cur)
}
