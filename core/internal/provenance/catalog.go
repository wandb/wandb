package provenance

import (
	"os"
	"strings"
)

// PeakFLOPsCatalogVersion names the revision of peakFLOPsByDevice recorded in manifests.
const PeakFLOPsCatalogVersion = "nvidia-dense-2026-10"

// PeakFLOPs is the catalog entry for the bound device; PerGPU is the bf16 dense peak in FLOP/s.
type PeakFLOPs struct {
	CatalogVersion string             `json:"catalog_version"`
	Device         string             `json:"device"`
	DType          string             `json:"dtype"`
	PerGPU         float64            `json:"per_gpu"`
	PerGPUByDType  map[string]float64 `json:"per_gpu_by_dtype"`
	Source         string             `json:"source"`
}

type peakEntry struct {
	device string
	bf16   float64
	fp8    float64
	source string
}

// Dense (no sparsity) Tensor Core peaks keyed by NVML device name.
var peakFLOPsByDevice = map[string]peakEntry{
	"NVIDIA H100 80GB HBM3": {
		"H100 SXM",
		989.4e12,
		1978.9e12,
		"NVIDIA H100 Tensor Core GPU datasheet",
	},
	"NVIDIA H200": {
		"H200 SXM",
		989.4e12,
		1978.9e12,
		"NVIDIA H200 Tensor Core GPU datasheet",
	},
	"NVIDIA A100-SXM4-80GB": {"A100 SXM", 312e12, 0, "NVIDIA A100 Tensor Core GPU datasheet"},
	"NVIDIA A100-SXM4-40GB": {"A100 SXM", 312e12, 0, "NVIDIA A100 Tensor Core GPU datasheet"},
}

// peakFLOPs returns the catalog entry for device and the matching peak_flops capability.
func peakFLOPs(device *Device) (*PeakFLOPs, Capability) {
	if device == nil || device.Name == "" {
		return nil, Capability{Status: "unavailable", Reason: "device_unknown"}
	}
	entry, ok := peakFLOPsByDevice[device.Name]
	if !ok {
		return nil, Capability{Status: "unavailable", Reason: "device_not_in_catalog"}
	}
	byDType := map[string]float64{"bf16": entry.bf16}
	if entry.fp8 > 0 {
		byDType["fp8"] = entry.fp8
	}
	peak := &PeakFLOPs{
		CatalogVersion: PeakFLOPsCatalogVersion,
		Device:         entry.device,
		DType:          "bf16",
		PerGPU:         entry.bf16,
		PerGPUByDType:  byDType,
		Source:         entry.source,
	}
	return peak, Capability{Status: "available"}
}

// Build identifies the SDK build that produced a writer's files, as injected by the launcher.
type Build struct {
	BaseCommit       string `json:"base_commit,omitempty"`
	SourceDiffSHA256 string `json:"source_diff_sha256,omitempty"`
	WheelSHA256      string `json:"wheel_sha256,omitempty"`
	ImageDigest      string `json:"image_digest,omitempty"`
}

// buildIdentity returns the launcher-provided build identity and the build_identity capability.
func buildIdentity() (*Build, Capability) {
	isHex := func(value string) bool { return value != "" && strings.Trim(value, "0123456789abcdef") == "" }
	isSHA256Hex := func(value string) bool { return len(value) == 64 && isHex(value) }
	isImageDigest := func(value string) bool {
		return strings.HasPrefix(value, "sha256:") && isSHA256Hex(value[len("sha256:"):])
	}
	fields := []struct {
		env   string
		valid func(string) bool
		into  func(*Build, string)
	}{
		{
			"WANDB_X_PROVENANCE_BUILD_BASE_COMMIT",
			func(v string) bool { return len(v) == 40 && isHex(v) },
			func(b *Build, v string) { b.BaseCommit = v },
		},
		{
			"WANDB_X_PROVENANCE_BUILD_SOURCE_DIFF_SHA256",
			isSHA256Hex,
			func(b *Build, v string) { b.SourceDiffSHA256 = v },
		},
		{
			"WANDB_X_PROVENANCE_BUILD_WHEEL_SHA256",
			isSHA256Hex,
			func(b *Build, v string) { b.WheelSHA256 = v },
		},
		{
			"WANDB_X_PROVENANCE_BUILD_IMAGE_DIGEST",
			isImageDigest,
			func(b *Build, v string) { b.ImageDigest = v },
		},
	}
	build := &Build{}
	provided, accepted := 0, 0
	for _, field := range fields {
		value := os.Getenv(field.env)
		if value == "" {
			continue
		}
		provided++
		if field.valid(value) {
			accepted++
			field.into(build, value)
		}
	}
	switch {
	case provided == 0:
		return nil, Capability{Status: "unavailable", Reason: "not_provided"}
	case accepted == 0:
		return nil, Capability{Status: "unavailable", Reason: "invalid_build_identity"}
	case accepted < provided:
		return build, Capability{Status: "partial", Reason: "invalid_build_identity"}
	case accepted < len(fields):
		return build, Capability{Status: "partial", Reason: "incomplete_build_identity"}
	}
	return build, Capability{Status: "available"}
}
