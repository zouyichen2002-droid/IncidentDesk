FROM elasticsearch:8.19.10

USER root

RUN curl -fsSL --retry 3 https://get.infini.cloud/elasticsearch/analysis-ik/8.19.10 \
      -o /tmp/elasticsearch-analysis-ik-8.19.10.zip \
    && echo 'dc968f7caefdc2457c9181b4df5c88b2a9ba0c3ba652e97448d100690629b371  /tmp/elasticsearch-analysis-ik-8.19.10.zip' | sha256sum -c - \
    && /usr/share/elasticsearch/bin/elasticsearch-plugin install --batch \
      file:///tmp/elasticsearch-analysis-ik-8.19.10.zip \
    && rm /tmp/elasticsearch-analysis-ik-8.19.10.zip

RUN chown -R elasticsearch:elasticsearch /usr/share/elasticsearch/plugins

USER elasticsearch
