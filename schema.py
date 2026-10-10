"""Versioned SQLite migrations. Existing history is assigned to server id 1."""
from datetime import datetime, timezone

SCHEMA_VERSION = 4


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def columns(db, table):
    return {row[1] for row in db.execute(f'PRAGMA table_info({table})')}


def add_column(db, table, name, decl):
    if table in {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")} and name not in columns(db, table):
        db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {decl}')


def migrate(db, host='unknown', port=25565, query_port=25565):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS sightings(id INTEGER PRIMARY KEY,ts TEXT,name TEXT,uuid TEXT,source TEXT,confirmed INTEGER);
        CREATE TABLE IF NOT EXISTS notices(id INTEGER PRIMARY KEY,ts TEXT,kind TEXT,title TEXT,message TEXT,delivery TEXT);
        CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY,start TEXT,last_seen TEXT,end TEXT,reason TEXT);
        CREATE TABLE IF NOT EXISTS chat(id INTEGER PRIMARY KEY,received TEXT,source TEXT,player TEXT,message TEXT,raw TEXT,external_id TEXT UNIQUE);
        PRAGMA journal_mode=WAL;
        PRAGMA busy_timeout=8000;
        CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY, applied TEXT);
        CREATE TABLE IF NOT EXISTS servers(
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            display_name TEXT,
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            query_port INTEGER,
            resolve_srv INTEGER DEFAULT 1,
            created TEXT
        );
        CREATE TABLE IF NOT EXISTS artifacts(
            sha256 TEXT PRIMARY KEY,
            kind TEXT,
            nbytes INTEGER,
            data TEXT,
            first_seen TEXT
        );
        CREATE TABLE IF NOT EXISTS delivery_queue(
            id INTEGER PRIMARY KEY,
            created TEXT,
            expire TEXT,
            attempts INTEGER DEFAULT 0,
            next_attempt TEXT,
            status TEXT,
            kind TEXT,
            title TEXT,
            message TEXT,
            player TEXT,
            reason TEXT,
            notice_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS setup_state(
            k TEXT PRIMARY KEY,
            v TEXT
        );
    ''')
    current = db.execute('SELECT MAX(version) FROM schema_version').fetchone()[0] or 0
    if db.execute('SELECT COUNT(*) FROM servers').fetchone()[0] == 0:
        db.execute(
            'INSERT INTO servers(id,slug,display_name,host,port,query_port,resolve_srv,created) VALUES(1,?,?,?,?,?,1,?)',
            ('default', host, host, port, query_port, utcnow()),
        )
    for table in ('checks', 'events', 'sessions', 'sightings', 'incidents', 'chat'):
        if table in {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            add_column(db, table, 'server_id', 'INTEGER NOT NULL DEFAULT 1')
    if 'players' in {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
        cols = columns(db, 'players')
        if 'server_id' not in cols:
            db.execute('''CREATE TABLE players_v3(
                server_id INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL,
                first_seen TEXT,
                last_seen TEXT,
                observations INTEGER DEFAULT 0,
                confirmed_observations INTEGER DEFAULT 0,
                PRIMARY KEY(server_id, name)
            )''')
            db.execute('INSERT OR IGNORE INTO players_v3(server_id,name,first_seen,last_seen,observations) SELECT 1,name,first_seen,last_seen,observations FROM players')
            db.execute('DROP TABLE players')
            db.execute('ALTER TABLE players_v3 RENAME TO players')
        add_column(db, 'players', 'confirmed_observations', 'INTEGER DEFAULT 0')
    add_column(db, 'notices', 'reason', 'TEXT')
    add_column(db, 'notices', 'server_id', 'INTEGER NOT NULL DEFAULT 1')
    db.execute('UPDATE notices SET server_id=1 WHERE server_id IS NULL')
    add_column(db, 'chat', 'original_ts', 'TEXT')
    add_column(db, 'chat', 'tz_confidence', 'TEXT')
    add_column(db, 'chat', 'unsupported', 'INTEGER DEFAULT 0')
    add_column(db, 'sessions', 'confidence', 'TEXT')
    add_column(db, 'sessions', 'last_seen', 'TEXT')
    add_column(db, 'delivery_queue', 'test', 'INTEGER DEFAULT 0')
    add_column(db, 'delivery_queue', 'server_id', 'INTEGER NOT NULL DEFAULT 1')
    db.execute('CREATE INDEX IF NOT EXISTS sessions_server_player ON sessions(server_id,player,end)')
    db.execute('CREATE INDEX IF NOT EXISTS checks_server_ts ON checks(server_id, ts)')
    db.execute('CREATE INDEX IF NOT EXISTS events_server_ts ON events(server_id, ts)')
    db.execute('CREATE INDEX IF NOT EXISTS sightings_server_name ON sightings(server_id, name)')
    db.execute('CREATE INDEX IF NOT EXISTS notices_ts ON notices(ts)')
    db.execute('CREATE INDEX IF NOT EXISTS delivery_status ON delivery_queue(status, next_attempt)')
    if current < SCHEMA_VERSION:
        db.execute('INSERT INTO schema_version(version, applied) VALUES(?,?)', (SCHEMA_VERSION, utcnow()))
    return SCHEMA_VERSION
