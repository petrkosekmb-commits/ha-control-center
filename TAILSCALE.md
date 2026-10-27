# Automaticke pripojeni / Automatic connection

CZ: Od verze 0.3.0 muze kazda instance obsahovat volitelne mistni nastaveni
`tailscale: {"enabled": true, "profileId": "LOCAL_PROFILE_ID", "account": "user@example.invalid"}`.
Prirazeni patri pouze do mistniho sifrovaneho nastaveni, nikoli do repozitare.
ID a ucet musi odpovidat `tailscale switch --list --json` a spravce musi predem
overit pristup k danemu domu z tohoto profilu. Sdileny pristup je platny.

Centrum nejdrive zkusi dostupnost cilove adresy. Funkcni spojeni ponecha.
Pri nedostupnosti prejde pouze na presne prirazeny, jiz prihlaseny profil,
pripadne obnovi zastavene pripojeni a overi dostupnost pred odeslanim HA tokenu.
Pri chybe pred zahajenim HA operace obnovi puvodni profil, pokud jej zmenilo.
Po uspesnem pripojeni zustava profil aktivni. Nove prihlaseni provadi uzivatel.
Prepnuti profilu ovlivnuje cely pocitac a muze prerusit jine aplikace.
Zamek serializuje operace centra mezi procesy; nebrani rucnimu prepnuti v Tailscale.
Kontrola `--health-check` profil nikdy neprepina. Chyba 401 nevyvola prepnuti
ani opakovani zapisu. Domy bez tohoto nastaveni zachovaji dosavadni chovani.

EN: Version 0.3.0 supports optional per-instance local Tailscale settings using
the schema above. Verify the profile ID, account and target access before enabling.
A reachable endpoint preserves the current connection, including shared devices.
An unreachable target selects only the configured, already authenticated profile.
Stopped connections may be resumed. Authentication requiring user interaction
is reported rather than bypassed. Failed network preparation restores the previous
profile; successful selection remains active. Switching affects the whole PC.
A cross-process lock covers network preparation and HA operations, but cannot
prevent external/manual switches. Scheduled health checks never switch accounts.
HA writes are never retried automatically. Secrets and account mappings stay local.

Reference: https://tailscale.com/docs/features/client/fast-user-switching
