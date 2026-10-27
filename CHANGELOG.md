# Změny

## 0.3.0

- Automaticka priprava site podle mistniho prirazeni domu k overenemu profilu Tailscale.
- Funkcni sdilene spojeni zustava zachovano, pri chybe prepnuti navrat k puvodnimu profilu.
- Zamek mezi procesy chrani prubeh HA operace; pravidelna kontrola profil nemeni.
- Automatic per-instance Tailscale selection, bounded reconnect, rollback and synthetic tests.

## 0.2.0

- Novy zobrazovany nazev HA Control Center. Technicky identifikator a cesta sifrovaneho nastaveni zustavaji kompatibilni.
- Diagnostika pripojeni rozlisuje odmitnuti tokenu, jeho datum platnosti, TLS, opravneni a dostupnost.
- Skryty mistni dialog pro vymenu tokenu s overenim pred ulozenim.
- Kontrola pro planovac Windows, stav bez tajnych udaju a oznameni jen pri zmene stavu, vcetne hranic 90 a 30 dni.
- WebSocket zachova prvni ramec prijaty spolu s handshake, overuje odpoved serveru a ukonci cekani pri EOF.

## 0.1.2 — 2026-10-16

- Konkrétní pokyn uživatele stačí k provedení změny; plugin již nevyžaduje další schvalování náhledu nebo použití konektoru.
- Nové nástroje `save_dashboard` a `call_service` provádějí zadanou akci přímo.
- Uložení dashboardu zachovává místní zálohu, povinný očekávaný SHA256, kontrolu souběžných změn a zpětné ověření obsahu.
- Volitelné `prepare_*` a kompatibilní `confirm_*` nástroje zůstávají dostupné bez dodatečného lidského potvrzení.
- Názvy záloh obsahují mikrosekundy, aby rychlé navazující úpravy nepřepisovaly předchozí zálohu.
- Doplněné syntetické testy přímého zápisu, konfliktů, záloh, ověření a volání služeb.

## 0.1.1 — 2026-10-05

- Automatické načítání změněného nastavení a tokenu při dalším volání bez restartu MCP serveru.
- Bezpečné odmítnutí nečitelného nastavení; při chybě se nepoužije starý token.
- Rozlišení odmítnutého tokenu (401) a nedostupné sítě bez výpisu přihlašovacích údajů.
- Interní DPAPI helper se skrytým procesem a soukromou rourou; launcher již nepředává tokeny v proměnné prostředí.
- Opravená kompatibilita pomocného Windows PowerShellu 5.1 s prostředím PowerShellu 7.
- Přidaný `update-token.ps1`: skrytý vstup, ověření API před uložením a atomické uložení kompatibilní s Windows PowerShellem 5.1.
- Očištěné exporty mají místní výchozí složku bez automatického kopírování do OneDrivu.
- Regresní testy pro změny tokenu za běhu, chyby nastavení, zotavení a zprávy při HTTP 401.

## 0.1.0

- Původní místní konektor pro více instancí Home Assistantu, diagnostiku, dashboardy a potvrzované služby.
