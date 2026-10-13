package platform

import (
	"context"
	"net/http"
	"os"
	"time"
)

type Capability struct {
	Status string `json:"status"`
	Reason string `json:"reason,omitempty"`
}
type Identity struct {
	Provider        string `json:"provider"`
	Region          string `json:"region,omitempty"`
	Zone            string `json:"zone,omitempty"`
	InstanceType    string `json:"instance_type,omitempty"`
	AcceleratorType string `json:"accelerator_type,omitempty"`
	InstanceID      string `json:"instance_id,omitempty"`
}
type TopologyLevel struct {
	Role  string `json:"role"`
	Label string `json:"label"`
	Value string `json:"value,omitempty"`
}
type Topology struct {
	Levels []TopologyLevel `json:"levels"`
}
type NetworkDevice struct {
	Name  string `json:"name"`
	PCIID string `json:"pci_id,omitempty"`
	NUMA  *int   `json:"numa,omitempty"`
}
type TransportEvidence struct {
	Name   string `json:"name"`
	Source string `json:"source,omitempty"`
}
type Counter struct {
	Family    string   `json:"family"`
	Name      string   `json:"name"`
	Device    string   `json:"device,omitempty"`
	Value     *float64 `json:"value,omitempty"`
	Unit      string   `json:"unit"`
	Monotonic bool     `json:"monotonic"`
}
type Snapshot struct {
	Identity     Identity              `json:"identity"`
	Topology     Topology              `json:"topology"`
	Networks     []NetworkDevice       `json:"networks"`
	Counters     []Counter             `json:"counters"`
	Transport    TransportEvidence     `json:"transport"`
	Capabilities map[string]Capability `json:"capabilities"`
}
type Adapter interface {
	Name() string
	Collect(context.Context, int) Snapshot
}
type Config struct {
	SysRoot           string
	Env               map[string]string
	Labels            map[string]string
	Client            *http.Client
	MetadataURL       string
	KubernetesURL     string
	ServiceAccountDir string
	Pseudonym         func(string, string) (string, bool)
	// KeyReason is the emitter's identity_join reason when Pseudonym is unavailable.
	KeyReason string
}

func (c Config) normalized() Config {
	if c.SysRoot == "" {
		c.SysRoot = "/sys"
	}
	if c.Client == nil {
		// Metadata endpoints are link-local, so environment proxies must never see these requests.
		transport := http.DefaultTransport.(*http.Transport).Clone()
		transport.Proxy = nil
		c.Client = &http.Client{Timeout: 500 * time.Millisecond, Transport: transport}
	}
	if c.ServiceAccountDir == "" {
		c.ServiceAccountDir = "/var/run/secrets/kubernetes.io/serviceaccount"
	}
	if c.Env == nil {
		c.Env = map[string]string{}
		for _, name := range []string{"KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT_HTTPS", "K8S_POD_NAME", "K8S_NAMESPACE", "COREWEAVE_REGION", "WANDB_X_PROVENANCE_PROVIDER"} {
			c.Env[name] = os.Getenv(name)
		}
	}
	if c.Pseudonym == nil {
		c.Pseudonym = func(string, string) (string, bool) { return "", false }
	}
	return c
}
