#!/bin/sh
set -eu
image=${1:-zerodev:latest}
docker run --rm --mount type=volume,destination=/home/zero/.zero --entrypoint sh "$image" -ec '
  test "$(id -u)" = 1000
  ls -ld /home/zero/.zero
  test -w /home/zero/.zero
  mkdir /home/zero/.zero/registry
  printf "cache inscriptible sans root\n"
'
