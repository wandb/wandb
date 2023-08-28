package main

import (
	_ "embed"
)

// generate nexus binary and embed into this package
//
//go:generate go build -C ../.. -o lib/core/embed-nexus.bin cmd/nexus/main.go
//go:embed embed-nexus.bin
var coreBinary []byte
