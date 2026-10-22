# BLACKSITE Web Radar / Raspberry Pi Monitor

Adds an optional feed to the existing Python stdlib web server. Existing dashboard, chat and notifications remain separate.

1. On Raspberry Pi, generate a secret: `python3 -c "import secrets;print(secrets.token_urlsafe(32))"`.
2. Put `BLACKSITE_RADAR_TOKEN=<generated secret>` in the runtime environment (e.g. systemd EnvironmentFile). Restart the monitor.
3. Open `/radar` on the existing website (same existing Basic authentication).
4. On the CC:Tweaked **base** install `blacksite_web.lua`. Enter a publicly reachable HTTPS URL ending in `/api/radar/ingest`, and the same token.
5. Run the script alongside radar and mobile server: `parallel.waitForAll(function() shell.run("radar.lua") end, function() shell.run("mobile_server.lua") end, function() shell.run("blacksite_web.lua") end)` (or adapt your startup script).
6. Check `/api/radar/live` in your browser after the first successful publish.

Minecraft requires HTTP enabled and the website hostname allowed. The Pi must have externally reachable HTTPS; don't expose port 8080 directly to the internet. The API requires an independent high-entropy token and the site retains existing login. Treat live coordinates as private information.

API:
- `POST /api/radar/ingest`: Bearer token, JSON `{"tracks":[{"id":"...","category":"PLAYER","entityType":"entity.minecraft.player","position":{"x":1,"y":2,"z":3}}]}`
- `GET /api/radar/live`: latest normalized snapshot with `stale` true after 20 seconds.

Radar map defaults to world X/Z centered at 0/0. Improve by setting base coordinates in the frontend or including a configured origin in a future revision; current marker separation remains correct but distant coordinates may be offscreen.
