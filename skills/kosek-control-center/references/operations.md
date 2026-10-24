# Provoz a bezpecnost

## Pripojeni instance

Spustit z korene pluginu:

```powershell
.\scripts\setup-instance.ps1 -Name ha-syrda -BaseUrl http://homeassistant.local:8123
```

Skript skryte vyzada dlouhodoby pristupovy token. Token ulozi zasifrovany pomoci Windows DPAPI do `%APPDATA%\KosekControlCenter\config.json`. Soubor nekopirovat na OneDrive.

## Kontrola pripojeni

```powershell
.\scripts\test-connection.ps1 -Name ha-syrda
```

## Umisteni dat

- Zasifrovane nastaveni: `%APPDATA%\KosekControlCenter\config.json`
- Neupravene lokalni zalohy: `%LOCALAPPDATA%\KosekControlCenter\backups`
- Ocistene uzitecne exporty: `%USERPROFILE%\Documents\Codex\Home Assistant\01-dashboards`

## Bezpecnostni hranice

- Nastroje pro cteni mohou bezet primo.
- Konkretne zadany zapis dashboardu a volani sluzby nevyzaduji dalsi potvrzeni uzivatele.
- `save_dashboard` spojuje pripravu, zalohu, kontrolu otisku a zapis s overenim; vyzaduje `expected_current_sha256` z posledniho cteni.
- `call_service` provede zadane volani; stav dotcenych entit je treba nasledne precist.
- Volitelne nastroje `prepare_*` a `confirm_*` zustavaji kompatibilni. Jejich kod slouzi k propojeni pripravy s provedenim v bezicim procesu, nikoli jako dalsi lidske schvaleni.
- Zaloha dashboardu vznika pred ulozenim zmeny.
- Lokalni export rekurzivne odstranuje klice a retezce pripominajici token, heslo, tajemstvi nebo autorizacni udaj.
