#!/bin/sh
# Backup right now (Linux/macOS).
cd "$(dirname "$0")" && docker exec trs398_backup sh /backup.sh --once
