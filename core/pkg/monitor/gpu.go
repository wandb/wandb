package monitor

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/protobuf/types/known/emptypb"
)

type GPU struct {
	pid    int32
	conn   *grpc.ClientConn
	client spb.SystemMonitorClient
}

func NewGPU(pid int32) *GPU {
	g := &GPU{pid: pid}

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

	// Establish connection to gpu_stats via gRPC.
	grpcAddr := "[::1]:" + strconv.Itoa(port)
	// NewCLient creates a new gRPC "channel" for the target URI provided. No I/O is performed.
	// Use of the ClientConn for RPCs will automatically cause it to connect.
	// conn, err := grpc.NewClient(grpcAddr, grpc.WithTransportCredentials(local.NewCredentials()))
	conn, err := grpc.NewClient(grpcAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil
	}
	g.conn = conn

	client := spb.NewSystemMonitorClient(g.conn)
	g.client = client

	return g
}

func getAvailablePort() (int, error) {
	// TODO: implement a robust handshake mechanism instead
	// Better still, use a unix domain socket on *nix systems
	// and named pipes on Windows
	return 50051, nil
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
	stats, err := g.client.GetStats(context.Background(), &spb.GetStatsRequest{Pid: int64(g.pid)})
	if err != nil {
		return nil, err
	}
	fmt.Println(stats)
	return nil, nil
}

func (g *GPU) Probe() *spb.MetadataRequest {
	return &spb.MetadataRequest{}
}

func (g *GPU) Close() {
	g.client.TearDown(context.Background(), &emptypb.Empty{})
	g.conn.Close()
}
