package main

import (
	"os"
	"path/filepath"

	"github.com/wandb/wandb/experimental/go-sdk/pkg/runconfig"
	"github.com/wandb/wandb/experimental/go-sdk/pkg/settings"
	"github.com/wandb/wandb/experimental/go-sdk/pkg/wandb"
)

func main() {
	os.Setenv("WANDB_TAGS", "tag1,tag2,tag3")
	os.Setenv("WANDB_NOTES", "bla bla")
	os.Setenv("WANDB_CONSOLE", "off")
	os.Setenv("WANDB_RESUME", "allow")

	// get the core binary path from the current file path
	coreBinaryPath := filepath.Join(
		filepath.Dir(os.Args[0]),
		"wandb-core",
	)
	wandb.Setup(&wandb.SessionParams{
		CoreExecPath: coreBinaryPath,
	})

	run, err := wandb.Init(
		&wandb.RunParams{
			Config: &runconfig.Config{},
			Settings: &settings.Settings{
				RunProject: "test",
				RunGroup:   "test",
			},
		},
	)
	defer wandb.Teardown()

	defer run.Finish()
	if err != nil {
		panic(err)
	}

	run.Log(map[string]any{"x": 1}, true)
}
