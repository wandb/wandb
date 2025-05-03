package kinds

const (
	CtrlplaneMetadataLinks = "ctrlplane/links"
)

const (
	// Basic database metadata
	DBMetadataType              = "database/type"
	DBMetadataHost              = "database/host"
	DBMetadataPort              = "database/port"
	DBMetadataState             = "database/state"
	DBMetadataVersion           = "database/version"
	DBMetadataVersionMajor      = "database/version/major"
	DBMetadataVersionMinor      = "database/version/minor"
	DBMetadataVersionPatch      = "database/version/patch"
	DBMetadataVersionPrerelease = "database/version/prerelease"
	DBMetadataName              = "database/name"
	DBMetadataSSL               = "database/ssl"
	DBMetadataRegion            = "database/region"
	DBMetadataTier              = "database/tier"

	// Authentication and access
	DBMetadataUser        = "database/user"
	DBMetadataAuthType    = "database/auth-type"
	DBMetadataAccessLevel = "database/access-level"

	// Performance and capacity
	DBMetadataStorageGB      = "database/storage-gb"
	DBMetadataStorageType    = "database/storage-type"
	DBMetadataIOPS           = "database/iops"
	DBMetadataMaxConnections = "database/max-connections"
	DBMetadataReadReplicas   = "database/read-replicas"

	// Operational
	DBMetadataBackupRetention   = "database/backup-retention-days"
	DBMetadataBackupWindow      = "database/backup-window"
	DBMetadataMaintenanceWindow = "database/maintenance-window"
	DBMetadataEncryption        = "database/encryption"
	DBMetadataMultiAZ           = "database/multi-az"
	DBMetadataEndpoint          = "database/endpoint"
)

const (
	K8SMetadataType      = "kubernetes/type"
	K8SMetadataName      = "kubernetes/name"
	K8SMetadataCreated   = "kubernetes/created"
	K8SMetadataNamespace = "kubernetes/namespace"

	K8SMetadataVersion           = "kubernetes/version"
	K8SMetadataVersionMajor      = "kubernetes/version/major"
	K8SMetadataVersionMinor      = "kubernetes/version/minor"
	K8SMetadataVersionPatch      = "kubernetes/version/patch"
	K8SMetadataVersionPrerelease = "kubernetes/version/prerelease"

	K8SMetadataStatus         = "kubernetes/status"
	K8SMetadataCreationTime   = "kubernetes/creation-time"
	K8SMetadataClusterName    = "kubernetes/cluster-name"
	K8SMetadataUID            = "kubernetes/uid"
	K8SMetadataNodeName       = "kubernetes/node-name"
	K8SMetadataPodIP          = "kubernetes/pod-ip"
	K8SMetadataServiceAccount = "kubernetes/service-account"
	K8SMetadataRestartCount   = "kubernetes/restart-count"
	K8SMetadataReadyReplicas  = "kubernetes/ready-replicas"
	K8SMetadataStrategy       = "kubernetes/strategy"
	K8SMetadataEndpoints      = "kubernetes/endpoints"
	K8SMetadataSelector       = "kubernetes/selector"
	K8SMetadataStorageClass   = "kubernetes/storage-class"
	K8SMetadataCapacity       = "kubernetes/capacity"
	K8SMetadataAccessModes    = "kubernetes/access-modes"
	K8SMetadataIngressRules   = "kubernetes/ingress-rules"
	K8SMetadataIngressClass   = "kubernetes/ingress-class"
)
