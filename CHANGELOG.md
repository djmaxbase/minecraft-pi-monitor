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
