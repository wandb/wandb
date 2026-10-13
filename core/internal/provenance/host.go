package provenance

import (
	"math"
	"os"
	"strconv"
	"strings"
)

// HostPaths locates host telemetry files; an empty ProcRoot disables host telemetry.
type HostPaths struct {
	ProcRoot  string
	SysRoot   string
	CgroupDir string
	Pid       int

	// ExcludePid skips this pid and its subtree during the sched walk; 0 excludes nothing.
	ExcludePid int
}

// readPressure adds PSI values for cpu, memory and io to into; false if no file was readable.
func readPressure(path func(resource string) string, into map[string]float64) bool {
	found := false
	for _, res := range []string{"cpu", "memory", "io"} {
		b, err := os.ReadFile(path(res))
		if err != nil {
			continue
		}
		found = true
		for line := range strings.SplitSeq(strings.TrimSpace(string(b)), "\n") {
			fields := strings.Fields(line)
			if len(fields) == 0 || (fields[0] != "some" && fields[0] != "full") {
				continue
			}
			for _, f := range fields[1:] {
				k, v, _ := strings.Cut(f, "=")
				name := map[string]string{"avg10": "avg10", "total": "total_us"}[k]
				if n, err := strconv.ParseFloat(
					v,
					64,
				); err == nil && name != "" && !math.IsNaN(n) &&
					!math.IsInf(n, 0) {
					into["pressure."+res+"."+fields[0]+"_"+name] = n
				}
			}
		}
	}
	return found
}
