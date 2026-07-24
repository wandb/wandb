package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/filestream/encodingbench"
)

func main() {
	defaultDir := filepath.Join("internal", "filestream", "encodingbench", "testdata")
	out := flag.String("out", defaultDir, "output directory for fixture corpus")
	flag.Parse()

	if err := encodingbench.ExportFixtures(*out); err != nil {
		fmt.Fprintf(os.Stderr, "export fixtures: %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("wrote fixtures to %s\n", *out)
}
