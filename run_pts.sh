#!/usr/bin/env bash
set -euo pipefail
# Relative input/output arguments are resolved against the caller's directory.
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
  case "${args[$i]}" in
    /*) ;;
    *) args[$i]="$PWD/${args[$i]}" ;;
  esac
done
cd "$(dirname "$0")"
python_bin="${KVC_PYTHON:-$PWD/.venv/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  echo 'Python environment missing. Run: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-pts.txt' >&2
  exit 1
fi
"$python_bin" -c 'import av'
mvn -q compile dependency:build-classpath -Dmdep.outputFile=target/pts-classpath.txt
java_args=("-Dkvc.python=$python_bin")
if [[ -n "${KVC_PTS_AUDIT:-}" ]]; then
  java_args+=("-Dkvc.pts.audit=$KVC_PTS_AUDIT")
fi
exec java "${java_args[@]}" -cp "target/classes:$(cat target/pts-classpath.txt)" \
  xin.chunming.KvcProbe_ffmpeg "${args[@]}"
