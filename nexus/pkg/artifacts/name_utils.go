package artifacts

import (
	"strings"
)

func parseArtifactQualifiedName(name string) (entityName string, projectName string, artifactName string, rerr error) {
	parts := strings.Split(name, "/")
	return parts[0], parts[1], parts[2], nil
}
