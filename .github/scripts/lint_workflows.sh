#!/usr/bin/env bash
set -euo pipefail

# Version and archive hashes are pinned to the upstream release. No global install.
hec_actionlint_version=1.7.12
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)
    hec_actionlint_platform=linux_amd64
    hec_actionlint_sha=8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8
    ;;
  Darwin-arm64)
    hec_actionlint_platform=darwin_arm64
    hec_actionlint_sha=aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f
    ;;
  Darwin-x86_64)
    hec_actionlint_platform=darwin_amd64
    hec_actionlint_sha=5b44c3bc2255115c9b69e30efc0fecdf498fdb63c5d58e17084fd5f16324c644
    ;;
  *) echo "unsupported workflow-lint platform" >&2; exit 1 ;;
esac
hec_actionlint_dir=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/hec-actionlint.XXXXXX")
trap 'rm -f "$hec_actionlint_dir/actionlint" "$hec_actionlint_dir/actionlint.tar.gz"; rmdir "$hec_actionlint_dir"' EXIT
curl --fail --location --retry 2 --silent --show-error \
  "https://github.com/rhysd/actionlint/releases/download/v${hec_actionlint_version}/actionlint_${hec_actionlint_version}_${hec_actionlint_platform}.tar.gz" \
  --output "$hec_actionlint_dir/actionlint.tar.gz"
printf '%s  %s\n' "$hec_actionlint_sha" "$hec_actionlint_dir/actionlint.tar.gz" | shasum -a 256 --check --status
tar -xzf "$hec_actionlint_dir/actionlint.tar.gz" -C "$hec_actionlint_dir" actionlint
"$hec_actionlint_dir/actionlint"
