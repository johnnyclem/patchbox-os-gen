#!/bin/sh
# Stand the launcher down without starting a sibling (MODEP / none may be next).
set -e
systemctl stop rangerdeck.service 2>/dev/null || true
systemctl disable rangerdeck.service 2>/dev/null || true
exit 0
