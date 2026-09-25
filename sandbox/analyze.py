"""Only this fixed analysis program is runnable. Input is a read-only JSON snapshot."""
import collections,json
from pathlib import Path
rows=json.loads(Path('/input/records.json').read_text())
if not isinstance(rows,list) or len(rows)>1000:raise ValueError('input_limit')
result={'count':len(rows),'levels':dict(collections.Counter(r.get('level','UNKNOWN') for r in rows))}
Path('/output/report.json').write_text(json.dumps(result))
print(json.dumps(result))
