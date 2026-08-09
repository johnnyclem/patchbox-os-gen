#!/bin/sh
set -e
if [ -x /usr/local/bin/patchbox-app ]; then
	/usr/local/bin/patchbox-app enable rk00pi
else
	systemctl stop rangerdeck chordranger midiranger genranger phraseranger \
		sceneranger grooveranger synthranger 2>/dev/null || true
	systemctl disable rangerdeck chordranger midiranger genranger phraseranger \
		sceneranger grooveranger synthranger 2>/dev/null || true
	systemctl enable rk00pi.service
	systemctl restart rk00pi.service
fi
