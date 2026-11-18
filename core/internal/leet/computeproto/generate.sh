# Use import paths relative to the project root, which works better with IDEs.
proto_path="${PWD%'core/internal/leet/computeproto'}"
protoc -I"$proto_path" \
    --go_out="$proto_path" \
    --go_opt=paths=source_relative \
    "$PWD/compute.proto"
