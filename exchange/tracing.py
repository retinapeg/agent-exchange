"""Small application trace context propagated across configured HTTP peers."""
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

current = ContextVar('exchange_trace', default={})


@contextmanager
def trace_scope(trace_id=None, span_id=None, parent_id=None):
    previous = current.get()
    value = {'trace_id': trace_id or previous.get('trace_id') or str(uuid4()),
             'span_id': span_id or str(uuid4()),
             'parent_id': parent_id if parent_id is not None else previous.get('span_id')}
    token = current.set(value)
    try:
        yield value
    finally:
        current.reset(token)


def headers():
    value = current.get()
    return {k: v for k, v in {'X-Trace-Id': value.get('trace_id'),
                              'X-Parent-Span': value.get('span_id')}.items() if v}
