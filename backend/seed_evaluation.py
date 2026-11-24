"""Seed a reproducible, labelled local example without LLM calls."""

import requests

r=requests.post('http://localhost:8000/api/evaluation/seed',json={})
r.raise_for_status()
print(r.json())
