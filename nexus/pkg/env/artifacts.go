package env

import (
	"os"
	"path/filepath"
)

func GetArtifactDir() (artifactDir string, rerr error) {
	artifactDir = os.Getenv("WANDB_ARTIFACT_DIR")
	cwd, err := os.Getwd()
	if err != nil {
		cwd = "."
	}
	if artifactDir == "" {
		return filepath.Join(cwd, "artifacts"), nil
	}
	return artifactDir, nil
}
