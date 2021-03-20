FROM debian:buster-slim
MAINTAINER Thomas Krijnen <thomas@aecgeeks.org>

RUN mkdir -p /usr/share/man/man1
RUN apt-get update -y && apt-get install -y curl openjdk-11-jdk-headless python3 python3-distutils procps lsof supervisor graphviz unzip git
RUN apt-get update -y && apt-get install -y texlive texlive-pictures texlive-latex-extra imagemagick-6.q16
# remove policy to disable PDF conversion
RUN rm /etc/ImageMagick-6/policy.xml
RUN curl --silent --show-error --retry 5 https://bootstrap.pypa.io/get-pip.py | python3
RUN python3 -m pip install flask Beautifulsoup4 Markdown gunicorn pysolr pydot tabulate hilbertcurve==1.0.5

RUN curl --location --silent --show-error --retry 5 'https://archive.apache.org/dist/lucene/solr/8.6.3/solr-8.6.3.tgz' -o - | tar zxf -
RUN ls /
RUN chmod +x /solr-8.6.3/bin/*

RUN curl --silent --show-error --retry 5 -o /tmp/ifcopenshell_python.zip https://s3.amazonaws.com/ifcopenshell-builds/ifcopenshell-python-`python3 -c 'import sys;print("".join(map(str, sys.version_info[0:2])))'`-v0.6.0-c15fdc7-linux64.zip
RUN mkdir -p `python3 -c 'import site; print(site.getusersitepackages())'`
RUN unzip -d `python3 -c 'import site; print(site.getusersitepackages())'` /tmp/ifcopenshell_python.zip
RUN git clone https://github.com/opensourceBIM/python-mvdxml/ `python3 -c 'import site; print(site.getusersitepackages())'`/ifcopenshell/mvd

WORKDIR /

ADD wsgi.py main.py parse_xmi.py transform_to_xml.py parse_mvd.py /
ADD templates/* /templates/
ADD https://api.github.com/repos/buildingSMART/IFC4.3.x-development/git/refs/heads/master /tmp/data_version.json
RUN git clone https://github.com/buildingSMART/IFC4.3.x-development /data
RUN git clone https://github.com/buildingSMART/Sample-Test-Files /examples

RUN mkdir /svgs
RUN mkdir /xml
RUN python3 transform_to_xml.py /data/docs /xml
RUN python3 parse_xmi.py
RUN python3 parse_mvd.py
RUN /solr-8.6.3/bin/solr start -force && /solr-8.6.3/bin/solr create_core -force -c ifc && echo 1 && /solr-8.6.3/bin/post -c ifc /xml && echo 2 && /solr-8.6.3/bin/solr stop && echo 3

WORKDIR /data/scripts
RUN python3 process_schema.py ../schemas/IFC.xml

WORKDIR /

COPY supervisord.conf /etc/supervisord.conf

ENTRYPOINT supervisord -n
