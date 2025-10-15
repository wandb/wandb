license:
	curl -sL https://liam.sh/-/gh/g/license-header.sh | bash -s

fetch:
	go mod download
	go mod tidy

up:
	go get -u ./... && go mod tidy
	cd examples && go get -u ./... && go mod tidy

test:
	go test -v ./...
	cd examples && go test -v ./...

fuzz:
	go test -fuzz=FuzzScan -timeout=1m

bench:
	go test -bench=.

pprof:
	go test -bench=. -benchmem -memprofile memprofile.out -cpuprofile profile.out
	go tool pprof -http=:8081 profile.out
