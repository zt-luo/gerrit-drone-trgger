#! /bin/bash

docker build ./ -t zt-luo/gerrit-drone-trgger
docker run zt-luo/gerrit-drone-trgger
