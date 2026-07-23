"""Shared DB connection helper for the worker."""

import os

import psycopg
from dotenv import load_dotenv


def connect() -> psycopg.Connection:
    load_dotenv()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(dsn)
