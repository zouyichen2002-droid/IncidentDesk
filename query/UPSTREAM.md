Source: https://github.com/didilili/shopkeeper-agent
Commit: 8045fa4d61608f58df551fda6cd1a70529bb5b67
MIT copyright didilili. Original LICENSE and README retained.

Merged into IncidentDesk as an internal read-only query worker.
See ../docs/MERGED_V1.md for changes, deployment and tests.

2026-09-25: Conversational routing, general answers and bounded follow-up context added by IncidentDesk. See ../docs/CONVERSATION_V1.md.

2026-09-25: Reviewed JoyDataAgent TableRAG and NL2SQL architecture at commit
2417e0b8b636d941ad5fb14c59b20dddfef5375d (data_agent branch). No JD source files
were copied into this module. Independently implemented bounded/batched recall,
reciprocal-rank fusion and Go-to-Python query trace correlation. See
../docs/ATGUIGU_CAPABILITIES.md for the source-by-source capability audit and gaps.
