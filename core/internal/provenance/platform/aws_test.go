package platform_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/provenance"
	"github.com/wandb/wandb/core/internal/provenance/platform"
)

func writeFiles(t *testing.T, root string, files map[string]string) {
	t.Helper()
	for name, content := range files {
		path := filepath.Join(root, name)
		require.NoError(t, os.MkdirAll(filepath.Dir(path), 0o700))
		require.NoError(t, os.WriteFile(path, []byte(content), 0o600))
	}
}

func imdsServer(t *testing.T, requests *[]string) *httptest.Server {
	values := map[string]string{
		"/latest/meta-data/instance-id":                 "i-0rawinstance",
		"/latest/meta-data/instance-type":               "p5.48xlarge",
		"/latest/meta-data/placement/region":            "us-east-1",
		"/latest/meta-data/placement/availability-zone": "us-east-1a",
		"/latest/meta-data/placement/group-name":        "private-placement",
	}
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*requests = append(*requests, r.Method+" "+r.URL.Path)
		if r.URL.Path == "/latest/api/token" {
			assert.Equal(t, http.MethodPut, r.Method)
			assert.Equal(t, "60", r.Header.Get("X-aws-ec2-metadata-token-ttl-seconds"))
			_, _ = w.Write([]byte("private-token"))
			return
		}
		assert.Equal(t, "private-token", r.Header.Get("X-aws-ec2-metadata-token"))
		value, ok := values[r.URL.Path]
		if !ok {
			t.Errorf("unexpected metadata request %s", r.URL.Path)
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write([]byte(value))
	}))
}

func TestAWSIMDSv2IdentityIsPseudonymizedAndReadOnce(t *testing.T) {
	var requests []string
	server := imdsServer(t, &requests)
	defer server.Close()
	redactor := provenance.NewRedactor([]byte("job-key"))
	adapter := platform.NewAWS(
		platform.Config{
			SysRoot:     t.TempDir(),
			MetadataURL: server.URL,
			Client:      server.Client(),
			Labels:      map[string]string{"topology.k8s.aws/network-node-layer-3": "nn-private"},
			Pseudonym:   redactor.Pseudonym,
		},
	)
	first := adapter.Collect(context.Background(), 0)
	second := adapter.Collect(context.Background(), 0)
	assert.Equal(t, first.Identity, second.Identity)
	assert.Len(t, requests, 6)
	assert.Equal(t, "PUT /latest/api/token", requests[0])
	assert.Equal(
		t,
		platform.Identity{
			Provider:     "aws",
			Region:       "us-east-1",
			Zone:         "us-east-1a",
			InstanceType: "p5.48xlarge",
			InstanceID:   first.Identity.InstanceID,
		},
		first.Identity,
	)
	assert.Regexp(t, "^instance_[0-9a-f]{24}$", first.Identity.InstanceID)
	roles := map[string]string{}
	for _, level := range first.Topology.Levels {
		roles[level.Role] = level.Value
	}
	assert.Regexp(t, "^topology_[0-9a-f]{24}$", roles["placement_group"])
	assert.Regexp(t, "^topology_[0-9a-f]{24}$", roles["network_node_layer_3"])
	assert.Regexp(t, "^topology_[0-9a-f]{24}$", roles["host"])
	assert.Empty(t, roles["network_node_layer_1"])
	assert.Equal(t, "unknown", first.Transport.Name)
	data, err := json.Marshal(first)
	require.NoError(t, err)
	for _, secret := range []string{"i-0rawinstance", "private-placement", "private-token", "nn-private", "job-key"} {
		assert.NotContains(t, string(data), secret)
	}
}

func TestAWSMissingRedactionKeyOmitsIdentityJoins(t *testing.T) {
	var requests []string
	server := imdsServer(t, &requests)
	defer server.Close()
	snapshot := platform.NewAWS(platform.Config{SysRoot: t.TempDir(), MetadataURL: server.URL, Client: server.Client(), Labels: map[string]string{}}).
		Collect(context.Background(), 0)
	assert.Empty(t, snapshot.Identity.InstanceID)
	for _, level := range snapshot.Topology.Levels {
		assert.Empty(t, level.Value)
	}
	assert.Equal(t, "partial", snapshot.Capabilities["identity_join"].Status)
	assert.Equal(t, "p5.48xlarge", snapshot.Identity.InstanceType)
}

func TestAWSTokenTimeoutIsBoundedAndSkipsFieldReads(t *testing.T) {
	var calls atomic.Int32
	server := httptest.NewServer(
		http.HandlerFunc(
			func(w http.ResponseWriter, r *http.Request) { calls.Add(1); <-r.Context().Done() },
		),
	)
	defer server.Close()
	started := time.Now()
	snapshot := platform.NewAWS(platform.Config{SysRoot: t.TempDir(), MetadataURL: server.URL, Client: server.Client(), Labels: map[string]string{}}).
		Collect(context.Background(), 0)
	assert.Less(t, time.Since(started), 3*time.Second)
	assert.EqualValues(t, 1, calls.Load())
	assert.Equal(t, "timeout", snapshot.Capabilities["metadata_token"].Status)
	assert.Equal(t, "aws", snapshot.Identity.Provider)
}

func TestAWSEFASysfsMapsSemanticCountersAndDevices(t *testing.T) {
	root := t.TempDir()
	port := "class/infiniband/rdmap79s0/ports/1/hw_counters/"
	writeFiles(t, root, map[string]string{
		port + "tx_bytes": "100", port + "rx_bytes": "200", port + "rdma_read_bytes": "300",
		port + "rdma_write_wrs": "4", port + "retrans_pkts": "5", port + "rdma_read_wr_err": "6",
		port + "rx_drops": "7", port + "lifespan": "12",
		"devices/pci0000:00/0000:4f:00.0/numa_node": "1",
	})
	require.NoError(
		t,
		os.Symlink(
			filepath.Join(root, "devices", "pci0000:00", "0000:4f:00.0"),
			filepath.Join(root, "class", "infiniband", "rdmap79s0", "device"),
		),
	)
	server := httptest.NewServer(http.NotFoundHandler())
	defer server.Close()
	redactor := provenance.NewRedactor([]byte("job-key"))
	snapshot := platform.NewAWS(platform.Config{SysRoot: root, MetadataURL: server.URL, Client: server.Client(), Labels: map[string]string{}, Pseudonym: redactor.Pseudonym}).
		Collect(context.Background(), 0)
	families := map[string]string{}
	for _, counter := range snapshot.Counters {
		assert.Equal(t, "rdmap79s0:1", counter.Device)
		assert.True(t, counter.Monotonic)
		families[counter.Name] = counter.Family + "/" + counter.Unit
	}
	assert.Equal(t, map[string]string{
		"aws.efa.tx_bytes":         "bytes/bytes",
		"aws.efa.rx_bytes":         "bytes/bytes",
		"aws.efa.rdma_read_bytes":  "bytes/bytes",
		"aws.efa.rdma_write_wrs":   "rdma_operations/operations",
		"aws.efa.retrans_pkts":     "retransmits/packets",
		"aws.efa.rdma_read_wr_err": "link_errors/events",
		"aws.efa.rx_drops":         "discards/packets",
	}, families)
	require.Len(t, snapshot.Networks, 1)
	assert.Equal(t, "rdmap79s0", snapshot.Networks[0].Name)
	assert.Equal(t, 1, *snapshot.Networks[0].NUMA)
	assert.Regexp(t, "^pci_[0-9a-f]{24}$", snapshot.Networks[0].PCIID)
	assert.Equal(t, "available", snapshot.Capabilities["efa"].Status)
	assert.Equal(t, "not_available", snapshot.Capabilities["metadata_token"].Reason)
}

func TestAWSNoEFADevicesIsAnExplicitGap(t *testing.T) {
	server := httptest.NewServer(http.NotFoundHandler())
	defer server.Close()
	snapshot := platform.NewAWS(platform.Config{SysRoot: t.TempDir(), MetadataURL: server.URL, Client: server.Client(), Labels: map[string]string{}}).
		Collect(context.Background(), 0)
	assert.Equal(
		t,
		platform.Capability{Status: "unavailable", Reason: "devices_not_visible"},
		snapshot.Capabilities["efa"],
	)
	assert.Empty(t, snapshot.Counters)
}

func TestAWSDetectionNeedsDMIEvidenceNotNICVendor(t *testing.T) {
	aws := t.TempDir()
	writeFiles(
		t,
		aws,
		map[string]string{
			"class/dmi/id/sys_vendor":   "Amazon EC2\n",
			"class/dmi/id/product_name": "p5.48xlarge\n",
		},
	)
	assert.Equal(t, "aws", platform.New(platform.Config{SysRoot: aws}).Name())
	efaOnly := t.TempDir()
	writeFiles(
		t,
		efaOnly,
		map[string]string{
			"class/infiniband/rdmap79s0/device/vendor": "0x1d0f",
			"class/net/ens32/device/vendor":            "0x1d0f",
		},
	)
	assert.Equal(t, "local", platform.New(platform.Config{SysRoot: efaOnly}).Name())
	conflict := t.TempDir()
	writeFiles(
		t,
		conflict,
		map[string]string{
			"class/dmi/id/sys_vendor":   "Amazon EC2",
			"class/dmi/id/product_name": "Google Compute Engine",
		},
	)
	snapshot := platform.New(platform.Config{SysRoot: conflict}).Collect(context.Background(), 0)
	assert.Equal(t, "local", snapshot.Identity.Provider)
	assert.Equal(t, "provider_conflict", snapshot.Capabilities["provider"].Reason)
	assert.Equal(
		t,
		"local",
		platform.New(platform.Config{SysRoot: aws, Env: map[string]string{"WANDB_X_PROVENANCE_PROVIDER": "coreweave"}}).
			Name(),
	)
}
