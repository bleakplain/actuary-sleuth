#!/usr/bin/env bash
cd "$(dirname "$0")/web"
node node_modules/vite/bin/vite.js "$@"
