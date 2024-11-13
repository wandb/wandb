package monitor

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/protobuf/types/known/emptypb"
)

// GPU is used to monitor Nvidia and Apple ARM GPUs.
//
// It collects GPU metrics from the gpu_stats binary via gRPC.
type GPU struct {
	// pid of the process to collect process-specific metrics for.
	pid int32
	// gpu_stats process.
	cmd *exec.Cmd
	// gRPC client connection and client for GPU metrics.
	conn   *grpc.ClientConn
	client spb.SystemMonitorClient
}

func NewGPU(pid int32) *GPU {
	g := &GPU{pid: pid}

	// A portfile is used to communicate the port number of the gRPC service
	// started by the gpu_stats binary.
	pf := NewPortfile()
	if pf == nil {
		return nil
	}

	// pid of the current wandb-core process.
	// the gpu_binary would shut down if this process dies.
	ppid := os.Getpid()

	// Start the gpu_stats binary, which will in turn start a gRPC service and
	// write the port number to the portfile.
	cmdPath, err := getGPUStatsCmdPath()
	if err != nil {
		return nil
	}
	g.cmd = exec.Command(
		cmdPath,
		"--portfile",
		pf.path,
		"--ppid",
		strconv.Itoa(ppid),
	)
	if err := g.cmd.Start(); err != nil {
		return nil
	}

	// Read the port number of the gRPC service from the portfile.
	// TODO: make the timeout configurable
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	port, err := pf.Read(ctx)
	if err != nil {
		return nil
	}
	err = pf.Delete()
	if err != nil {
		return nil
	}

	// Establish connection to gpu_stats via gRPC.
	grpcAddr := "127.0.0.1:" + strconv.Itoa(port)
	// NewCLient creates a new gRPC "channel" for the target URI provided. No I/O is performed.
	// Use of the ClientConn for RPCs will automatically cause it to connect.
	conn, err := grpc.NewClient(grpcAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil
	}
	g.conn = conn

	client := spb.NewSystemMonitorClient(g.conn)
	g.client = client

	return g
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

// Sample returns GPU metrics such as power usage, temperature, and utilization.
//
// TODO: The metrics are collected from the gpu_stats binary via gRPC.
// This function is a temporary adapter that adds extra ser/de ops.
// Will refactor to use the protobuf message directly.
func (g *GPU) Sample() (map[string]any, error) {
	stats, err := g.client.GetStats(context.Background(), &spb.GetStatsRequest{Pid: g.pid})
	if err != nil {
		return nil, err
	}

	// convert stats record into a map
	metrics := make(map[string]any)
	for _, item := range stats.GetStats().GetItem() {
		var unmarshalled any
		err = json.Unmarshal([]byte(item.ValueJson), &unmarshalled)
		if err != nil {
			continue
		}
		// skip underscored keys
		if strings.HasPrefix(item.Key, "_") {
			continue
		}
		metrics[item.Key] = unmarshalled
	}

	return metrics, nil
}

// Probe returns metadata about the GPU.
func (g *GPU) Probe() *spb.MetadataRequest {
	metadata, err := g.client.GetMetadata(context.Background(), &spb.GetMetadataRequest{})
	if err != nil {
		return nil
	}
	return metadata.GetRequest().GetMetadata()
}

// Close shuts down the gpu_stats binary and releases resources.
func (g *GPU) Close() {
	if _, err := g.client.TearDown(context.Background(), &emptypb.Empty{}); err == nil { // ignore error
		g.conn.Close()
		// Wait for the process to exit to prevent zombie processes.
		// This is a best-effort attempt to clean up the process.
		go func() {
			_ = g.cmd.Wait()
		}()
	}
}
