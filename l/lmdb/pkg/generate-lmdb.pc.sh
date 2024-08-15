#!/usr/bin/env bash
#
# Generates correct lmdb.pc dynamically on each build
#
cat<<EOF > /tmp/lmdb.pc
prefix=/usr
libdir=\${prefix}/lib
includedir=\${prefix}/include

Name: liblmdb
Description: Lightning Memory-Mapped Database
URL: https://symas.com/products/lightning-memory-mapped-database/
Version: @PKGVER@
Libs: -L\${libdir} -llmdb
Cflags: -I\${includedir}
EOF
