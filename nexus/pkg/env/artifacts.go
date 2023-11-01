package env

import (
	"os"
	"path/filepath"
)

func GetArtifactDir() (artifactDir string, rerr error) {
	artifactDir = os.Getenv("WANDB_ARTIFACT_DIR")
	if artifactDir == "" {
		return filepath.Join(".", "artifacts"), nil
	}
	return artifactDir, nil
}
