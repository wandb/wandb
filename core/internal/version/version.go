package version

import "strings"

const Version = "0.25.1rc20260303"

const MinServerVersion = "0.40.0"

var Environment string

func init() {
	if strings.Contains(Version, "dev") {
		Environment = "development"
	} else {
		Environment = "production"
	}
}
