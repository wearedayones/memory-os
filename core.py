import json
import os
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(os.environ.get('HERMES_MEMORY_DIR', '/home/ubuntu/hermes-memory'))


def _ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default):
    if not path.exists() or path.stat().st_size == 0:
        data = default() if callable(default) else default
        _ensure_dir(path.parent)
        path.write_text(json.dumps(data, indent=2))
        return data
    try:
        return json.loads(path.read_text())
    except Exception:
        data = default() if callable(default) else default
        path.write_text(json.dumps(data, indent=2))
        return data


def _write_json(path: Path, data):
    _ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2))


def _ts():
    return datetime.now(timezone.utc).isoformat()


class MemoryOS:
    def __init__(self, base_dir=BASE_DIR):
        self.base_dir = Path(base_dir)
        self.user_dir = self.base_dir / 'users'
        self.system_dir = self.base_dir / 'system'
        self.index_dir = self.base_dir / 'index'
        self.logs_dir = self.base_dir / 'logs'
        for d in [self.user_dir, self.system_dir, self.index_dir, self.logs_dir]:
            _ensure_dir(d)

    def _user_paths(self, user_id):
        u = self.user_dir / user_id
        _ensure_dir(u)
        return {
            'facts': u / 'facts.json',
            'sessions': u / 'sessions.json',
        }

    def _append_entry(self, entry, path):
        data = _load_json(path, lambda: {'entries': []})
        data.setdefault('entries', []).append(entry)
        _write_json(path, data)

    def _log_event(self, event):
        _ensure_dir(self.logs_dir)
        data = _load_json(self.logs_dir / 'raw.json', lambda: {'events': []})
        data.setdefault('events', []).append(event)
        _write_json(self.logs_dir / 'raw.json', data)

    def _update_indexes(self, user_id, entry):
        kw_path = self.index_dir / 'keywords.json'
        tag_path = self.index_dir / 'tags.json'
        keywords = _load_json(kw_path, lambda: {'keywords': {}}).setdefault('keywords', {})
        tags = _load_json(tag_path, lambda: {'tags': {}}).setdefault('tags', {})
        text = entry.get('text', '')
        for w in [w.lower() for w in text.split() if len(w) > 2]:
            keywords.setdefault(w, {'count': 0, 'user_ids': []})
            keywords[w]['count'] += 1
            if user_id not in keywords[w]['user_ids']:
                keywords[w]['user_ids'].append(user_id)
        for t in entry.get('tags', []):
            t = t.lower()
            tags.setdefault(t, {'count': 0, 'users': []})
            tags[t]['count'] += 1
            if user_id not in tags[t]['users']:
                tags[t]['users'].append(user_id)
        _write_json(kw_path, {'keywords': keywords})
        _write_json(tag_path, {'tags': tags})

    def _entry(self, user_id, text, entry_type, importance=0.5, tags=None):
        if entry_type not in {'fact', 'preference', 'session', 'summary'}:
            raise ValueError(f'Invalid memory type: {entry_type}')
        ts = _ts()
        return {
            'id': hashlib.sha1(f'{user_id}:{ts}:{text}'.encode()).hexdigest()[:16],
            'user_id': user_id,
            'type': entry_type,
            'text': text,
            'importance': float(max(0.0, min(1.0, importance))),
            'tags': list(tags or []),
            'timestamp': ts,
            'created_at': ts,
            'updated_at': ts,
        }

    def remember(self, user_id, text, entry_type='fact', importance=0.5, tags=None):
        entry = self._entry(user_id, text, entry_type, importance, tags)
        ts = entry['timestamp']
        paths = self._user_paths(user_id)
        if entry_type == 'session':
            self._append_entry(entry, paths['sessions'])
        else:
            self._append_entry(entry, paths['facts'])
        self._update_indexes(user_id, entry)
        self._log_event({'user_id': user_id, 'type': 'remember', 'entry_id': entry['id'], 'timestamp': ts})
        return entry

    def recall(self, user_id, query, top_k=5):
        q_words = [w.lower() for w in query.split() if len(w) > 2]
        scored = []
        for p in [self._user_paths(user_id)['facts'], self._user_paths(user_id)['sessions']]:
            if not p.exists():
                continue
            try:
                data = json.loads(p.read_text())
            except Exception:
                continue
            for e in data.get('entries', []):
                score = 0.0
                text = e.get('text', '').lower()
                tags = [t.lower() for t in e.get('tags', [])]
                for w in q_words:
                    score += 2.0 if w in text else 0.0
                    score += 3.0 if any(w in t for t in tags) else 0.0
                try:
                    age_hours = max(
                        (datetime.now(timezone.utc) - datetime.fromisoformat(e.get('timestamp'))).total_seconds() / 3600.0,
                        0.0,
                    )
                except Exception:
                    age_hours = 1e9
                recency = 1.0 / (1.0 + age_hours / 24.0)
                score += float(e.get('importance', 0.0)) * 2.0
                score += recency * 1.5
                if score > 0:
                    scored.append((score, e))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]

    def summarize(self, user_id):
        p = self._user_paths(user_id)['sessions']
        try:
            data = json.loads(p.read_text())
        except Exception:
            return None
        sessions = data.get('sessions', []) if isinstance(data, dict) else []
        if not sessions:
            return None
        summary_text = '; '.join(filter(None, [s.get('summary', s.get('title', '')) for s in sessions]))
        summary = {
            'id': hashlib.sha1(f'{user_id}:{_ts()}'.encode()).hexdigest()[:16],
            'user_id': user_id,
            'type': 'summary',
            'summary': summary_text[:500] if summary_text else '',
            'keywords': [],
            'tags': ['auto-summary'],
            'status': 'archived',
            'created_at': _ts(),
            'expires_at': None,
        }
        path = self.system_dir / 'summaries.json'
        data = _load_json(path, lambda: {'summaries': []})
        data.setdefault('summaries', []).append(summary)
        _write_json(path, data)
        data['sessions'] = []
        _write_json(p, data)
        self._log_event({'user_id': user_id, 'type': 'summarize', 'summary_id': summary['id'], 'timestamp': summary['created_at']})
        return summary

    def cleanup(self, user_id):
        removed = 0
        for p in [self._user_paths(user_id)['facts'], self._user_paths(user_id)['sessions']]:
            if not p.exists():
                continue
            data = _load_json(p, lambda: {'entries': []})
            entries = data.get('entries', []) if isinstance(data, dict) else []
            kept = [e for e in entries if float(e.get('importance', 0.0)) >= 0.4]
            removed += len(entries) - len(kept)
            data['entries'] = kept
            _write_json(p, data)
        self._log_event({'user_id': user_id, 'type': 'cleanup', 'removed': removed, 'timestamp': _ts()})
        return removed

    def commit_memory(self, message=None):
        if message is None:
            message = 'memory update'
        def run(args):
            return subprocess.run(args, cwd=self.base_dir, capture_output=True, text=True)
        run(['git', 'add', '-A'])
        proc = run(['git', 'commit', '-m', message])
        out = run(['git', 'log', '-1', '--pretty=%H %s'])
        if proc.returncode != 0:
            return {'committed': False, 'message': proc.stderr.strip() or out.stdout.strip()}
        return {'committed': True, 'message': out.stdout.strip()}


if __name__ == '__main__':
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    mem = MemoryOS(tmp)
    mem.remember('u1', 'likes dark mode', 'preference', 0.9, ['ui', 'prefs'])
    mem.remember('u1', 'uses iPhone', 'fact', 0.7, ['device'])
    mem.remember('u2', 'python dev', 'fact', 0.6, ['work'])
    mem.summarize('u1')
    removed = mem.cleanup('u1')
    recall = mem.recall('u1', 'pref')
    commit = mem.commit_memory('test commit')
    print(json.dumps({
        'recall': [(round(s, 3), e['text']) for s, e in recall],
        'summarize': 'ok',
        'cleanup': removed,
        'commit': commit,
    }, indent=2))
    print('CORE_OK')
