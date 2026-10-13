"""The helpers of the tests that open the database directly (the tests were written for psycopg; this keeps their style).

connect(path) gives a connection with tuple rows (dict rows with row_factory=dict_row); the guard errors of the schema
(RAISE(ABORT) of the triggers, foreign keys) are sqlite3.IntegrityError, which `errors.*` stand for.
"""
import sqlite3

from app import db


def dict_row(cursor, row):
    return db._dict_row(cursor, row)


def tuple_row(cursor, row):
    return tuple(db._convert(d[0], v) for d, v in zip(cursor.description, row))


class errors:                                         # names of the PostgreSQL errors the tests expect, all are integrity errors here
    RaiseException = sqlite3.IntegrityError
    InsufficientPrivilege = sqlite3.IntegrityError
    ForeignKeyViolation = sqlite3.IntegrityError
    UniqueViolation = sqlite3.IntegrityError
    CheckViolation = sqlite3.IntegrityError


def connect(path, row_factory=None, autocommit=False, **_ignored):
    conn = db.connect(path)
    conn.row_factory = row_factory or tuple_row
    return conn
