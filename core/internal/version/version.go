package version

import "strings"

const Version = "0.27.3.dev1"

const MinServerVersion = "0.65.0"

var Environment string

func init() {
	if strings.Contains(Version, "dev") {
		Environment = "development"
	} else {
		Environment = "production"
	}
}
