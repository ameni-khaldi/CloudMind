FROM golang:1.24-bookworm AS build
ARG MINIO_RELEASE=RELEASE.2025-09-07T16-13-09Z
WORKDIR /src
RUN git clone --depth 1 --branch "${MINIO_RELEASE}" https://github.com/minio/minio.git . \
    && test "$(git rev-parse --short=12 HEAD)" = "07c3a429bfed" \
    && CGO_ENABLED=0 go build -trimpath \
        -ldflags "-s -w -X github.com/minio/minio/cmd.Version=2025-09-07T16:13:09Z -X github.com/minio/minio/cmd.ReleaseTag=${MINIO_RELEASE} -X github.com/minio/minio/cmd.CommitID=$(git rev-parse HEAD)" \
        -o /out/minio .

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/minio /usr/local/bin/minio
COPY --from=build /src/LICENSE /usr/share/doc/minio/LICENSE
ENTRYPOINT ["/usr/local/bin/minio"]
