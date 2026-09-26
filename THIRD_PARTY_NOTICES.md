# Third-party notices

IncidentDesk's original code is licensed under the root MIT license. This license does not replace licenses covering third-party code, dependencies, services, or datasets.

## Query component

- Source: https://github.com/didilili/shopkeeper-agent
- Upstream commit: `8045fa4d61608f58df551fda6cd1a70529bb5b67`
- Copyright (c) 2026 didilili; MIT.
- Adapted code and sample data live under `query/`. The original copyright and license are retained in `query/LICENSE`. Component provenance is recorded in `query/UPSTREAM.md`.
- Compatibility patches under `integrations/shopkeeper/` retain the same upstream license.

## Runtime dependencies and plugin

Go, Python, and JavaScript dependencies are declared in `backend/go.mod`, the Python `pyproject.toml` / `uv.lock` files, and `web/package.json` / `package-lock.json`. They retain their respective licenses. Container images in the Compose and Helm files also retain their upstream terms; the project's MIT license does not relicense Elasticsearch or other runtime services.

The Elasticsearch IK plugin is downloaded from INFINI Labs during image build, with version 8.19.10 and a pinned SHA-256. Its binary is not vendored here. Source and license: https://github.com/infinilabs/analysis-ik (Apache-2.0 as stated upstream).

## Benchmark datasets and evidence

BGL and HDFS benchmark data originate from Loghub. Full downloaded corpora are not included. Acquisition and dataset scope are documented in `docs/PUBLIC_LOG_BENCHMARK.md`; users must follow the original dataset's usage terms. Evidence files contain local teaching/synthetic runs and limited public-log excerpts, with workstation home paths replaced by `/workspace`. These records preserve both failed and passing runs, not a claim of production deployment.
