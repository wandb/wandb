package artifacts

import "strings"

const registryProjectPrefix = "wandb-registry-"

func IsArtifactRegistryProject(project string) bool {
	return strings.HasPrefix(project, registryProjectPrefix)
}
