package platform

import (
	"os"
	"path/filepath"
	"strings"
)

// New selects an adapter from offline DMI and label evidence only; conflicting or absent evidence selects local.
func New(config Config) Adapter {
	config = config.normalized()
	found := map[string]bool{"coreweave": config.Env["WANDB_X_PROVENANCE_PROVIDER"] == "coreweave"}
	for _, name := range []string{"sys_vendor", "product_name", "chassis_asset_tag"} {
		data, _ := os.ReadFile(filepath.Join(config.SysRoot, "class", "dmi", "id", name))
		value := strings.TrimSpace(string(data))
		found["gcp"] = found["gcp"] ||
			(name != "chassis_asset_tag" && strings.Contains(value, "Google"))
		found["aws"] = found["aws"] || (name == "sys_vendor" && value == "Amazon EC2")
		found["oci"] = found["oci"] || (name == "chassis_asset_tag" && value == "OracleCloud.com")
	}
	for name := range config.Labels {
		found["gcp"] = found["gcp"] || strings.HasPrefix(name, "cloud.google.com/")
		found["coreweave"] = found["coreweave"] || name == "ib.coreweave.cloud/fabric" ||
			name == "ib.coreweave.cloud/leafgroup"
		found["aws"] = found["aws"] || strings.HasPrefix(name, "topology.k8s.aws/")
		found["oci"] = found["oci"] || strings.HasPrefix(name, "oci.oraclecloud.com/")
	}
	providers := []string{}
	for name, ok := range found {
		if ok {
			providers = append(providers, name)
		}
	}
	switch {
	case len(providers) > 1:
		adapter := NewLocal(config).(*localAdapter)
		adapter.provider = Capability{Status: "partial", Reason: "provider_conflict"}
		return adapter
	case found["gcp"]:
		return NewGCP(config)
	case found["coreweave"]:
		return NewCoreWeave(config)
	case found["aws"]:
		return NewAWS(config)
	case found["oci"]:
		return NewOCI(config)
	}
	return NewLocal(config)
}
