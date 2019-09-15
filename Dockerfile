FROM debian:buster
LABEL MAINTAINER h4r0

ENV APP RecuperaBit

ARG DEBIAN_FRONTEND=noninteractive

RUN \
 # setting up packages
 apt-get update && \
 
 apt-get install -y \
  pypy \
  git \
  locales && \

 # setup unicode locale
 echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen && \
 locale-gen && \

 # cleanup
 apt-get clean && \
 rm -rf \
  /tmp/* \
  /var/lib/apt/lists/*

RUN \
 # installing recuperabit
 git clone https://github.com/Lazza/RecuperaBit.git recuperabit

RUN \
 # create placeholder files
 mkdir /output && \
 touch /drive.img

ENV PYTHONIOENCODING utf-8
ENV LANG='en_US.UTF-8'
ENV LC_ALL='en_US.UTF-8'

ENTRYPOINT ["/usr/bin/pypy", "/recuperabit/main.py"]
CMD ["-s", "/save.file", "-o", "/output", "/drive.img"]
