"""Strict local control messages; no credentials or raw input content."""
import json

FIELDS = {'get_status': set(), 'pair': {'code'}, 'start_session': {'session_id'},
          'stop_session': set(), 'set_camera': {'on'}, 'watch_resumption': {'break_id'}}


def decode(raw):
    if not isinstance(raw, str):
        raise ValueError('Text messages only')
    msg = json.loads(raw)
    if not isinstance(msg, dict) or not isinstance(msg.get('type'), str):
        raise ValueError('Invalid message')
    kind = msg['type']
    if kind not in FIELDS or set(msg) != FIELDS[kind] | {'type'}:
        raise ValueError('Invalid fields')
    for field in FIELDS[kind]:
        value = msg[field]
        if field == 'on':
            if type(value) is not bool:
                raise ValueError('Expected boolean')
        elif not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise ValueError('Invalid identifier')
    return msg
