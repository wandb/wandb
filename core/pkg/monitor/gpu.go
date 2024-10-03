package monitor

import (
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
)

type GPU struct{}

func NewGPU() *GPU {
	g := &GPU{}

	// TODO: implement a robust handshake mechanism instead
	// find an available port to use for grpc
	port, err := getAvailablePort()
	if err != nil {
		return nil
	}

	// start gpu_stats binary
	// establish connection to gpu_stats via grpc

	cmdPath, err := getGPUStatsCmdPath()
	if err != nil {
		return nil
	}

	cmd := exec.Command(
		cmdPath,
		"--port",
		strconv.Itoa(port),
	)

	if err := cmd.Start(); err != nil {
		return nil
	}

	return g
}

func getAvailablePort() (int, error) {
	// TODO: implement a robust handshake mechanism instead
	listener, err := net.Listen("tcp", ":0")
	if err != nil {
		return 0, err
	}
	port := listener.Addr().(*net.TCPAddr).Port
	listener.Close()
	return port, nil
}

// getGPUStatsCmdPath returns the path to the gpu_stats program.
func getGPUStatsCmdPath() (string, error) {
	ex, err := os.Executable()
	if err != nil {
		return "", err
	}
	exDirPath := filepath.Dir(ex)
	exPath := filepath.Join(exDirPath, "gpu_stats")

	// append .exe if running on Windows
	if runtime.GOOS == "windows" {
		exPath += ".exe"
	}

	if _, err := os.Stat(exPath); os.IsNotExist(err) {
		return "", err
	}
	return exPath, nil
}

func (g *GPU) Name() string {
	return "gpu"
}

func (g *GPU) IsAvailable() bool {
	return true
}

func (g *GPU) Sample() (map[string]any, error) {
	return nil, nil
}
