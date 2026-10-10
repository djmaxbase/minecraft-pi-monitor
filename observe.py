"""Player-list confidence: complete, partial, stale, unavailable, conflicting.

A name in a status sample is not automatically a confirmed join. A name missing
from an incomplete sample is never a confirmed leave.
"""
from datetime import datetime


PLACEHOLDER_NAMES = {'Anonymous Player'}


def parse_ts(value):
    if not value:
        return None
    return datetime.fromisoformat(value)


def unique_names(names):
    seen = set()
    out = []
    for name in names or []:
        if not isinstance(name, str):
            continue
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def gap_seconds(previous, current):
    if not previous:
        return None
    a, b = parse_ts(previous.get('timestamp')), parse_ts(current.get('timestamp'))
    if not a or not b:
        return None
    return (b - a).total_seconds()


def classify(record):
    """Attach observation fields. Mutates and returns the record."""
    names = unique_names(record.get('names'))
    record['names'] = names
    if not record.get('reachable'):
        record['observation'] = 'unavailable'
        record['names_complete'] = False
        record['list_confidence'] = 'none'
        return record
    count = record.get('online')
    query = record.get('query') or {}
    query_names = unique_names(query.get('names'))
    meta = query.get('metadata') or {}
    query_count = meta.get('numplayers')
    query_ok = bool(record.get('query_available'))

    if query_ok:
        consistent = (
            type(count) is int and count >= 0
            and query_count is not None
            and count is not None
            and str(count) == str(query_count)
            and len(query_names) == count
        )
        if consistent:
            record['names'] = query_names
            record['observation'] = 'complete'
            record['names_complete'] = True
            record['list_confidence'] = 'query'
            record['name_source'] = 'Query'
            return record
        record['observation'] = 'conflicting'
        record['names_complete'] = False
        record['list_confidence'] = 'conflict'
        record['names'] = query_names or names
        record['name_source'] = 'Query (inconsistent met status)'
        record['query_conflict'] = {
            'status_online': count,
            'query_numplayers': query_count,
            'query_name_count': len(query_names),
        }
        return record

    if type(count) is not int or count < 0 or len(names) > count or (count == 0 and names):
        record.update(observation='conflicting', names_complete=False, list_confidence='conflict')
        return record

    if count == 0:
        record['names'] = []
        record['observation'] = 'complete'
        record['names_complete'] = True
        record['list_confidence'] = 'empty'
        record['name_source'] = 'Status: lege server'
        return record

    if names:
        record['observation'] = 'partial'
        record['names_complete'] = False
        record['list_confidence'] = 'sample'
        record['name_source'] = 'Statussample (onvolledig)'
        return record

    record['observation'] = 'partial'
    record['names_complete'] = False
    record['list_confidence'] = 'sample'
    record['name_source'] = 'Statussample zonder namen'
    return record


def mark_stale(record, previous, interval):
    gap = gap_seconds(previous, record)
    limit = max(90, float(interval or 30) * 2.5)
    record['measurement_gap_seconds'] = gap
    if gap is not None and gap > limit:
        if record.get('observation') not in ('unavailable', 'conflicting'):
            record['observation'] = 'stale' if not record.get('names_complete') else record['observation']
        record['stale_gap'] = True
    else:
        record['stale_gap'] = False
    return record


def _sets(record):
    if not record:
        return set()
    return set(record.get('names') or [])


def player_events(previous, current):
    """Return (kind, player, detail, confidence) tuples. Never leave from a partial list."""
    events = []
    curr_complete = bool(current.get('names_complete') and current.get('reachable') and current.get('list_confidence') in ('query', 'empty'))
    prev_complete = bool(previous and previous.get('names_complete') and previous.get('reachable') and previous.get('list_confidence') in ('query', 'empty'))
    gap = current.get('stale_gap') or (not previous)
    old, new = _sets(previous), _sets(current)

    if current.get('observation') == 'unavailable':
        return events

    if curr_complete and prev_complete and not current.get('stale_gap'):
        for name in sorted(new - old):
            events.append(('join_observed', name, 'Bevestigd tussen twee volledige lijsten', 'confirmed'))
        for name in sorted(old - new):
            events.append(('leave_observed', name, 'Bevestigd tussen twee volledige lijsten', 'confirmed'))
        return events

    if curr_complete and (not prev_complete or current.get('stale_gap') or not previous):
        for name in sorted(new):
            events.append(('online_observed', name, 'Aanwezig bij start van een volledige lijst of na een meetgat', 'confirmed'))
        return events

    # Partial/conflicting/stale: sample appearance only. Missing names are not leaves.
    prev_names = old if previous and previous.get('reachable') else set()
    if current.get('observation') in ('partial', 'conflicting', 'stale') or current.get('list_confidence') == 'sample':
        for name in sorted(new - prev_names):
            events.append(('sample_appeared', name, 'Naam verscheen in een onvolledige of ongeverifieerde sample', 'sample'))
    return events


def should_close_sessions(previous, current):
    """Close open confirmed sessions at last_seen when continuity is lost."""
    if not current.get('reachable'):
        return 'unreachable'
    if current.get('stale_gap'):
        return 'observation_gap'
    if previous and previous.get('names_complete') and not current.get('names_complete'):
        return 'observation_gap'  # End at last complete observation, never a leave.
    if not current.get('names_complete'):
        return None
    if previous and previous.get('names_complete') and not current.get('stale_gap'):
        return None  # continuous complete lists; leaves handled separately
    if not previous or not previous.get('names_complete') or current.get('stale_gap'):
        return 'observation_gap'
    return None
