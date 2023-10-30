package artifacts

import (
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/wandb/wandb/nexus/pkg/utils"
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

func getArtifactQualifiedName(entityName string, projectName string, artifactName string, versionIndex string) (name string) {
	return fmt.Sprintf("%s:v%s", strings.Join([]string{entityName, projectName, artifactName}, "/"), versionIndex)
}

// todo: needs testing
// filesystem utils - need to move?
func GetPathFallbacks(path string) (pathFallbacks []string) {
	// https://en.wikipedia.org/wiki/Filename#Comparison_of_filename_limitations
	var charsBuilder strings.Builder
	for i := 0; i < 32; i++ {
		charsBuilder.WriteRune(rune(i))
	}
	charsBuilder.WriteString(`:"*<>?|`)
	PROBLEMATIC_PATH_CHARS := charsBuilder.String()
	root := filepath.VolumeName(path)
	tail := path[len(root):]
	pathFallbacks = append(pathFallbacks, filepath.Join(root, tail))
	for _, char := range PROBLEMATIC_PATH_CHARS {
		if strings.Contains(tail, string(char)) {
			tail = strings.ReplaceAll(tail, string(char), "-")
			pathFallbacks = append(pathFallbacks, filepath.Join(root, tail))
		}
	}
	return pathFallbacks
}

func CheckExists(path string) *string {
	for _, dest := range GetPathFallbacks(path) {
		_, err := os.Stat(dest)
		if err == nil {
			return &dest
		}
	}
	return nil
}

// todo: needs testing
func SystemPreferredPath(path string, warn bool) string {
	if runtime.GOOS != "windows" {
		return path
	}
	head := filepath.VolumeName(path)
	tail := path[len(head):]
	if warn && strings.Contains(tail, ":") {
		fmt.Printf("\nReplacing ':' in %s with '-'", tail)
	}
	new_path := filepath.Join(head, strings.ReplaceAll(tail, ":", "-"))
	return new_path
}

func isArtifactReference(ref *string) (bool, error) {
	if ref == nil {
		return false, nil
	}
	u, err := url.Parse(*ref)
	if err != nil {
		return false, err
	}
	if u.Scheme == "wandb-artifact" {
		return true, nil
	}
	return false, nil
}

func getReferencedID(ref *string) (*string, error) {
	isRef, err := isArtifactReference(ref)
	if err != nil {
		return nil, err
	} else if !isRef {
		return nil, nil
	}
	u, err := url.Parse(*ref)
	if err != nil {
		return nil, err
	}
	refID, err := utils.HexToB64(u.Host)
	if err != nil {
		return nil, err
	}
	return &refID, nil
}
