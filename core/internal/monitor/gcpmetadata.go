package monitor

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	googleCloudMetadataBaseURL        = "http://metadata.google.internal/computeMetadata/v1"
	googleCloudMetadataTimeout        = 100 * time.Millisecond
	kubernetesServiceAccountTokenPath = "/var/run/secrets/kubernetes.io/serviceaccount/token"
	kubernetesNamespacePath           = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
)

type GoogleCloudMetadataParams struct {
	Client                  *http.Client
	BaseURL                 string
	KubernetesSATokenPath   string
	KubernetesNamespacePath string
	Logger                  *observability.CoreLogger
}

// GoogleCloudMetadata captures GCP and GKE environment metadata.
type GoogleCloudMetadata struct {
	client                  *http.Client
	baseURL                 string
	kubernetesSATokenPath   string
	kubernetesNamespacePath string
	logger                  *observability.CoreLogger
}

func NewGoogleCloudMetadata(params GoogleCloudMetadataParams) (*GoogleCloudMetadata, error) {
	if params.Logger == nil {
		params.Logger = observability.NewNoOpLogger()
	}
	if params.Client == nil {
		params.Client = &http.Client{Timeout: googleCloudMetadataTimeout}
	}
	if params.BaseURL == "" {
		params.BaseURL = googleCloudMetadataBaseURL
	}
	if _, err := url.ParseRequestURI(params.BaseURL); err != nil {
		return nil, fmt.Errorf("invalid Google Cloud metadata base URL: %w", err)
	}
	if params.KubernetesSATokenPath == "" {
		params.KubernetesSATokenPath = kubernetesServiceAccountTokenPath
	}
	if params.KubernetesNamespacePath == "" {
		params.KubernetesNamespacePath = kubernetesNamespacePath
	}

	return &GoogleCloudMetadata{
		client:                  params.Client,
		baseURL:                 strings.TrimRight(params.BaseURL, "/"),
		kubernetesSATokenPath:   params.KubernetesSATokenPath,
		kubernetesNamespacePath: params.KubernetesNamespacePath,
		logger:                  params.Logger,
	}, nil
}

// Sample is a no-op method.
//
// Required for GoogleCloudMetadata to implement the Resource interface.
func (gcm *GoogleCloudMetadata) Sample() (*spb.StatsRecord, error) {
	return nil, nil
}

func (gcm *GoogleCloudMetadata) Probe(ctx context.Context) *spb.EnvironmentRecord {
	info, err := gcm.Get(ctx)
	if err != nil {
		gcm.logger.Debug("gcpmetadata: error collecting data", "error", err)
		return nil
	}
	if info == nil {
		return nil
	}
	return &spb.EnvironmentRecord{GoogleCloud: info}
}

func (gcm *GoogleCloudMetadata) Get(ctx context.Context) (*spb.GoogleCloudInfo, error) {
	instanceID, ok, err := gcm.getMetadata(ctx, "instance/id", true)
	if err != nil || !ok {
		return nil, err
	}

	projectID := gcm.optionalMetadata(ctx, "project/project-id")
	zonePath := gcm.optionalMetadata(ctx, "instance/zone")
	zone := lastPathPart(zonePath)
	region := regionFromZone(zone)

	orchestrator := "GCE"
	var gke *spb.GKEInfo
	if gcm.isKubernetes() {
		orchestrator = "GKE"
		gke = gcm.getGKEInfo(ctx)
	}

	return &spb.GoogleCloudInfo{
		ProjectId:    projectID,
		Zone:         zone,
		Region:       region,
		InstanceId:   instanceID,
		Orchestrator: orchestrator,
		Gke:          gke,
	}, nil
}

func (gcm *GoogleCloudMetadata) optionalMetadata(ctx context.Context, path string) string {
	value, ok, err := gcm.getMetadata(ctx, path, false)
	if err != nil || !ok {
		return ""
	}
	return value
}

func (gcm *GoogleCloudMetadata) getMetadata(
	ctx context.Context,
	path string,
	requireGoogleFlavor bool,
) (string, bool, error) {
	reqCtx, cancel := context.WithTimeout(ctx, googleCloudMetadataTimeout)
	defer cancel()

	req, err := http.NewRequestWithContext(
		reqCtx,
		http.MethodGet,
		gcm.baseURL+"/"+strings.TrimLeft(path, "/"),
		http.NoBody,
	)
	if err != nil {
		return "", false, err
	}
	req.Header.Set("Metadata-Flavor", "Google")

	resp, err := gcm.client.Do(req)
	if err != nil {
		return "", false, err
	}
	defer func() {
		_, _ = io.Copy(io.Discard, resp.Body)
		_ = resp.Body.Close()
	}()

	if resp.StatusCode != http.StatusOK {
		return "", false, nil
	}
	if requireGoogleFlavor && resp.Header.Get("Metadata-Flavor") != "Google" {
		return "", false, nil
	}

	body, err := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	if err != nil {
		return "", false, err
	}
	return strings.TrimSpace(string(body)), true, nil
}

func (gcm *GoogleCloudMetadata) isKubernetes() bool {
	if os.Getenv("KUBERNETES_SERVICE_HOST") != "" {
		return true
	}
	_, err := os.Stat(gcm.kubernetesSATokenPath)
	return err == nil
}

type gkeWorkloadDetails struct {
	clusterName       string
	namespace         string
	workloadKind      string
	workloadName      string
	parentWorkload    string
	creationTimestamp string
	labels            map[string]string
}

func (gcm *GoogleCloudMetadata) getGKEInfo(ctx context.Context) *spb.GKEInfo {
	details := gkeWorkloadDetailsFromEnv()
	if details.clusterName == "" {
		details.clusterName = shortName(
			gcm.optionalMetadata(ctx, "instance/attributes/cluster-name"),
		)
	}
	if details.namespace == "" {
		details.namespace = gcm.kubernetesNamespace()
	}

	if details.isEmpty() {
		return nil
	}

	return &spb.GKEInfo{
		ClusterName:       details.clusterName,
		Namespace:         details.namespace,
		WorkloadKind:      details.workloadKind,
		WorkloadName:      details.workloadName,
		ParentWorkload:    details.parentWorkload,
		CreationTimestamp: details.creationTimestamp,
		WorkloadId:        gkeWorkloadID(details),
		Labels:            details.labels,
	}
}

func (gcm *GoogleCloudMetadata) kubernetesNamespace() string {
	data, err := os.ReadFile(gcm.kubernetesNamespacePath)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}

func gkeWorkloadDetailsFromEnv() gkeWorkloadDetails {
	identifier := jsonEnv("GKE_DIAGON_IDENTIFIER")
	metadata := jsonEnv("GKE_DIAGON_METADATA")

	details := gkeWorkloadDetails{
		clusterName:       shortName(jsonString(identifier, "clustername")),
		namespace:         jsonString(identifier, "namespace"),
		workloadKind:      jsonString(identifier, "metadata.kind"),
		workloadName:      jsonString(identifier, "metadata.name"),
		parentWorkload:    jsonString(metadata, "parent-workload"),
		creationTimestamp: jsonString(metadata, "creation-timestamp"),
		labels:            labelsFromString(jsonString(metadata, "associated-labels")),
	}
	if len(details.labels) == 0 {
		details.labels = nil
	}
	return details
}

func jsonEnv(name string) map[string]any {
	value := os.Getenv(name)
	if value == "" {
		return nil
	}
	var result map[string]any
	if err := json.Unmarshal([]byte(value), &result); err != nil {
		return nil
	}
	return result
}

func jsonString(values map[string]any, key string) string {
	value, ok := values[key].(string)
	if !ok {
		return ""
	}
	return value
}

func labelsFromString(value string) map[string]string {
	labels := make(map[string]string)
	for _, pair := range strings.Split(value, ",") {
		key, value, ok := strings.Cut(pair, "=")
		if !ok {
			continue
		}
		key = strings.TrimSpace(key)
		value = strings.TrimSpace(value)
		if key != "" {
			labels[key] = value
		}
	}
	return labels
}

func (details gkeWorkloadDetails) isEmpty() bool {
	return details.clusterName == "" &&
		details.namespace == "" &&
		details.workloadKind == "" &&
		details.workloadName == "" &&
		details.parentWorkload == "" &&
		details.creationTimestamp == "" &&
		len(details.labels) == 0
}

func gkeWorkloadID(details gkeWorkloadDetails) string {
	if details.clusterName == "" ||
		details.namespace == "" ||
		details.workloadKind == "" ||
		details.workloadName == "" ||
		details.creationTimestamp == "" {
		return ""
	}

	createdAt, err := time.Parse(time.RFC3339Nano, details.creationTimestamp)
	if err != nil {
		return ""
	}
	raw := fmt.Sprintf(
		"%s_%s_%s_%s_%s",
		shortName(details.clusterName),
		details.namespace,
		details.workloadKind,
		details.workloadName,
		createdAt.UTC().Format("20060102-150405"),
	)
	hash := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(hash[:])
}

func lastPathPart(value string) string {
	value = strings.Trim(value, "/")
	if value == "" {
		return ""
	}
	parts := strings.Split(value, "/")
	return parts[len(parts)-1]
}

func shortName(value string) string {
	return lastPathPart(value)
}

func regionFromZone(zone string) string {
	parts := strings.Split(zone, "-")
	if len(parts) < 2 {
		return ""
	}
	return strings.Join(parts[:len(parts)-1], "-")
}
