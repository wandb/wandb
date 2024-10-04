package monitor

import (
	"context"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/local"
	"google.golang.org/protobuf/types/known/emptypb"
)

type GPU struct {
	conn   *grpc.ClientConn
	client spb.SystemMonitorClient
}

func NewGPU() *GPU {
	g := &GPU{}

	// TODO: implement a robust handshake mechanism instead
	// find an available port to use for grpc
	port, err := getAvailablePort()
	fmt.Println(port, err)
	if err != nil {
		return nil
	}

	// start the gpu_stats binary. it will start a grpc server on the specified port
	cmdPath, err := getGPUStatsCmdPath()
	fmt.Println(cmdPath, err)
	if err != nil {
		return nil
	}
	cmd := exec.Command(
		cmdPath,
		"--port",
		strconv.Itoa(port),
	)
	fmt.Println(cmd)
	if err := cmd.Start(); err != nil {
		fmt.Println(err)
		return nil
	}

	// establish connection to gpu_stats via grpc
	grpcAddr := "localhost:" + strconv.Itoa(port)
	conn, err := grpc.NewClient(grpcAddr, grpc.WithTransportCredentials(local.NewCredentials()))
	// TODO: does this succeed immediately after starting the binary?
	if err != nil {
		fmt.Println(err)
		return nil
	}
	g.conn = conn

	client := spb.NewSystemMonitorClient(g.conn)
	g.client = client

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

func (g *GPU) Probe() *spb.MetadataRequest {
	return &spb.MetadataRequest{}
}

func (g *GPU) Close() {
	g.client.TearDown(context.Background(), &emptypb.Empty{})
}
