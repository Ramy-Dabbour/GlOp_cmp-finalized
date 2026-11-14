"""One-shot read-only transfer metrics for the November 3 continuation."""
import datetime as dt
import json
import os
from pathlib import Path
import ssl
import subprocess
import urllib.parse
import urllib.request

cli = Path(os.environ['LOCALAPPDATA']) / 'Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd'
auth = subprocess.run([str(cli), 'auth', 'print-access-token', '--quiet'],
                      capture_output=True, text=True, check=True, timeout=90,
                      creationflags=subprocess.CREATE_NO_WINDOW)
context = ssl.create_default_context(cafile=str(cli.parent.parent / 'lib/third_party/certifi/cacert.pem'))
params = {
    'filter': 'metric.type="storage.googleapis.com/api/request_count" AND resource.labels.bucket_name="strange-reducer-509621-e8-matlab-glop-cmp" AND metric.labels.method="ReadObject"',
    'interval.endTime': dt.datetime.now(dt.timezone.utc).isoformat(),
    'interval.startTime': '2026-11-03T11:19:00Z',
    'aggregation.alignmentPeriod': '60s',
    'aggregation.perSeriesAligner': 'ALIGN_SUM',
    'aggregation.crossSeriesReducer': 'REDUCE_SUM',
    'pageSize': 100,
}
url = 'https://monitoring.googleapis.com/v3/projects/strange-reducer-509621-e8/timeSeries?' + urllib.parse.urlencode(params)
request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + auth.stdout.strip()})
with urllib.request.urlopen(request, context=context, timeout=40) as response:
    data = json.load(response)
points = [p for s in data.get('timeSeries', []) for p in s.get('points', [])]
result = {
    'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(),
    'reported_bucket_reads_since_1119_utc': sum(int(p['value'].get('int64Value', 0)) for p in points),
    'latest_minute': points[0] if points else None,
    'note': 'Lagging bucket-wide activity includes source/status reads; not a verified restored-trial count.',
}
Path(__file__).with_name('continuation-restore-activity-20261103.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
