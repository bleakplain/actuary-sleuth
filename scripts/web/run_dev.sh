#!/usr/bin/env bash
cd "$(dirname "$0")"
exec node node_modules/vite/bin/vite.js "$@"
