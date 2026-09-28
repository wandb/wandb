// Package systemmetrics renders SystemMetricsRecord values in the legacy
// string-keyed form used by the filestream, leet and the in-memory buffer, and
// converts legacy StatsRecord items back into the typed record.
//
// Both directions are driven by the MetricInfo options on the proto fields, so
// wandb/proto/wandb_system_metrics.proto stays the only catalog of system
// metrics and their legacy keys.
package systemmetrics

import (
	"maps"
	"sort"
	"strconv"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/types/descriptorpb"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Item is one legacy system metric: the collector key, without the "system."
// prefix and without the writer label, and its value in the legacy unit.
type Item struct {
	Key   string
	Value float64
}

// Items renders the legacy items of a record, sorted by key.
//
// Accelerators with a host get "/l:<host>" appended to their keys, and fields
// marked legacy_process_copy are repeated under gpu.process.<index>.* when the
// device is in use by the monitored process. The writer label is not applied;
// see LegacyRow.
func Items(rec *spb.SystemMetricsRecord) []Item {
	if rec == nil {
		return nil
	}

	var items []Item
	emit := func(key string, value float64) {
		items = append(items, Item{Key: key, Value: value})
	}

	walk(rec.ProtoReflect(), scope{}, emit)
	tpuDistributionItems(rec.GetTpuRuntime(), emit)

	sort.SliceStable(items, func(i, j int) bool { return items[i].Key < items[j].Key })
	return items
}

// LegacyRow returns the wandb-events.jsonl row for a record: every item under
// "system.<key>", suffixed with "/l:<label>" when the record has a writer
// label, plus the _wandb, _timestamp and _runtime fields.
func LegacyRow(rec *spb.SystemMetricsRecord, startTime time.Time) map[string]any {
	ts := rec.GetTimestamp()

	row := make(map[string]any)
	row["_wandb"] = true
	row["_timestamp"] = float64(ts.GetSeconds()) + float64(ts.GetNanos())/1e9
	row["_runtime"] = ts.AsTime().Sub(startTime).Seconds()

	suffix := ""
	if label := rec.GetLabel(); label != "" {
		suffix = "/l:" + label
	}
	for _, item := range Items(rec) {
		row["system."+item.Key+suffix] = item.Value
	}
	return row
}

// scope carries what a leaf needs from its enclosing messages: the accelerator
// type and source that select a legacy template, the host suffix, whether the
// device is in use by the process, and the placeholder values.
type scope struct {
	accel  spb.AcceleratorType
	source string
	host   string
	inUse  bool
	vars   map[string]string
}

// child derives the scope for a message from the parent scope and the
// message's identity fields (index, path, device, label, name, source, type,
// host, in_use_by_process, legacy_series_index).
func (s scope) child(m protoreflect.Message) scope {
	c := scope{
		accel:  s.accel,
		source: s.source,
		host:   s.host,
		inUse:  s.inUse,
		vars:   make(map[string]string, len(s.vars)+4),
	}
	maps.Copy(c.vars, s.vars)

	fields := m.Descriptor().Fields()
	for i := 0; i < fields.Len(); i++ {
		fd := fields.Get(i)
		if fd.Kind() == protoreflect.MessageKind || fd.IsList() || metricInfo(fd) != nil {
			continue
		}
		v := m.Get(fd)
		switch fd.Name() {
		case "index":
			c.vars["index"] = strconv.FormatUint(v.Uint(), 10)
		case "legacy_series_index":
			c.vars["series"] = strconv.FormatUint(v.Uint(), 10)
		case "path", "device", "label", "name":
			c.vars[string(fd.Name())] = v.String()
		case "source":
			c.vars["source"] = v.String()
			c.source = v.String()
		case "type":
			c.accel = spb.AcceleratorType(v.Enum())
		case "host":
			c.host = v.String()
		case "in_use_by_process":
			c.inUse = v.Bool()
		}
	}
	return c
}

func walk(m protoreflect.Message, parent scope, emit func(string, float64)) {
	s := parent.child(m)
	m.Range(func(fd protoreflect.FieldDescriptor, v protoreflect.Value) bool {
		switch {
		case fd.IsMap():
		case fd.IsList() && fd.Kind() == protoreflect.MessageKind:
			list := v.List()
			for i := 0; i < list.Len(); i++ {
				walk(list.Get(i).Message(), s, emit)
			}
		case fd.Kind() == protoreflect.MessageKind:
			walk(v.Message(), s, emit)
		default:
			if info := metricInfo(fd); info != nil {
				emitLeaf(fd, v, info, s, emit)
			}
		}
		return true
	})
}

func emitLeaf(
	fd protoreflect.FieldDescriptor,
	v protoreflect.Value,
	info *spb.MetricInfo,
	s scope,
	emit func(string, float64),
) {
	lk := pickLegacy(info.GetLegacy(), s.accel, s.source)
	if lk == nil {
		return
	}
	value := toLegacyUnit(numeric(fd, v), info.GetUnit(), lk.GetUnit())

	key := s.expand(lk.GetTemplate())
	emit(key, value)

	if info.GetLegacyProcessCopy() && s.inUse {
		emit(s.expand(processCopyTemplate(lk.GetTemplate())), value)
	}
}

// expand fills a template's placeholders and appends the host suffix.
//
// A GenericMetric without a source is a first-party key the schema does not
// model; its legacy key is the name as the producer emitted it.
func (s scope) expand(template string) string {
	var key string
	if strings.Contains(template, "{source}") && s.vars["source"] == "" {
		key = s.vars["name"]
	} else {
		key = template
		for name, value := range s.vars {
			key = strings.ReplaceAll(key, "{"+name+"}", value)
		}
	}
	if s.host != "" {
		key += "/l:" + s.host
	}
	return key
}

func processCopyTemplate(template string) string {
	return strings.Replace(template, "gpu.{index}.", "gpu.process.{index}.", 1)
}

// pickLegacy selects the most specific template for an accelerator type and
// source: an entry naming both beats one naming the type, which beats one
// naming neither. Entries naming a different type or source never match.
func pickLegacy(entries []*spb.LegacyKey, accel spb.AcceleratorType, source string) *spb.LegacyKey {
	var best *spb.LegacyKey
	bestScore := -1
	for _, e := range entries {
		score := 0
		if t := e.GetAcceleratorType(); t != spb.AcceleratorType_ACCELERATOR_UNSPECIFIED {
			if t != accel {
				continue
			}
			score += 2
		}
		if src := e.GetSource(); src != "" {
			if src != source {
				continue
			}
			score++
		}
		if score > bestScore {
			best, bestScore = e, score
		}
	}
	return best
}

func numeric(fd protoreflect.FieldDescriptor, v protoreflect.Value) float64 {
	switch fd.Kind() {
	case protoreflect.DoubleKind, protoreflect.FloatKind:
		return v.Float()
	case protoreflect.Uint32Kind, protoreflect.Uint64Kind,
		protoreflect.Fixed32Kind, protoreflect.Fixed64Kind:
		return float64(v.Uint())
	case protoreflect.Int32Kind, protoreflect.Int64Kind,
		protoreflect.Sint32Kind, protoreflect.Sint64Kind,
		protoreflect.Sfixed32Kind, protoreflect.Sfixed64Kind:
		return float64(v.Int())
	}
	return 0
}

// unitScale returns the factor from a canonical unit to a legacy unit.
func unitScale(from, to string) float64 {
	switch from + ">" + to {
	case "By>MiBy":
		return 1.0 / (1 << 20)
	case "By>GiBy":
		return 1.0 / (1 << 30)
	case "J>mJ":
		return 1000
	}
	return 1
}

func toLegacyUnit(value float64, unit, legacyUnit string) float64 {
	if legacyUnit == "" || legacyUnit == unit {
		return value
	}
	return value * unitScale(unit, legacyUnit)
}

func fromLegacyUnit(value float64, unit, legacyUnit string) float64 {
	if legacyUnit == "" || legacyUnit == unit {
		return value
	}
	return value / unitScale(unit, legacyUnit)
}

func metricInfo(fd protoreflect.FieldDescriptor) *spb.MetricInfo {
	opts, ok := fd.Options().(*descriptorpb.FieldOptions)
	if !ok || opts == nil || !proto.HasExtension(opts, spb.E_Metric) {
		return nil
	}
	info, _ := proto.GetExtension(opts, spb.E_Metric).(*spb.MetricInfo)
	return info
}

// tpuDistribution is the legacy key name and stat unit suffix of a TPU runtime
// distribution kind. Keys are tpu.<name>[.<label>].<stat><unit>.
type tpuDistribution struct {
	name string
	unit string
}

var tpuDistributions = map[spb.TpuRuntimeMetrics_DistributionKind]tpuDistribution{
	spb.TpuRuntimeMetrics_BUFFER_TRANSFER_LATENCY:         {"bufferTransferLatency", "Us"},
	spb.TpuRuntimeMetrics_INBOUND_BUFFER_TRANSFER_LATENCY: {"inboundBufferTransferLatency", "Us"},
	spb.TpuRuntimeMetrics_HOST_TO_DEVICE_TRANSFER_LATENCY: {"hostToDeviceTransferLatency", "Us"},
	spb.TpuRuntimeMetrics_DEVICE_TO_HOST_TRANSFER_LATENCY: {"deviceToHostTransferLatency", "Us"},
	spb.TpuRuntimeMetrics_COLLECTIVE_E2E_LATENCY:          {"collectiveE2ELatency", "Us"},
	spb.TpuRuntimeMetrics_HOST_COMPUTE_LATENCY:            {"hostComputeLatency", "Us"},
	spb.TpuRuntimeMetrics_GRPC_TCP_MIN_RTT:                {"grpcTcpMinRtt", "Us"},
	spb.TpuRuntimeMetrics_GRPC_TCP_DELIVERY_RATE:          {"grpcTcpDeliveryRate", "Mbps"},
	spb.TpuRuntimeMetrics_HLO_EXEC_TIMING:                 {"hloExecTiming", "Us"},
}

var tpuStats = []string{"mean", "p50", "p90", "p95", "p99", "p999"}

func tpuDistributionStats(d *spb.TpuRuntimeMetrics_Distribution) []*float64 {
	return []*float64{d.Mean, d.P50, d.P90, d.P95, d.P99, d.P999}
}

func tpuDistributionItems(tr *spb.TpuRuntimeMetrics, emit func(string, float64)) {
	for _, d := range tr.GetDistributions() {
		spec, ok := tpuDistributions[d.GetKind()]
		if !ok {
			continue
		}
		base := "tpu." + spec.name
		if d.GetLabel() != "" {
			base += "." + d.GetLabel()
		}
		for i, value := range tpuDistributionStats(d) {
			if value != nil {
				emit(base+"."+tpuStats[i]+spec.unit, *value)
			}
		}
	}
}
