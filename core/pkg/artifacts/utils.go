package artifacts

import "strings"

const RegistryProjectPrefix = "wandb-registry-"

func IsArtifactRegistryProject(project string) bool {
	return strings.HasPrefix(project, RegistryProjectPrefix)
}
