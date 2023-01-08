FROM ubuntu:22.04

LABEL maintainer="ztluo <me@ztluo.dev>"
LABEL Description="gerrit-drone-trigger"
WORKDIR /work

ADD . /work

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y python3 python3-pip ssh && \
    apt-get clean

RUN pip3 install --no-cache-dir -r requirements.txt

# CMD [ "python3", "gerrit-drone-trigger.py" ]
