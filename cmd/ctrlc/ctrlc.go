package main

import (
	"github.com/ctrlplanedev/cli/cmd/ctrlc/root"
)

func main() {
	root.NewRootCmd().Execute()
}
