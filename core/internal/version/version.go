package version

import "strings"

const Version = "0.28.2.dev1"

const MinServerVersion = "0.70.0"

var Environment string

func init() {
	if strings.Contains(Version, "dev") {
		Environment = "development"
	} else {
		Environment = "production"
	}
}
