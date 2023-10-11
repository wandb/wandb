package artifacts

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

func parseArtifactQualifiedName(name string) (entityName string, projectName string, artifactName string, rerr error) {
	// todo: fix parsing; default project and entity
	projectName = "uncategorized"
	entityName = ""
	if name == "" {
		return "", "", "", fmt.Errorf("Invalid artifact path - empty string: %s", name)
	}

	parts := strings.Split(name, "/")
	if len(parts) > 3 {
		return "", "", "", fmt.Errorf("Invalid artifact path: %s", name)
	} else if len(parts) == 1 {
		return entityName, projectName, parts[0], nil
	} else if len(parts) == 2 {
		return entityName, parts[0], parts[1], nil
	}
	return parts[0], parts[1], parts[2], nil
}

// filesystem utils - need to move?
func GetPathFallbacks(path string) (pathFallbacks []string) {
	// https://en.wikipedia.org/wiki/Filename#Comparison_of_filename_limitations
	var charsBuilder strings.Builder
	for i := 0; i < 32; i++ {
		charsBuilder.WriteRune(rune(i))
	}
	charsBuilder.WriteString(`:"*<>?|`)
	PROBLEMATIC_PATH_CHARS := charsBuilder.String()
	// todo: fix this split. this gives dir and file, not drive and path
	root, tail := filepath.Split(path)
	pathFallbacks = append(pathFallbacks, filepath.Join(root, tail))
	for _, char := range PROBLEMATIC_PATH_CHARS {
		if strings.Contains(tail, string(char)) {
			tail = strings.Replace(tail, string(char), "-", -1)
			pathFallbacks = append(pathFallbacks, filepath.Join(root, tail))
		}
	}
	return pathFallbacks
}

func CheckExists(path string) *string {
	for _, dest := range GetPathFallbacks(path) {
		_, err := os.Stat(dest)
		if err == nil {
			// Path exists
			return &dest
		}
	}
	return nil
}

// todo: fix function.
func SystemPreferredPath(path string, warn bool) string {
	if runtime.GOOS != "windows" {
		return path
	}
	// todo: fix this split. this gives dir and file, not drive and path
	head, tail := filepath.Split(path)
	if warn && strings.Contains(tail, ":") {
		fmt.Printf("\nReplacing ':' in %s with '-'", tail)
	}
	new_path := filepath.Join(head, strings.Replace(tail, ":", "-", -1))
	return new_path
}
