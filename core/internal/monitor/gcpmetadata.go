package monitor

import (
	"context"
	"time"

	"cloud.google.com/go/compute/metadata"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// probeGoogleCloud returns the project, zone and instance of a Google Cloud
// VM and the GKE cluster it belongs to, or nil off Google Cloud.
func probeGoogleCloud(ctx context.Context) *spb.EnvironmentRecord {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()

	client := metadata.NewClient(nil)
	if !client.OnGCEWithContext(ctx) {
		return nil
	}

	info := &spb.GoogleCloudInfo{}
	info.ProjectId, _ = client.ProjectIDWithContext(ctx)
	info.Zone, _ = client.ZoneWithContext(ctx)
	info.InstanceId, _ = client.InstanceIDWithContext(ctx)
	info.ClusterName, _ = client.InstanceAttributeValueWithContext(ctx, "cluster-name")
	return &spb.EnvironmentRecord{GoogleCloud: info}
}
