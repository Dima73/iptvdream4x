ARG IMAGE_TAG=latest
FROM technic93/e2xvfb:${IMAGE_TAG}

RUN rev="acac722e25a5e2d69d60d4df6bcef701049e2b38" \
 && curl -fsSL https://github.com/littlesat/skin-PLiHD/archive/$rev.zip -o skin-PLiHD.zip \
 && unzip skin-PLiHD.zip && cd skin-PLiHD-$rev && cp -arv . /

RUN apt-get update && apt-get install -y \
  gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad gstreamer1.0-libav

RUN apt-get update && apt-get install -y bash-completion command-not-found psmisc htop vim wput

RUN mkdir /etc/iptvdream

RUN pip install ptvsd pytest pytest-cov typing
EXPOSE 5678

COPY mytest-ptvsd.py /opt/mytest-ptvsd.py
COPY mytest-ptvsd-py3.py /opt/mytest-ptvsd-py3.py
ARG IMAGE_TAG
RUN test "${IMAGE_TAG}" = "atv-py3" && mv /opt/mytest-ptvsd-py3.py /opt/mytest-ptvsd.py || true

COPY start.sh /opt/start.sh
ENV LC_CTYPE="C.UTF-8"
CMD ["/opt/start.sh"]
