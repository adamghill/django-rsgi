# django-rsgi

Native [RSGI](https://github.com/emmett-framework/granian/blob/master/docs/spec/RSGI.md) support for Django for [granian](https://github.com/emmett-framework/granian).

> NOTE: This is mostly a proof of concept.

## Installation

```bash
uv add django-rsgi
```

## Usage

```python
# rsgi.py
import os
from django_rsgi import get_rsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_rsgi_application()
```

## Test

```bash
uv run pytest
```
