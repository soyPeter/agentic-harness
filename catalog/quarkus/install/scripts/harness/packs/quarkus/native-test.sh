#!/usr/bin/env bash
# Run Quarkus native tests with an in-container Mandrel build (Gradle testNative or Maven verify).
# See .claude/skills/quarkus/native.md for troubleshooting.
set -euo pipefail

BUILDER_IMAGE="${BUILDER_IMAGE:-quay.io/quarkus/ubi9-quarkus-mandrel-builder-image:jdk-25}"

# Repo root (for backbone/harness.conf); falls back to the current directory outside git.
repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

# Read KEY="value" (or KEY=value) from backbone/harness.conf; prints nothing if absent.
conf_value() {
  local file="$repo_root/backbone/harness.conf" line value
  [[ -f "$file" ]] || return 0
  line=$(grep -E "^[[:space:]]*$1=" "$file" | tail -n 1 || true)
  [[ -n "$line" ]] || return 0
  value="${line#*=}"
  value="${value%\"}"; value="${value#\"}"
  value="${value%\'}"; value="${value#\'}"
  printf '%s' "$value"
}

# Container runtime: CONTAINER_RUNTIME env, else HARNESS_CONTAINER_ENGINE, else podman if on PATH, else docker.
if [[ -z "${CONTAINER_RUNTIME:-}" ]]; then
  CONTAINER_RUNTIME=$(conf_value HARNESS_CONTAINER_ENGINE)
  if [[ -z "$CONTAINER_RUNTIME" ]]; then
    if command -v podman >/dev/null 2>&1; then CONTAINER_RUNTIME=podman; else CONTAINER_RUNTIME=docker; fi
  fi
fi

# Build tool: BUILD_TOOL env (gradle|maven), else auto-detect from the wrapper in the current directory.
if [[ -z "${BUILD_TOOL:-}" ]]; then
  if [[ -f ./gradlew ]]; then BUILD_TOOL=gradle
  elif [[ -f ./mvnw ]]; then BUILD_TOOL=maven
  else BUILD_TOOL=""
  fi
fi

case "$BUILD_TOOL" in
  gradle) BUILD_CMD="${GRADLE:-./gradlew}"; OUT_DIR=build ;;
  maven)  BUILD_CMD="${MAVEN:-./mvnw}";     OUT_DIR=target ;;
  *)      BUILD_CMD=""; OUT_DIR="" ;;
esac

usage() {
  cat <<EOF
Usage: $(basename "$0") [build-tool args...]

Builds the native executable inside a container and runs the native tests:
  Gradle: \$GRADLE testNative -Dquarkus.native.enabled=true -Dquarkus.native.container-build=true \\
            -Dquarkus.native.container-runtime=\$CONTAINER_RUNTIME -Dquarkus.native.builder-image=\$BUILDER_IMAGE [args...]
  Maven:  \$MAVEN verify -Dquarkus.native.enabled=true -DskipITs=false -Dquarkus.native.container-build=true \\
            -Dquarkus.native.container-runtime=\$CONTAINER_RUNTIME -Dquarkus.native.builder-image=\$BUILDER_IMAGE [args...]
          (native integration tests run in the verify phase through Failsafe)

Environment:
  BUILD_TOOL         gradle or maven     (default: ./gradlew present -> gradle, else ./mvnw present -> maven;
                                          current: ${BUILD_TOOL:-none detected})
  GRADLE             Gradle command      (default: ./gradlew)
  MAVEN              Maven command       (default: ./mvnw)
  CONTAINER_RUNTIME  podman or docker    (default: HARNESS_CONTAINER_ENGINE from backbone/harness.conf,
                                          else podman if on PATH, else docker; current: $CONTAINER_RUNTIME)
  BUILDER_IMAGE      Mandrel builder     (default: quay.io/quarkus/ubi9-quarkus-mandrel-builder-image:jdk-25)

Extra arguments go to the build tool unchanged, e.g.:
  $(basename "$0") -p services/customer --info              # Gradle
  $(basename "$0") -pl services/customer -am                # Maven
  $(basename "$0") -Dquarkus.native.native-image-xmx=6g

Exit status is the build tool's exit status (2 for usage or prerequisite errors).
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
esac

if [[ -z "$BUILD_TOOL" ]]; then
  echo "ERROR: no ./gradlew or ./mvnw in $(pwd). Run from the project root or set BUILD_TOOL=gradle|maven." >&2
  exit 2
fi
if [[ -z "$BUILD_CMD" ]]; then
  echo "ERROR: BUILD_TOOL must be 'gradle' or 'maven' (got '$BUILD_TOOL')." >&2
  exit 2
fi

if ! command -v "$CONTAINER_RUNTIME" >/dev/null 2>&1; then
  echo "ERROR: container runtime '$CONTAINER_RUNTIME' not found on PATH." >&2
  echo "       Install it, or set CONTAINER_RUNTIME (or HARNESS_CONTAINER_ENGINE) to the engine you use: podman or docker." >&2
  exit 2
fi

if ! "$CONTAINER_RUNTIME" info >/dev/null 2>&1; then
  echo "ERROR: '$CONTAINER_RUNTIME info' failed: the runtime is installed but not reachable." >&2
  if [[ "$CONTAINER_RUNTIME" == podman ]]; then
    echo "       macOS/Windows: 'podman machine start'. Linux rootless: 'systemctl --user enable --now podman.socket'." >&2
  else
    echo "       Start Docker Desktop or the Docker daemon, and check access to its socket." >&2
  fi
  exit 2
fi

build_bin="${BUILD_CMD%% *}"
if [[ "$build_bin" == */* ]]; then
  if [[ ! -x "$build_bin" ]]; then
    echo "ERROR: build command '$build_bin' not found or not executable (run from the project root or set GRADLE/MAVEN)." >&2
    exit 2
  fi
elif ! command -v "$build_bin" >/dev/null 2>&1; then
  echo "ERROR: build command '$build_bin' not found on PATH (set GRADLE/MAVEN)." >&2
  exit 2
fi

if [[ "$BUILD_TOOL" == gradle ]]; then
  goal=testNative; extra_flag=""; jvm_tests="./gradlew test"
else
  goal=verify; extra_flag="-DskipITs=false"; jvm_tests="./mvnw test"
fi

echo "== Quarkus native tests ($BUILD_TOOL)"
echo "   runtime: $CONTAINER_RUNTIME   builder: $BUILDER_IMAGE"
echo "   WARNING: a native build plus tests usually takes 5-30 minutes and needs ~8 GB RAM for the build container."
echo "   Run the JVM tests ($jvm_tests) first; native only catches native-specific problems."
echo

marker=$(mktemp "${TMPDIR:-/tmp}/native-test.XXXXXX")
trap 'rm -f "$marker"' EXIT
start=$(date +%s)
status=0
# BUILD_CMD is word-split on purpose so values like "gradle --no-daemon" or "mvn -B" work.
# extra_flag is empty for Gradle; ${extra_flag:+...} avoids passing an empty argument.
# shellcheck disable=SC2086
$BUILD_CMD "$goal" \
  -Dquarkus.native.enabled=true \
  ${extra_flag:+"$extra_flag"} \
  -Dquarkus.native.container-build=true \
  "-Dquarkus.native.container-runtime=$CONTAINER_RUNTIME" \
  "-Dquarkus.native.builder-image=$BUILDER_IMAGE" \
  "$@" || status=$?
end=$(date +%s)
elapsed=$((end - start))

echo
printf '== Finished in %dm%02ds with exit status %d\n' $((elapsed / 60)) $((elapsed % 60)) "$status"

# Portable to bash 3.2 (macOS): no globstar, no empty-array expansion under set -u.
runners=$(find . -path '*/node_modules' -prune -o -type f -path "*/$OUT_DIR/*-runner" -print 2>/dev/null | sort || true)

if [[ -n "$runners" ]]; then
  echo "== Native executable(s):"
  while IFS= read -r f; do
    size=$(du -h "$f" | awk '{print $1}')
    note=""
    [[ "$f" -nt "$marker" ]] || note=", STALE: not rebuilt by this run"
    echo "   ${f#./} ($size$note)"
  done <<<"$runners"
else
  echo "== No $OUT_DIR/*-runner found (native build did not complete, or a different output directory is configured)."
fi

if ((status != 0)); then
  echo "== Native tests FAILED. See .claude/skills/quarkus/native.md (troubleshooting table)." >&2
fi
exit "$status"
