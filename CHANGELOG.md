# 2.2.4 — BLACKSITE Web Radar

Adds BLACKSITE Radar to the web dashboard. Requires v2.2.3 compatibility bridge installed first on the Raspberry Pi, and a configured BLACKSITE_RADAR_TOKEN and CC:Tweaked HTTP bridge.

# 2.2.3 — Compatibility bridge

This signed transitional update installs an updater compatible with future BLACKSITE radar files while keeping the existing v2.1.1 web server running. Install v2.2.3 first, then install the next radar release. No radar UI in this bridge version.

# 2.2.0 — BLACKSITE Web Radar

- Optional token-authenticated CC:Tweaked radar ingest and live web dashboard at /radar.
- Latest snapshots stored on Pi; existing monitoring and notifications preserved.
- Requires BLACKSITE_RADAR_TOKEN and Minecraft HTTP access to the Pi HTTPS endpoint.
- New radar files included in signed in-app updates.

# 2.1.1

- Supervisor schrijft update-uitkomst atomisch vóór het vrijgeven van de pending-status.
- Gezondheidsmarker moet overeenkomen met de geïnstalleerde versie.
- Bewaart maximaal 100 supervisor-update-uitkomsten lokaal.
- Lost de in GitHub CI gevonden race op; lokaal getest en CI geslaagd op Python 3.9 en 3.13.

# 2.1.0

- Herstelt verse installatie en beschermde setup-wizard; bestaande credentials blijven behouden.
- Statussamples worden nooit tot bevestigde joins/vertrekken gepromoveerd op basis van lengte.
- Sessiedelen stoppen bij verlies van volledige waarneming; meetgaten tellen niet als speeltijd.
- Persistente begrensde meldingenwachtrij met expiry, backoff en providerdiagnose.
- Server-id's en gescheiden actieve weergaven; ander adres via GUI maakt nieuw profiel.
- GitHub Releases met ondertekende assets, gecontroleerde redirects en correcte SemVer.
- Striktere ZIP-validatie, concurrentievergrendeling en expliciete pending-state; tweede update overschrijft geen onbevestigde eerste.
- Streaming exports, doorzoekbare historie, ingestie-scoping en relay-checkpoints/outbox.
- Nederlandse setup, server- en updatebediening, expliciete tijdzone en sample-alertoptie.
- Bestaande Pi-telemetrie behouden; dubbele filesystemmetingen verwijderd en reset-counters als onbekend gemarkeerd.

Nog geen gelijktijdige multi-servermonitoring, volledige chatdekking of exacte sessietijden. Raadpleeg README voor grenzen.
