package artifacts

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
)

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
