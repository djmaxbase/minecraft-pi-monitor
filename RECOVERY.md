# Backup, updates en herstel

## Voor wijzigingen

Databasebackups gebruiken SQLite's backup-API (ook met WAL). Bewaar daarnaast `config.json`, `data/settings.json`, `data/admin.json` en eventueel `monitor.env` op een besloten locatie. De knop Volledige databasebackup exporteert de database, niet de credentials. Bewaar die dus afzonderlijk. Dagelijkse databasebackups bewaren de laatste zeven bestanden.

## Webupdates

De ZIP wordt begrensd, gecontroleerd op traversal/symlinks en dubbele paden, op manifest-hashes, Python-syntax en schema-compatibiliteit. Een installatievergrendeling blokkeert gelijktijdige pogingen. Code wordt eerst gestaged; consistente databasebackup en oude code staan onder `data/update-rollback`. Het pending-bestand wordt duurzaam geschreven voordat code wordt vervangen.

De vaste supervisor start nieuwe code. Alleen na een gereedheidsmarker en minstens 15 seconden proceslevensduur wordt pending verwijderd. Mislukte start of ontbrekende marker leidt tot codeherstel. Een onderbroken kopieerfase wordt bij starten eerst teruggedraaid. Dit is geen garantie tegen fysieke SD-kaartschade.

Releases na 2.1.0 mogen alleen achterwaarts compatibele/additieve schemawijzigingen via de webupdater uitvoeren. Een incompatibele wijziging vereist een handmatige migratie. Automatisch codeherstel draait de database **niet** terug: zo verdwijnen geen nieuw ingelezen records. De eerste migratie uit de oude installatie verandert de spelerssleutel; herstel naar die oude code vereist ook de bijbehorende pre-migratiedatabase.

## Handmatig terugzetten

Stop eerst de systemd-service (`sudo systemctl stop uitgeteld-monitor`). Bewaar een extra kopie van de huidige data. Als `data/update-pending.json` bestaat, voer vanuit de installatiemap uit:

```sh
python3 -c 'from pathlib import Path; import updater; updater.rollback(Path.cwd())'
```

Herstart met `sudo systemctl start uitgeteld-monitor`. Voor een handmatig databaseherstel: stop de service, bewaar/verplaats de bestaande database én de bijbehorende `-wal`/`-shm`, kopieer de gekozen consistente backup naar het databasepad uit config.json en start de service. Controleer versie, recente controle en `PRAGMA integrity_check`. Een backup terugzetten verliest gegevens sinds die backup; doe dit alleen bewust.

## Beheerder herstellen

Stop de service. Vanuit de installatiemap kun je lokaal een nieuw wachtwoord instellen zonder geschiedenis te wissen:

```sh
python3 -c 'from settings import Preferences; from pathlib import Path; import getpass; p=Preferences(Path("data")); p.set_password(getpass.getpass("Nieuw wachtwoord: "),username="admin")'
```

Als MONITOR_PASSWORD in monitor.env staat, wijzig die override lokaal. Start de service opnieuw. Om een nooit voltooide wizard te herstellen blijft `data/setup-token.txt` de sleutel; verwijder geen productiedatabase om opnieuw te beginnen.

## Vertrouwenssleutel

`update_pubkey.pem` is de distributie-trust-anchor. Alleen een bezitter van de bijbehorende privé-RSA-sleutel kan updates ondertekenen. GitHub Actions gebruikt het repositorysecret `RELEASE_SIGNING_KEY`; private sleutels gaan nooit in Git of assets. Bij rotatie publiceer eerst een met de oude sleutel ondertekende release die de nieuwe publieke sleutel bevat; teken volgende releases met de nieuwe sleutel. Houd de oude sleutel offline voor herstel. Een gecompromitteerde sleutel vereist een onafhankelijk geverifieerde herinstallatie.

## Verwijderen

Stop en disable `uitgeteld-monitor`, verwijder uitsluitend de bijbehorende unit, voer daemon-reload uit en verwijder desgewenst de programmabestanden. Verwijder `data/` en configuratie alleen met een afzonderlijke bewuste handeling. Geen uninstall mag automatisch historie wissen.
