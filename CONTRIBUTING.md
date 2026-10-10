# Bijdragen

Maak een branch en PR. Draai `python3 -m unittest discover -s tests -v` en `python3 make_release.py`. Gebruik alleen mocks of lokale fixtures voor notificaties; nooit echte telefoons in tests. Behoud observatiezekerheid, UTC-opslag en server-id's. Voeg regressietests toe voor concrete fouten. Commit nooit data, credentials, persoonlijke adressen of logs. Schemawijzigingen vereisen backup-, migratie- en hersteltests. Webreleases mogen alleen achterwaarts compatibele migraties uitvoeren.
