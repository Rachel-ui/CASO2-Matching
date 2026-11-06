content = open('src/ejecutar_matching.py', 'r', encoding='utf-8').read()
# Add uuid import
content = content.replace(
    'import csv\nimport json\nimport time\nfrom pathlib import Path',
    'import csv\nimport json\nimport time\nimport uuid\nfrom pathlib import Path'
)
# Fix the opciones line
content = content.replace(
    'opciones = {"max_concurrency": 1}',
    'opciones = {"max_concurrency": 1, "configurable": {"thread_id": f"run-{uuid.uuid4().hex[:8]}"}}'
)
open('src/ejecutar_matching.py', 'w', encoding='utf-8').write(content)
print('Done')