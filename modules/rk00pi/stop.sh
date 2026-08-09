#!/bin/sh
set -e
systemctl stop rk00pi.service 2>/dev/null || true
systemctl disable rk00pi.service 2>/dev/null || true
exit 0
