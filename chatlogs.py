"""Import only recognizable Minecraft chat lines, supplied by an authorized log source."""
import hashlib
import re
import time

CHAT=re.compile(r'(?:\[CHAT\]\s*)?<([^<>]{1,64})>\s*(.+)$')


def parse_chat(line):
    line=re.sub(r'§.', '',line.strip())
    match=CHAT.search(line)
    if match:return match.group(1),match.group(2)
    if '[CHAT]' in line:
        text=line.split('[CHAT]',1)[1].strip()
        if text:return '',text
    return None


class ChatLog:
    def __init__(self,store,notifier,prefs):
        self.store=store;self.notifier=notifier;self.prefs=prefs
        with store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS chat(id INTEGER PRIMARY KEY,received TEXT,source TEXT,player TEXT,message TEXT,raw TEXT,external_id TEXT UNIQUE);
            CREATE INDEX IF NOT EXISTS chat_received ON chat(received);
            CREATE INDEX IF NOT EXISTS chat_player ON chat(player);''')

    def ingest(self,lines,source,stamp):
        if not self.prefs.get()['chat_enabled']:raise ValueError('Chatlog staat uit in instellingen')
        if not isinstance(source,str) or not 1<=len(source)<=100:raise ValueError('Ongeldige bron')
        if not isinstance(lines,list) or len(lines)>2000:raise ValueError('Maximaal 2000 regels per aanvraag')
        count=0
        for item in lines:
            if not isinstance(item,dict) or not isinstance(item.get('line'),str) or len(item['line'])>8192:continue
            parsed=parse_chat(item['line'])
            if not parsed:continue
            player,message=parsed
            external=item.get('id')
            if not isinstance(external,str) or len(external)>200:raise ValueError('Iedere regel heeft een uniek id nodig')
            key=hashlib.sha256((str(self.store.server_id)+'\0'+source+'\0'+external).encode()).hexdigest()
            with self.store.connect() as db:
                cur=db.execute('INSERT OR IGNORE INTO chat(received,source,player,message,raw,external_id,server_id,original_ts,tz_confidence) VALUES(?,?,?,?,?,?,?,?,?)',(stamp,source,player,message,item['line'],key,self.store.server_id,item.get('timestamp'),item.get('tz_confidence','unknown')))
                inserted=bool(cur.rowcount)
            if inserted:
                count+=1;self.notifier.emit('chat','Minecraft-chat',f'{player}: {message}' if player else message,player or None)
        return count

    def search(self,query='',player='',before=None):
        query=query[:200];player=player[:100]
        conditions=['1=1'];args=[]
        if query:
            conditions.append("instr(lower(message),lower(?))>0");args.append(query)
        if player:conditions.append('player=?');args.append(player)
        if before:conditions.append('id<?');args.append(before)
        from app import ScopedRead
        with self.store.connect() as db:
            db=ScopedRead(db,self.store.server_id)
            rows=[dict(r) for r in db.execute('SELECT id,received,source,player,message,raw FROM chat WHERE '+' AND '.join(conditions)+' ORDER BY id DESC LIMIT 200',args)]
            count=db.execute('SELECT COUNT(*) FROM chat').fetchone()[0]
        return dict(rows=rows,total=count,next_before=rows[-1]['id'] if len(rows)==200 else None)
