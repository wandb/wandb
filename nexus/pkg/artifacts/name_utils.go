package artifacts

import (
	"fmt"
	"strings"
)

func parseArtifactQualifiedName(name string) (entityName string, projectName string, artifactName string, rerr error) {
	// todo: default/run project and entity?
	projectName = "uncategorized"
	entityName = ""
	if name == "" {
		return "", "", "", fmt.Errorf("invalid artifact path - empty string: %s", name)
	}

	parts := strings.Split(name, "/")
	switch len(parts) {
	case 1:
		return entityName, projectName, parts[0], nil
	case 2:
		return entityName, parts[0], parts[1], nil
	case 3:
		return parts[0], parts[1], parts[2], nil
	default:
		return "", "", "", fmt.Errorf("invalid artifact path: %s", name)
	}
}
