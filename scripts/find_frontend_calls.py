import os
import re

calls = set()
pattern = re.compile(r'fetch\([`\'"](/api/v1/[^`\'"?$]+)')
sse_pattern = re.compile(r'EventSource\([`\'"](/api/v1/[^`\'"?$]+)')

for root, dirs, files in os.walk('frontend/src'):
    for f in files:
        if f.endswith(('.ts', '.tsx')):
            p = os.path.join(root, f).replace('\\', '/')
            with open(p, encoding='utf-8') as fh:
                text = fh.read()
                for m in pattern.findall(text):
                    calls.add((m, p))
                for m in sse_pattern.findall(text):
                    calls.add((m + " (SSE)", p))

print("Total unique API endpoints called in frontend:", len(calls))
for endpoint, filepath in sorted(calls):
    print(f"{endpoint:<45} called in {filepath}")
