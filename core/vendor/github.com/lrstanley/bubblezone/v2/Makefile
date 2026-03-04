license:
	curl -sL https://liam.sh/-/gh/g/license-header.sh | bash -s

fetch:
	go mod download
	go mod tidy

up:
	go get -u ./... && go mod tidy
	cd _examples/ && go get -u ./... && go mod tidy

test:
	GORACE="exitcode=1 halt_on_error=1" go test -v -race -timeout 3m -count 3 -cpu 1,4 ./...
	cd _examples/ && GORACE="exitcode=1 halt_on_error=1" go test -v -race -timeout 3m -count 3 -cpu 1,4 ./...

fuzz:
	go test -fuzz=FuzzScan -timeout=1m

bench:
	go test -bench=.

pprof:
	go test -bench=. -benchmem -memprofile memprofile.out -cpuprofile profile.out
	go tool pprof -http=:8081 profile.out
