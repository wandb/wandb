package main

import (
	_ "embed"
)

// generate nexus binary and embed into this package
//
//go:generate go build -C ../.. -o lib/core/nexusimage.bin cmd/nexus/main.go
//go:embed nexusimage.bin
var nexusImage []byte
