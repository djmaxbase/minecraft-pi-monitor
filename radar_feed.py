"""BLACKSITE radar snapshots, kept separate from Minecraft status monitoring."""
import json
import os
import hmac
import time
import threading
from pathlib import Path

class RadarFeed:
    def __init__(self, directory):
        self.path = Path(directory) / "blacksite-radar.json"
        self.lock = threading.Lock()
        self.snapshot = {"tracks": [], "received_at": None}
        try:
            data = json.loads(self.path.read_text())
            if isinstance(data, dict): self.snapshot = data
        except (OSError, ValueError): pass

    def accept(self, supplied_key, payload):
        configured = os.environ.get("BLACKSITE_RADAR_TOKEN", "")
        if not configured or len(configured) < 24:
            return False, "Radar-token ontbreekt (minimaal 24 tekens)"
        if not hmac.compare_digest(supplied_key, configured):
            return False, "Ongeldige radar-token"
        if not isinstance(payload, dict): return False, "JSON-object vereist"
        tracks = payload.get("tracks")
        if not isinstance(tracks, list) or len(tracks) > 250:
            return False, "Maximaal 250 tracks"
        cleaned = []
        for track in tracks:
            if not isinstance(track, dict): continue
            pos = track.get("position")
            if not isinstance(pos, dict): continue
            try:
                xyz = {axis: float(pos[axis]) for axis in ("x", "y", "z")}
                if any(not -30000000 <= v <= 30000000 for v in xyz.values()): continue
            except (KeyError, ValueError, TypeError): continue
            cleaned.append({
                "id": str(track.get("id", ""))[:100],
                "name": str(track.get("name", ""))[:80],
                "category": str(track.get("category", "OTHER"))[:32],
                "entityType": str(track.get("entityType", ""))[:100],
                "position": xyz,
            })
        record = {"tracks": cleaned, "received_at": int(time.time()), "source": "BLACKSITE CC:Tweaked"}
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(record))
            os.replace(tmp, self.path)
            self.snapshot = record
        return True, record

    def current(self):
        with self.lock: result = dict(self.snapshot)
        result["stale"] = not result.get("received_at") or time.time() - result["received_at"] > 20
        return result
