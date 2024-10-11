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

type GPU struct {
	pid    int32
	cmd    *exec.Cmd
	conn   *grpc.ClientConn
	client spb.SystemMonitorClient
}

func NewGPU(pid int32) *GPU {
	g := &GPU{pid: pid}

	pf := NewPortfile()
	if pf == nil {
		return nil
	}

	// start the gpu_stats binary, which will start a gRPC service and
	// write the port number to the portfile
	cmdPath, err := getGPUStatsCmdPath()
	if err != nil {
		return nil
	}
	g.cmd = exec.Command(
		cmdPath,
		"--portfile",
		pf.path,
	)
	if err := g.cmd.Start(); err != nil {
		return nil
	}

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
	stats, err := g.client.GetStats(context.Background(), &spb.GetStatsRequest{Pid: g.pid})
	if err != nil {
		return nil, err
	}

	// TODO: this is a temporary adapter. Will redo to use the protobuf message directly.
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

func (g *GPU) Probe() *spb.MetadataRequest {
	metadata, err := g.client.GetMetadata(context.Background(), &spb.GetMetadataRequest{})
	if err != nil {
		return nil
	}
	return metadata.GetRequest().GetMetadata()
}

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
