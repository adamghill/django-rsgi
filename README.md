# django-rsgi

Native [RSGI](https://github.com/emmett-framework/granian/blob/master/docs/spec/RSGI.md) support for Django for [granian](https://github.com/emmett-framework/granian).

> NOTE: This is mostly a proof of concept.

## Installation

```bash
uv add django-rsgi
```

## Usage

1. `uv add django-rsgi granian[reload,uvloop]`
2. Create `config/rsgi.py`

```python
# config/rsgi.py
import os
from django_rsgi import get_rsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_rsgi_application()
```

3. `uv run granian --interface rsgi --loop uvloop --workers 4 --no-ws --reload --host 0.0.0.0 --port 8000 config.rsgi:application`
4. Go to `http://localhost:8000`

## Test

```bash
uv run pytest
```
