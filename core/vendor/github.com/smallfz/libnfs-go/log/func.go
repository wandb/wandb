package log

import (
	"path"
	"runtime"
	"strings"
)

type funcInfo struct {
	mod      string
	fileName string
	line     int
}

func getFuncInfo() *funcInfo {
	fi := &funcInfo{}
	_, fileThis, _, ok := runtime.Caller(0)
	if !ok {
		return fi
	}
	folder := path.Dir(fileThis)
	pc := make([]uintptr, 10)
	n := runtime.Callers(0, pc)
	if n == 0 {
		return fi
	}
	pc = pc[:n]
	frames := runtime.CallersFrames(pc)
	foundThis := false
	for {
		frame, _ := frames.Next()
		frameFolder := path.Dir(frame.File)
		if !foundThis && frameFolder == folder {
			foundThis = true
			continue
		}
		if foundThis && frameFolder != folder {
			funcName := frame.Function
			parts := strings.Split(funcName, "/")
			lastPart := parts[len(parts)-1]
			lastPartArr := strings.Split(lastPart, ".")
			modName := lastPartArr[0]
			parts = parts[:len(parts)-1]
			parts = append(parts, modName)
			modPath := strings.Join(parts, "/")
			fi.mod = modPath
			fi.fileName = path.Base(frame.File)
			fi.line = frame.Line
			break
		}
	}
	return fi
}
