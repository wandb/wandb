package systemmetrics

import (
	"regexp"
	"strconv"
	"strings"
	"sync"

	"github.com/wandb/simplejsonext"
	"google.golang.org/protobuf/reflect/protoreflect"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// FromStatsRecord converts a legacy StatsRecord, as wandb-xpu still emits,
// into a typed record.
//
// Keys are matched against the legacy templates in the schema. hint picks the
// accelerator type when vendors share a key (gpu.<i>.temp is NVIDIA, AMD and
// Apple). Keys no template matches are kept as GenericMetric entries without
// a source, so they render back unchanged.
func FromStatsRecord(rec *spb.StatsRecord, hint spb.AcceleratorType) *spb.SystemMetricsRecord {
	out := &spb.SystemMetricsRecord{Timestamp: rec.GetTimestamp()}
	root := out.ProtoReflect()

	for _, item := range rec.GetItem() {
		value, ok := numericJSON(item.GetValueJson())
		if !ok || item.GetKey() == "" {
			continue
		}
		key := item.GetKey()

		if setTPUDistribution(out, key, value) {
			continue
		}
		if m, vars := matchLegacy(key, hint); m != nil {
			m.set(root, vars, value)
			continue
		}
		out.Generic = append(out.Generic, &spb.GenericMetric{Name: key, Value: &value})
	}
	return out
}

func numericJSON(text string) (float64, bool) {
	v, err := simplejsonext.UnmarshalString(text)
	if err != nil {
		return 0, false
	}
	switch n := v.(type) {
	case float64:
		return n, true
	case int64:
		return float64(n), true
	}
	return 0, false
}

// matcher is one legacy template compiled to a regexp, with the path to the
// field it belongs to.
type matcher struct {
	re          *regexp.Regexp
	path        []protoreflect.FieldDescriptor
	accel       spb.AcceleratorType
	source      string
	unit        string
	legacyUnit  string
	processCopy bool
}

var (
	matchersOnce sync.Once
	matchers     []*matcher
)

var placeholderPatterns = map[string]string{
	"index":  `(?P<index>\d+)`,
	"series": `(?P<series>\d+)`,
	"path":   `(?P<path>.+)`,
	"device": `(?P<device>[^.]+)`,
	"label":  `(?P<label>[^.]+)`,
	"source": `(?P<source>[^.]+)`,
	"name":   `(?P<name>.+)`,
}

// extTypes maps the accelerator extension fields to the type they imply.
var extTypes = map[protoreflect.Name]spb.AcceleratorType{
	"nvidia":   spb.AcceleratorType_NVIDIA_GPU,
	"amd":      spb.AcceleratorType_AMD_GPU,
	"tpu":      spb.AcceleratorType_GOOGLE_TPU,
	"trainium": spb.AcceleratorType_AWS_TRAINIUM,
}

// sourceForType is the collector wandb-xpu uses for each accelerator type.
var sourceForType = map[spb.AcceleratorType]string{
	spb.AcceleratorType_NVIDIA_GPU:   "nvml",
	spb.AcceleratorType_AMD_GPU:      "rocm-smi",
	spb.AcceleratorType_APPLE_GPU:    "ioreport",
	spb.AcceleratorType_APPLE_ANE:    "ioreport",
	spb.AcceleratorType_GOOGLE_TPU:   "libtpu",
	spb.AcceleratorType_AWS_TRAINIUM: "neuron-monitor",
}

func buildMatchers() {
	var visit func(md protoreflect.MessageDescriptor, path []protoreflect.FieldDescriptor, implied spb.AcceleratorType)
	visit = func(md protoreflect.MessageDescriptor, path []protoreflect.FieldDescriptor, implied spb.AcceleratorType) {
		fields := md.Fields()
		for i := 0; i < fields.Len(); i++ {
			fd := fields.Get(i)
			fieldPath := append(append([]protoreflect.FieldDescriptor{}, path...), fd)

			if fd.Kind() == protoreflect.MessageKind && !fd.IsMap() {
				if fd.Message().FullName() == "google.protobuf.Timestamp" ||
					fd.Message().Name() == "_RecordInfo" {
					continue
				}
				childImplied := implied
				if t, ok := extTypes[fd.Name()]; ok {
					childImplied = t
				}
				visit(fd.Message(), fieldPath, childImplied)
				continue
			}

			info := metricInfo(fd)
			if info == nil {
				continue
			}
			for _, lk := range info.GetLegacy() {
				accel := lk.GetAcceleratorType()
				if accel == spb.AcceleratorType_ACCELERATOR_UNSPECIFIED {
					accel = implied
				}
				matchers = append(matchers, &matcher{
					re:         templateRegexp(lk.GetTemplate()),
					path:       fieldPath,
					accel:      accel,
					source:     lk.GetSource(),
					unit:       info.GetUnit(),
					legacyUnit: lk.GetUnit(),
				})
				if info.GetLegacyProcessCopy() {
					matchers = append(matchers, &matcher{
						re:          templateRegexp(processCopyTemplate(lk.GetTemplate())),
						path:        fieldPath,
						accel:       accel,
						source:      lk.GetSource(),
						processCopy: true,
					})
				}
			}
		}
	}
	visit(
		(&spb.SystemMetricsRecord{}).ProtoReflect().Descriptor(),
		nil,
		spb.AcceleratorType_ACCELERATOR_UNSPECIFIED,
	)
}

func templateRegexp(template string) *regexp.Regexp {
	pattern := regexp.QuoteMeta(template)
	for name, sub := range placeholderPatterns {
		pattern = strings.ReplaceAll(pattern, `\{`+name+`\}`, sub)
	}
	return regexp.MustCompile("^" + pattern + "$")
}

// matchLegacy finds the template a key was rendered from. When templates of
// several accelerator types match, the hinted type wins, then a type-less
// template, then NVIDIA, then the first match.
func matchLegacy(key string, hint spb.AcceleratorType) (*matcher, map[string]string) {
	matchersOnce.Do(buildMatchers)

	type hit struct {
		m    *matcher
		vars map[string]string
	}
	var hits []hit
	for _, m := range matchers {
		sub := m.re.FindStringSubmatch(key)
		if sub == nil {
			continue
		}
		vars := make(map[string]string)
		for i, name := range m.re.SubexpNames() {
			if name != "" {
				vars[name] = sub[i]
			}
		}
		hits = append(hits, hit{m, vars})
	}
	if len(hits) == 0 {
		return nil, nil
	}

	for _, want := range []spb.AcceleratorType{
		hint,
		spb.AcceleratorType_ACCELERATOR_UNSPECIFIED,
		spb.AcceleratorType_NVIDIA_GPU,
	} {
		for _, h := range hits {
			if h.m.accel == want {
				return h.m, h.vars
			}
		}
	}
	return hits[0].m, hits[0].vars
}

// set writes value into the record at the matcher's path, creating the
// enclosing messages and list elements it needs.
func (m *matcher) set(root protoreflect.Message, vars map[string]string, value float64) {
	cur := root
	for _, fd := range m.path[:len(m.path)-1] {
		if fd.IsList() {
			cur = m.listElement(cur.Mutable(fd).List(), fd.Message(), vars)
		} else {
			cur = cur.Mutable(fd).Message()
		}
	}

	leaf := m.path[len(m.path)-1]
	if m.processCopy {
		if fd := cur.Descriptor().Fields().ByName("in_use_by_process"); fd != nil {
			cur.Set(fd, protoreflect.ValueOfBool(true))
		}
		return
	}

	value = fromLegacyUnit(value, m.unit, m.legacyUnit)
	switch leaf.Kind() {
	case protoreflect.DoubleKind:
		cur.Set(leaf, protoreflect.ValueOfFloat64(value))
	case protoreflect.FloatKind:
		cur.Set(leaf, protoreflect.ValueOfFloat32(float32(value)))
	case protoreflect.Uint64Kind:
		cur.Set(leaf, protoreflect.ValueOfUint64(uint64(value)))
	case protoreflect.Uint32Kind:
		cur.Set(leaf, protoreflect.ValueOfUint32(uint32(value)))
	case protoreflect.Int64Kind:
		cur.Set(leaf, protoreflect.ValueOfInt64(int64(value)))
	case protoreflect.Int32Kind:
		cur.Set(leaf, protoreflect.ValueOfInt32(int32(value)))
	}
}

// identityFields are the scalar fields that distinguish list elements.
var identityFields = []protoreflect.Name{"index", "path", "device", "label", "name", "type"}

// listElement returns the element of list whose identity matches vars and the
// matcher's accelerator type, appending a new one when there is none.
func (m *matcher) listElement(
	list protoreflect.List,
	md protoreflect.MessageDescriptor,
	vars map[string]string,
) protoreflect.Message {
	want := m.identity(md, vars)

	for i := 0; i < list.Len(); i++ {
		elem := list.Get(i).Message()
		same := true
		for fd, v := range want {
			if !elem.Get(fd).Equal(v) {
				same = false
				break
			}
		}
		if same {
			return elem
		}
	}

	elem := list.NewElement()
	msg := elem.Message()
	for fd, v := range want {
		msg.Set(fd, v)
	}
	if fd := md.Fields().ByName("source"); fd != nil && md.Name() == "AcceleratorMetrics" {
		source := m.source
		if source == "" {
			source = sourceForType[m.accel]
		}
		msg.Set(fd, protoreflect.ValueOfString(source))
	}
	list.Append(elem)
	return msg
}

func (m *matcher) identity(
	md protoreflect.MessageDescriptor,
	vars map[string]string,
) map[protoreflect.FieldDescriptor]protoreflect.Value {
	want := make(map[protoreflect.FieldDescriptor]protoreflect.Value)
	for _, name := range identityFields {
		fd := md.Fields().ByName(name)
		if fd == nil {
			continue
		}
		switch name {
		case "type":
			want[fd] = protoreflect.ValueOfEnum(protoreflect.EnumNumber(m.accel))
		case "index":
			n, _ := strconv.ParseUint(vars["index"], 10, 32)
			want[fd] = protoreflect.ValueOfUint32(uint32(n))
		default:
			want[fd] = protoreflect.ValueOfString(vars[string(name)])
		}
	}
	return want
}

var tpuDistributionKey = regexp.MustCompile(
	`^tpu\.(?P<name>[A-Za-z0-9]+)(?:\.(?P<label>[^.]+))?\.(?P<stat>mean|p50|p90|p95|p99|p999)(?P<unit>Us|Mbps)$`,
)

// setTPUDistribution parses a TPU runtime distribution stat key into
// TpuRuntimeMetrics. It reports whether the key was one.
func setTPUDistribution(out *spb.SystemMetricsRecord, key string, value float64) bool {
	sub := tpuDistributionKey.FindStringSubmatch(key)
	if sub == nil {
		return false
	}
	name, label, stat := sub[1], sub[2], sub[3]

	var kind spb.TpuRuntimeMetrics_DistributionKind
	found := false
	for k, spec := range tpuDistributions {
		if spec.name == name {
			kind, found = k, true
			break
		}
	}
	if !found {
		return false
	}

	if out.TpuRuntime == nil {
		out.TpuRuntime = &spb.TpuRuntimeMetrics{}
	}
	var dist *spb.TpuRuntimeMetrics_Distribution
	for _, d := range out.TpuRuntime.Distributions {
		if d.GetKind() == kind && d.GetLabel() == label {
			dist = d
			break
		}
	}
	if dist == nil {
		dist = &spb.TpuRuntimeMetrics_Distribution{Kind: kind, Label: label}
		out.TpuRuntime.Distributions = append(out.TpuRuntime.Distributions, dist)
	}

	switch stat {
	case "mean":
		dist.Mean = &value
	case "p50":
		dist.P50 = &value
	case "p90":
		dist.P90 = &value
	case "p95":
		dist.P95 = &value
	case "p99":
		dist.P99 = &value
	case "p999":
		dist.P999 = &value
	}
	return true
}
