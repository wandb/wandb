package platform_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/provenance"
	"github.com/wandb/wandb/core/internal/provenance/platform"
)

func ociServer(t *testing.T, requests *[]string) *httptest.Server {
	values := map[string]string{
		"/opc/v2/instance/id":                         "ocid1.instance.oc1.iad.private",
		"/opc/v2/instance/canonicalRegionName":        "us-ashburn-1",
		"/opc/v2/instance/availabilityDomain":         "Uocm:US-ASHBURN-AD-1",
		"/opc/v2/instance/faultDomain":                "FAULT-DOMAIN-2",
		"/opc/v2/instance/shape":                      "BM.GPU.H100.8",
		"/opc/v2/instance/shapeConfig/gpuDescription": "NVIDIA H100 80GB HBM3",
		"/opc/v2/host/rdmaTopologyData":               `{"customerHPCIslandId":"ocid1.hpcisland.private","customerNetworkBlock":"ocid1.computenetworkblock.private","customerLocalBlock":"ocid1.computelocalblock.private","customerHostId":"ocid1.computebaremetalhost.private","extra":"ignored"}`,
	}
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*requests = append(*requests, r.URL.Path)
		assert.Equal(t, http.MethodGet, r.Method)
		assert.Equal(t, "Bearer Oracle", r.Header.Get("Authorization"))
		value, ok := values[r.URL.Path]
		if !ok {
			t.Errorf("unexpected metadata request %s", r.URL.Path)
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write([]byte(value))
	}))
}

func TestOCIReadsOnlyAllowlistedMetadataAndPseudonymizesTopology(t *testing.T) {
	var requests []string
	server := ociServer(t, &requests)
	defer server.Close()
	redactor := provenance.NewRedactor([]byte("job-key"))
	adapter := platform.NewOCI(
		platform.Config{
			SysRoot:     t.TempDir(),
			MetadataURL: server.URL + "/opc/v2",
			Client:      server.Client(),
			Pseudonym:   redactor.Pseudonym,
		},
	)
	first := adapter.Collect(context.Background(), 0)
	adapter.Collect(context.Background(), 0)
	assert.Len(t, requests, 7)
	assert.Equal(t, "oci", first.Identity.Provider)
	assert.Equal(t, "us-ashburn-1", first.Identity.Region)
	assert.Equal(t, "Uocm:US-ASHBURN-AD-1", first.Identity.Zone)
	assert.Equal(t, "BM.GPU.H100.8", first.Identity.InstanceType)
	assert.Equal(t, "NVIDIA H100 80GB HBM3", first.Identity.AcceleratorType)
	assert.Regexp(t, "^instance_[0-9a-f]{24}$", first.Identity.InstanceID)
	roles := []string{}
	for _, level := range first.Topology.Levels {
		roles = append(roles, level.Role)
		assert.Regexp(t, "^topology_[0-9a-f]{24}$", level.Value)
	}
	assert.Equal(
		t,
		[]string{"fault_domain", "hpc_island", "network_block", "local_block", "host"},
		roles,
	)
	data, err := json.Marshal(first)
	require.NoError(t, err)
	assert.NotContains(t, string(data), "ocid1.")
	assert.NotContains(t, string(data), "FAULT-DOMAIN-2")
}

func TestOCIMissingRDMATopologyIsAnExplicitGap(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/instance/shape" {
			_, _ = w.Write([]byte("BM.GPU.H100.8"))
			return
		}
		http.NotFound(w, r)
	}))
	defer server.Close()
	snapshot := platform.NewOCI(platform.Config{SysRoot: t.TempDir(), MetadataURL: server.URL, Client: server.Client()}).
		Collect(context.Background(), 0)
	assert.Equal(t, "BM.GPU.H100.8", snapshot.Identity.InstanceType)
	assert.Equal(t, "not_available", snapshot.Capabilities["metadata_host/rdmaTopologyData"].Reason)
	assert.Empty(t, snapshot.Identity.InstanceID)
	assert.Equal(
		t,
		platform.Capability{Status: "unavailable", Reason: "devices_not_visible"},
		snapshot.Capabilities["rocev2"],
	)
}

func TestOCIMetadataTimeoutIsBounded(t *testing.T) {
	server := httptest.NewServer(
		http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { <-r.Context().Done() }),
	)
	defer server.Close()
	started := time.Now()
	snapshot := platform.NewOCI(platform.Config{SysRoot: t.TempDir(), MetadataURL: server.URL, Client: server.Client()}).
		Collect(context.Background(), 0)
	assert.Less(t, time.Since(started), 2*time.Second)
	assert.Equal(t, "timeout", snapshot.Capabilities["metadata_instance/id"].Status)
	assert.NotContains(t, snapshot.Capabilities, "metadata_instance/shape")
}

func TestOCIRoCEv2CountersPortStateAndSharedNames(t *testing.T) {
	root := t.TempDir()
	files := map[string]string{}
	for device, state := range map[string][3]string{"mlx5_0": {"Ethernet", "4: ACTIVE", "5: LinkUp"}, "mlx5_1": {"InfiniBand", "4: ACTIVE", "5: LinkUp"}, "mlx5_2": {"Ethernet", "1: DOWN", "3: Disabled"}} {
		port := "class/infiniband/" + device + "/ports/1/"
		files[port+"link_layer"], files[port+"state"], files[port+"phys_state"] = state[0], state[1], state[2]
		for _, counter := range []string{"np_ecn_marked_roce_packets", "rp_cnp_ignored", "out_of_buffer", "local_ack_timeout_err", "req_cqe_error", "np_cnp_sent", "rp_cnp_handled"} {
			files[port+"hw_counters/"+counter] = "3"
		}
		files[port+"counters/port_xmit_data"] = "10"
		files[port+"counters/link_downed"] = "1"
	}
	writeFiles(t, root, files)
	server := httptest.NewServer(http.NotFoundHandler())
	defer server.Close()
	snapshot := platform.NewOCI(platform.Config{SysRoot: root, MetadataURL: server.URL, Client: server.Client()}).
		Collect(context.Background(), 0)
	provider, shared := map[string]string{}, map[string]string{}
	for _, counter := range snapshot.Counters {
		if strings.HasPrefix(counter.Name, "oci.rocev2.") {
			assert.NotEqual(t, "mlx5_1:1", counter.Device)
			provider[counter.Name] = counter.Family
		} else if counter.Device == "mlx5_0:1" {
			shared[counter.Name] = counter.Family
		}
	}
	assert.Equal(t, map[string]string{
		"oci.rocev2.np_ecn_marked_roce_packets": "congestion",
		"oci.rocev2.rp_cnp_ignored":             "congestion",
		"oci.rocev2.out_of_buffer":              "discards",
		"oci.rocev2.local_ack_timeout_err":      "retransmits",
		"oci.rocev2.req_cqe_error":              "link_errors",
	}, provider)
	assert.Equal(
		t,
		map[string]string{
			"rdma.np_cnp_sent":    "congestion",
			"rdma.rp_cnp_handled": "congestion",
			"rdma.port_xmit_data": "bytes",
			"rdma.link_downed":    "link_errors",
		},
		shared,
	)
	assert.Equal(t, "available", snapshot.Capabilities["rocev2"].Status)
	assert.Equal(
		t,
		platform.Capability{Status: "partial", Reason: "port_not_active"},
		snapshot.Capabilities["rocev2_ports"],
	)
	names := []string{}
	for _, network := range snapshot.Networks {
		names = append(names, network.Name)
	}
	assert.ElementsMatch(t, []string{"mlx5_0", "mlx5_2"}, names)
}

func TestOCIDetectionUsesChassisAssetTagNotMellanoxDevices(t *testing.T) {
	oci := t.TempDir()
	writeFiles(
		t,
		oci,
		map[string]string{
			"class/dmi/id/chassis_asset_tag": "OracleCloud.com\n",
			"class/dmi/id/sys_vendor":        "Oracle Corporation",
		},
	)
	assert.Equal(t, "oci", platform.New(platform.Config{SysRoot: oci}).Name())
	vendorOnly := t.TempDir()
	writeFiles(
		t,
		vendorOnly,
		map[string]string{
			"class/dmi/id/sys_vendor":                    "Oracle Corporation",
			"class/infiniband/mlx5_0/ports/1/link_layer": "Ethernet",
			"class/infiniband/mlx5_0/device/vendor":      "0x15b3",
		},
	)
	assert.Equal(t, "local", platform.New(platform.Config{SysRoot: vendorOnly}).Name())
	assert.Equal(
		t,
		"local",
		platform.New(platform.Config{SysRoot: oci, Labels: map[string]string{"ib.coreweave.cloud/fabric": "x"}}).
			Name(),
	)
}
