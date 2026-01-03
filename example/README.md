# Example Django RSGI Application

This is a minimal Django application configured to run with `django-rsgi` and `Granian`.

## Running the application

```bash
uv run granian --interface rsgi --loop uvloop --no-ws --reload --host 0.0.0.0 --port 8000 config.rsgi:application
```

Once running, you can visit:

- http://localhost:8000/
- http://localhost:8000/hello/RSGI/
