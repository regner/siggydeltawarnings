

FROM python:3.5.2-alpine
MAINTAINER Regner Blok-Andersen <shadowdf@gmail.com>

ADD . /app/

WORKDIR /app/

RUN apk update \
 && apk add ca-certificates wget \
 && update-ca-certificates \
 && wget -qO- https://www.fuzzwork.co.uk/dump/latest/mapSolarSystems.csv.bz2 | bunzip2 > mapSolarSystems.csv \
 && wget -qO- https://www.fuzzwork.co.uk/dump/latest/mapSolarSystemJumps.csv.bz2 | bunzip2 > mapSolarSystemJumps.csv \
 && wget -qO- https://www.fuzzwork.co.uk/dump/latest/mapRegions.csv.bz2 | bunzip2 > mapRegions.csv \
 && pip install -qU pip \
 && pip install -r requirements.txt

CMD python main.py