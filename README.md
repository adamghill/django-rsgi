# django-rsgi

Native RSGI support for Django on Granian.

> NOTE: This is mostly a proof of concept.

## Installation

```bash
pip install django-rsgi
```

## Usage

```python
# rsgi.py
import os
from django_rsgi import get_rsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_rsgi_application()
```
