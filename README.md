# HA Control Center 0.2.0

Lokální plugin pro Home Assistant: entity, diagnostika, FVE, Tesla, Traccar a Lovelace dashboardy. Vyžaduje Windows, Windows PowerShell 5.1 a Python 3.10 nebo novější.

## Připojení a obnova přístupu

V profilu Home Assistantu na kartě Zabezpečení vytvořte samostatný dlouhodobý token pro tento konektor. Pro provoz lze použít vyhrazený účet s oprávněními potřebnými pro používané funkce.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-instance.ps1 -Name muj-ha -BaseUrl https://ha.example.org
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\update-token.ps1 -Name muj-ha -Gui
```

Druhý příkaz obnovuje již nastavenou instanci. Dialog má skrytý vstup. Skript ověří nový token přes API, teprve potom atomicky vymění šifrované nastavení. Bez `-Gui` se používá skrytý vstup v konzoli. Volitelný parametr `-BaseUrl` mění cílovou adresu. Změněné nastavení se načte při dalším volání bez restartu.

Token zadávejte pouze místně. Nikdy jej nevkládejte do chatu, zdrojů ani GitHubu. Nastavení je šifrováno Windows DPAPI pro aktuálního uživatele v `%APPDATA%\KosekControlCenter\config.json`. Záloha tohoto souboru není přenosná na libovolný jiný účet či počítač.

## Dlouhodobý provoz

Dlouhodobé tokeny z profilu standardně platí deset let. Server je však může odmítnout dříve, například po jejich zrušení nebo změně autentizačních dat. Plugin neobchází přihlášení a nemůže obnovit zrušený token bez nového přihlášení uživatele.

Nástroj `connection_health` provede malý požadavek na API a vrátí pouze stav připojení a datum platnosti. Rozlišuje odmítnutí tokenu, síť, certifikát a nedostatečná oprávnění. Údaje přečtené z JWT nejsou kryptograficky ověřeny; důkazem přístupu je odpověď API. Upozornění na expiraci má hranice 90 a 30 dní.

Pro pravidelnou kontrolu lze v Plánovači úloh Windows spouštět pod stejným uživatelem:

```powershell
powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "C:\cesta\ha-control-center\scripts\check-health.ps1" -Notify
```

Použijte stabilní instalační složku, nikoliv dočasnou cache pluginu. Stav je v `%LOCALAPPDATA%\KosekControlCenter\health\status.json`. Kontrola nezapisuje do Home Assistantu. Oznámení Windows se zobrazí jen při změně problému, při dosažení další hranice expirace a při obnovení přístupu. Zobrazení závisí na nastavení oznámení Windows a přihlášení uživatele. Vypnutý počítač kontrolu neprovádí; plánovač má zmeškaný běh spustit po dostupnosti.

## Dashboardy a služby

- `save_dashboard` před zápisem zálohuje, kontroluje otisk posledního načtení a ověřuje uložený obsah.
- `call_service` provede konkrétně požadovanou službu. Po volání ověřte stav dotčených entit.
- Zápisy se při nejistém výsledku automaticky neopakují.
- Zálohy zůstávají v `%LOCALAPPDATA%\KosekControlCenter\backups`. Mohou obsahovat soukromé údaje a nepatří do repozitáře.
- Očištěný export je dostupný na výslovný požadavek; před sdílením vždy zkontrolujte obsah.

## Aktualizace a název

Zobrazovaný název je **HA Control Center**. Technický identifikátor `kosek-control-center`, jména interních souborů a složka `KosekControlCenter` zůstávají zachované pro kompatibilitu stávající instalace a šifrovaného nastavení. Veřejný i soukromý balíček používají stejný zdroj; instalujte pouze jeden z nich.

Po aktualizaci kódu znovu připojte plugin nebo restartujte aplikaci. Pouhá výměna tokenu restart nevyžaduje. Helper `read-runtime-config.ps1` smí používat pouze server přes soukromou rouru: jeho výstup obsahuje pracovní token, proto jej nespouštějte ručně ani nelogujte.

## Ověření

```powershell
python -m unittest discover -s tests -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-health.ps1
```

Testy používají syntetická data. Ověřují rotaci nastavení, chyby přístupu, expiraci, TLS, první WebSocket rámec a bezpečnost zápisů. Úspěch testů nenahrazuje živé ověření uživatelovy instance.

## Tailscale 0.3.0

Automaticke pripojeni podle domu / Automatic per-home connection: [TAILSCALE.md](TAILSCALE.md). Prirazeni uctu a tokeny zustavaji pouze mistne. Account mappings and tokens remain local.
