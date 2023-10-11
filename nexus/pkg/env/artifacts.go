package env

import (
	"os"
	"path/filepath"
)

func GetArtifactDir() (artifactDir string, rerr error) {
	artifactDir = os.Getenv("WANDB_ARTIFACT_DIR")
	if artifactDir == "" {
		cwd, err := os.Getwd()
		if err != nil {
			return "", err
		}
		return filepath.Join(cwd, "artifacts"), nil
	}
	absArtifactDir, err := filepath.Abs(artifactDir)
	if err != nil {
		return "", err
	}
	return absArtifactDir, nil
}
