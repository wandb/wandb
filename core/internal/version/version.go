package version

import "strings"

const Version = "0.26.0rc20260409001"

const MinServerVersion = "0.40.0"

var Environment string

func init() {
	if strings.Contains(Version, "dev") {
		Environment = "development"
	} else {
		Environment = "production"
	}
}
