#!/bin/bash -e

on_chroot << EOF
	chown -R ${FIRST_USER_NAME} /home/${FIRST_USER_NAME}
	chgrp -R ${FIRST_USER_NAME} /home/${FIRST_USER_NAME}

	chown -R ${FIRST_USER_NAME}:audio /usr/local/puredata-patches
	chmod -R u+rwX,g+rwX,o+rX /usr/local/puredata-patches

	apt-get update
	apt-get upgrade -y
	apt-get autoremove -y
EOF
