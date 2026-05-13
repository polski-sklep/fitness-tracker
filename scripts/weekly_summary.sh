#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
python -m scripts.weekly_summary

