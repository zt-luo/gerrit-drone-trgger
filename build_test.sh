#! /bin/bash

docker build ./ -t zt-luo/gerrit-drone-trigger
docker run zt-luo/gerrit-drone-trigger
