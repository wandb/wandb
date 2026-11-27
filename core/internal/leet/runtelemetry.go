package leet

import (
	"cmp"
	"maps"
	"slices"
	"strconv"
	"strings"
	"time"

	"google.golang.org/protobuf/reflect/protoreflect"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// sessionRuns collects facts about the runs loaded during this process.
var sessionRuns = &observedRuns{byID: map[string]*observedRun{}}

type observedRuns struct {
	byID map[string]*observedRun
}

type observedRun struct {
	entity     string
	sdkVersion string
	frameworks []string
	startTime  time.Time
	offline    bool
	viewed     bool
}

// observe records telemetry-relevant facts about a loaded run.
func (rs *observedRuns) observe(msg RunMsg, viewed bool) {
	if msg.ID == "" {
		return
	}

	run := rs.byID[msg.ID]
	if run == nil {
		run = &observedRun{}
		rs.byID[msg.ID] = run
	}
	run.viewed = run.viewed || viewed
	run.offline = run.offline || msg.Telemetry.GetFeature().GetOffline()
	if msg.Entity != "" {
		run.entity = msg.Entity
	}
	if !msg.StartTime.IsZero() {
		run.startTime = msg.StartTime
	}
	if v := msg.Telemetry.GetCliVersion(); v != "" {
		run.sdkVersion = v
	}
	frameworks := importNames(
		msg.Telemetry.GetImportsInit(), msg.Telemetry.GetImportsFinish())
	if len(frameworks) > 0 {
		run.frameworks = frameworks
	}
}

func (rs *observedRuns) attributes() map[string]string {
	if len(rs.byID) == 0 {
		return nil
	}

	var viewed, offline int
	var newestStart time.Time
	entityCounts := map[string]int{}
	sdkVersions := map[string]struct{}{}
	frameworks := map[string]struct{}{}
	for _, run := range rs.byID {
		if run.viewed {
			viewed++
		}
		if run.offline {
			offline++
		}
		if run.startTime.After(newestStart) {
			newestStart = run.startTime
		}
		if run.entity != "" {
			entityCounts[run.entity]++
		}
		if run.sdkVersion != "" {
			sdkVersions[run.sdkVersion] = struct{}{}
		}
		for _, framework := range run.frameworks {
			frameworks[framework] = struct{}{}
		}
	}

	attrs := map[string]string{
		"run_count":         strconv.Itoa(len(rs.byID)),
		"run_viewed_count":  strconv.Itoa(viewed),
		"run_offline_count": strconv.Itoa(offline),
	}
	if entity := topEntity(entityCounts); entity != "" {
		attrs["entity"] = entity
	}
	if len(sdkVersions) > 0 {
		versions := slices.SortedFunc(maps.Keys(sdkVersions), compareVersions)
		attrs["run_sdk_version_oldest"] = versions[0]
		attrs["run_sdk_version_newest"] = versions[len(versions)-1]
	}
	if len(frameworks) > 0 {
		attrs["run_frameworks"] = strings.Join(slices.Sorted(maps.Keys(frameworks)), ",")
	}
	if !newestStart.IsZero() {
		attrs["run_age_newest"] = ageBucket(time.Since(newestStart))
	}
	return attrs
}

// importNames returns the sorted names of the frameworks set in the given
// telemetry import records.
func importNames(records ...*spb.Imports) []string {
	names := map[string]struct{}{}
	for _, record := range records {
		if record == nil {
			continue
		}
		record.ProtoReflect().Range(
			func(fd protoreflect.FieldDescriptor, v protoreflect.Value) bool {
				if fd.Kind() == protoreflect.BoolKind && v.Bool() {
					names[string(fd.Name())] = struct{}{}
				}
				return true
			})
	}
	return slices.Sorted(maps.Keys(names))
}

// topEntity returns the most frequent entity, breaking ties alphabetically.
func topEntity(counts map[string]int) string {
	var top string
	var topCount int
	for entity, count := range counts {
		if count > topCount || (count == topCount && entity < top) {
			top, topCount = entity, count
		}
	}
	return top
}

// compareVersions orders wandb version strings like "0.10.20.dev1" by
// their leading numeric fields, then by the full string.
func compareVersions(a, b string) int {
	return cmp.Or(
		slices.Compare(versionFields(a), versionFields(b)),
		strings.Compare(a, b),
	)
}

func versionFields(version string) []int {
	var fields []int
	for part := range strings.SplitSeq(version, ".") {
		n, err := strconv.Atoi(part)
		if err != nil {
			break
		}
		fields = append(fields, n)
	}
	return fields
}

// ageBucket buckets an age into lt_1h, lt_1d, lt_7d, lt_30d or ge_30d.
func ageBucket(age time.Duration) string {
	switch {
	case age < time.Hour:
		return "lt_1h"
	case age < 24*time.Hour:
		return "lt_1d"
	case age < 7*24*time.Hour:
		return "lt_7d"
	case age < 30*24*time.Hour:
		return "lt_30d"
	default:
		return "ge_30d"
	}
}
