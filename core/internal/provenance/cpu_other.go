//go:build !linux

package provenance

func collectorCPU() func() *int64 { return func() *int64 { return nil } }
