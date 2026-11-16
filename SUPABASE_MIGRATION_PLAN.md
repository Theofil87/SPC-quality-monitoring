# Supabase migrációs terv

Állapot: **előkészítés, végrehajtásra még nincs jóváhagyás**. A jelen dokumentumban szereplő létrehozási, betöltési és jogosultsági műveleteket most nem hajtottuk végre. Az eredeti adatbázis-felmérés 2026-11-12-én történt; a kapukat a tényleges migráció előtt újra ellenőrizni kell.

2026-11-16-i **DESIGN READY** történeti tervezési döntés nem snapshot-, staging- vagy production-GO. A korábban tervezett saját JSONL-manifesztum, age X25519 és Ed25519 megoldás az egyszerűsített alapfolyamatban nem kötelező; lásd az opcionális függeléket.

2026-11-13-i pontosítás: a Supabase `postgres` és `supabase_admin` default ACL-jeit újra, kizárólag olvasással ellenőriztük. A tényleges migrációs szerepkört még nem választották ki, ezért annak default ACL-je továbbra sem ellenőrzött.

2026-11-15-én, 20:31:17–20:31:21 között (Europe/Budapest, UTC+01) a PostgreSQL 18.6 forrás és a PostgreSQL 17.12 tesztadatbázis teljes soronkénti összehasonlítása **DATA CONSISTENCY PASS** eredményt adott: mind a 12 tábla 572 239 rekordja és 76 oszlopának értékei, beleértve a `NULL`-okat, egyeztek. A stabil elsődleges kulcs szerinti összehasonlítás típusos numerikus és időbélyegértékeket használt; JSON-oszlop nem volt. A 12 PK és 16 FK külön ellenőrzése nem talált NULL vagy duplikált PK-t, illetve árva FK-t; mind a 11 sequence vizsgált konfigurációja, `last_value` és `is_called` állapota egyezett. A teljes, 25 mezős ACTIVE baseline-rekord és mind a hat numerikus érték külön is egyezett.

Ez **kizárólag történeti bizonyíték: nem helyettesíti a közvetlenül a migráció előtt végzett forrásfrissességi ellenőrzést**. A két `REPEATABLE READ READ ONLY` tranzakció egymástól független snapshotot használt, írás- és sequence-fagyasztás nélkül; a sequence-állapot nem MVCC-snapshot szerinti. A vizsgálat nem bizonyítja az azóta történt változások hiányát, és nem helyettesíti a teljes objektum-/indexdefiníció-ellenőrzést vagy a későbbi archívum és izolált restore ellenőrzését.

## Architecture overview

- Eredeti, hiteles adatforrás: helyi PostgreSQL 18, `spc_quality_monitoring`. A migráció közvetlen forrása **a friss, ellenőrzött PG18-adatállományból újonnan, izolált PostgreSQL 17-en visszaállított és teljesen validált adatbázis**, nem a korábbi tesztadatbázis. A `localhost:5433` `spc_quality_monitoring_pg17_test` kizárólag történeti összehasonlítási eredményhez tartozik; nevét vagy jelenlegi tartalmát nem szabad migrációs forrásként feltételezni.
- Cél: Supabase projekt `zxozwihqojkbzinvwuso`, PostgreSQL 17.11, `postgres` adatbázis, `public` séma. Az ellenőrzéskor a sémában nem volt alkalmazástábla, nézet, szekvencia vagy függvény.
- Az alkalmazás a [dashboard.py](dashboard.py) fájlban SQLAlchemy/psycopg2 segítségével, közvetlen PostgreSQL-kapcsolaton olvas. Nem használja a Supabase Data API-t. A kapcsolat `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` és a libpq TLS-változóival állítható be.
- A [meglévő, teljes mentés](backups/spc_quality_monitoring_2026-11-12_active_baseline.dump) PostgreSQL 18.6-ról készült, SHA-256: `8752FABE9A96A973BF5FB9FA014005248476A4336AFF56B156CBCA866D9CFE48`. A PostgreSQL 17-es próba-visszaállítás sikeres volt, és a 12 tábla tartalma egyezett az archívummal. Ez nem igazolja, hogy a PostgreSQL 18-as eredeti azóta nem változott.
- A sorrend: a PG18-forrás ellenőrzése és fagyasztása; **friss PG18-mentés** és SHA-256; abból külön, üres PG17 célba visszaállítás; a PG18 és az új PG17 teljes összehasonlítása; az igazolt PG17-ből új PG17 migrációs archívum és annak külön izolált restore-próbája, teljes összehasonlítása és dashboardtesztje. A fagyasztást csak az ellenőrzések lezárulta után oldjuk fel. Ezután, külön előfeltételekkel következhet az első izolált stagingpróba, a hardening, a második teljes stagingpróba és a **staging GO**. Éles migráció előtt ismét igazolni kell a forrás frissességét. Eltérés esetén álljunk meg; ne írjuk felül az eredeti mentést.
- A 17.12 → 17.11 azonos főverzió, de a régebbi célon nem garantált az összes patchszintű viselkedés és a Supabase által kezelt jogosultságok kompatibilitása. A célverzión, elkülönített staging környezetben végzett teljes próba kötelező. A 18 → helyi 17 próba nem helyettesíti a Supabase-próbát.

## Source inventory

### Táblák és betöltési sorrend

Az alábbi darabszámok a korábban ellenőrzött, 2026-11-12-i pillanatképre vonatkozó tájékoztató értékek, nem minden későbbi migráció kötelező átvételi értékei. A friss, a mentéshez kapcsolt forrásellenőrzés jegyzőkönyve az irányadó. A sorrend a foreign key függőségeket követi; a táblák teljes tartalma szükséges, nem csak a BOOTH_01 / A-L1 részhalmaz.

| Sorrend | Tábla | Rekord | Közvetlen függőség |
|---:|---|---:|---|
| 1 | `dim_booth` | 2 | — |
| 2 | `dim_shift` | 3 | — |
| 3 | `dim_measurement_point` | 18 | — |
| 4 | `dim_specification` | 1 | — |
| 5 | `dim_track_axis` | 4 | `dim_booth` |
| 6 | `dim_robot` | 8 | `dim_track_axis` |
| 7 | `dim_batch` | 1 860 | `dim_shift` |
| 8 | `dim_cabin` | 9 300 | `dim_batch`, `dim_booth` |
| 9 | `fact_quality_measurement` | 167 400 | `dim_cabin`, `dim_measurement_point`, `dim_specification` |
| 10 | `bridge_measurement_robot` | 393 409 | `fact_quality_measurement`, `dim_robot` |
| 11 | `fact_process_event` | 233 | `dim_batch`, `dim_booth` |
| 12 | `spc_baseline` | 1 | `dim_booth`, `dim_measurement_point`, `dim_specification`, valamint önhivatkozás |

A `spc_baseline` a három dimenzió után már betölthető; a fenti sorrend csak egy lehetséges topologikus sorrend. Több baseline esetén a teljes történetet, az azonosítókat és a `supersedes_baseline_id` kapcsolatokat is meg kell őrizni.

### Objektumok és integritás

- **12 PK, 16 FK, 9 UNIQUE, 20 CHECK**; a forráson 66 `NOT NULL` oszlop van. A 39 indexből 21 PK/UNIQUE index, 18 külön index. Fontos a részleges `uq_spc_baseline_one_active_per_scope` és az `idx_spc_baseline_scope_effective`; nem elég csak a PK-kat áthozni.
- **11 `GENERATED ALWAYS AS IDENTITY` szekvencia**: a kapcsolótáblán kívül minden táblához egy. A mentés és a teszt-visszaállítás a szekvenciák `last_value` és `is_called` állapotát megőrizte; az `spc_baseline_baseline_id_seq` értéke `1`, `is_called=true`.
- Két `plpgsql` triggerfüggvény: `enforce_spc_baseline_immutability()` és `enforce_spc_baseline_supersession()`. Az előbbi azonosítót, jóváhagyott értékeket és életciklust védi; az utóbbi ellenőrzi az előd verzióját.
- Két engedélyezett trigger a `spc_baseline` táblán: `trg_spc_baseline_immutability` (`BEFORE UPDATE OR DELETE`) és `trg_spc_baseline_supersession` (`AFTER INSERT OR UPDATE`, constraint trigger, `DEFERRABLE INITIALLY IMMEDIATE`). A triggerek és a négy baseline FK, köztük az azonos hatókörű önhivatkozás megőrzése kötelező.
- A forrásban csak a beépített `plpgsql` extension van. A célban ezen kívül `pg_stat_statements`, `pgcrypto`, `supabase_vault` és `uuid-ossp` is telepített; ezeket nem kell törölni vagy újratelepíteni. Nincs azonosított további alkalmazás-extension.
- A forrástáblákon nincs RLS, a 13 forrásnézeten nincs külön `security_invoker` beállítás. A cél biztonságát ezért külön kell kialakítani; a forrásállapot önmagában nem biztonsági sablon.

### Baseline: teljes referenciarekord

Az értékeket **nem szabad újraszámolni, újra jóváhagyni vagy kézzel új baseline-ként létrehozni**. A teljes sort az archívumból, meglévő identity-vel kell átvinni.

| Mező | Tárolt érték |
|---|---|
| `baseline_id`, `version`, `status` | `1`, `1`, `ACTIVE` |
| `booth_id`, `measurement_point_id`, `specification_id` | `1`, `1`, `1` — BOOTH_01 / A-L1 / Coating Thickness |
| `window_start`, `window_end` | `2026-01-01 06:00:00+01`, `2026-01-19 06:00:00+01` |
| `effective_from`, `effective_to` | `2026-01-19 06:00:00+01`, `NULL` |
| `approved_by`, `approved_at` | `Bela Pager`, `2026-11-07 20:56:53.02371+01` |
| `rationale`, `source_query_hash`, `supersedes_baseline_id` | `NULL`, `NULL`, `NULL` |
| `n_observations`, `n_valid_mr` | `450`, `405` |
| `center_line`, `sigma` | `74.540491`, `1.197419` |
| `i_lcl`, `i_ucl` | `70.948233`, `78.132749` |
| `mr_center`, `mr_ucl` | `1.350689`, `4.412701` |
| `created_at`, `updated_at` | mindkettő `2026-11-07 20:54:03.633118+01` |

A forrás munkamenet időzónája `Europe/Budapest`, a Supabase-é `UTC`. A `timestamptz` mezőket azonos időpillanatként, nem formázott szövegként kell összevetni. A mérési `timestamp without time zone` értékeket tilos UTC-vé átértelmezni; az SPC-nézet a helyi mérési időt kifejezetten `Europe/Budapest` szerint értelmezi.

## Dependency order

1. Ellenőrizzük a cél ürességét és a szükséges `plpgsql` rendelkezésre állását. További extension létrehozása nem szükséges.
2. Táblák és az identity szekvenciák létrehozása; a `NOT NULL` és a tábladefinícióba ágyazott CHECK feltételek maradjanak meg.
3. PK és UNIQUE constraint-ek, illetve az általuk létrehozott indexek; **ne hozzuk létre másodszor** ugyanazokat az indexeket. A hivatkozott egyedi kulcsnak a rá mutató FK előtt kell léteznie.
4. A 18 önálló index és a szekvenciák pontos állapota. Az adatbetöltés után a `setval` állapotokat az archívum állítsa vissza; ne csak `max(id)` alapján becsüljük őket.
5. FK-k és CHECK-ek ellenőrzése; a `spc_baseline` önhivatkozó FK-jához az összetett scope UNIQUE kulcs szükséges.
6. A két baseline-függvény, majd a két baseline-trigger létrehozása. Ha az archívum alapértelmezett sorrendjét használjuk, a `pg_restore` a definíciókat és a post-data objektumokat a saját függőségi rendjében kezeli: a PK/FK és indexek jellemzően **az adatok után** jönnek létre. Ne keverjük a kézi és az archívumos létrehozást.
7. Nézetek a következő topologikus rendben; az egy sorban felsorolt, egymástól független nézetek sorrendje tetszőleges:

| Sorrend | Nézet | Közvetlen nézetfüggőség |
|---:|---|---|
| 1 | `v_measurement_enriched` | — |
| 2 | `v_spc_rule_results` | `v_measurement_enriched` |
| 3 | `v_spc_rule_results_booth01_a_l1` | `v_spc_rule_results` |
| 4 | `v_capability_measurements_booth01_a_l1` | `v_measurement_enriched`, `v_spc_rule_results_booth01_a_l1` |
| 5 | `v_drift_shift_measurements_booth01_a_l1` | `v_capability_measurements_booth01_a_l1` |
| 6 | `v_batch_quality` | `v_measurement_enriched` |
| 7 | `v_event_evaluation_context` | `v_batch_quality` |
| 8 | `v_booth_quality_daily`, `v_cabin_quality`, `v_measurement_point_quality`, `v_production_volume`, `v_robot_attribution_quality`, `v_shift_quality_daily` | `v_measurement_enriched` |

Mind a 13 telepített definíciót és közvetlen függőségeit a PostgreSQL 17 katalógusából vizsgáltuk. A `v_robot_attribution_quality` emellett a robot-, tengely-, kabin- és kapcsolótábláktól függ; a `v_event_evaluation_context` az esemény- és booth-tábláktól is. A `v_spc_rule_results` a tárolt baseline-limitértékeket, az érvényességi időszakot és az eredeti Rule 1–4 logikát használja. A [views.sql](sql/views.sql) dokumentálja az alkalmazás definícióit, de a migráció alapja az aktuális, tényleges adatbázisarchívum.

## Security and access control

### Ellenőrzött célállapot és kötelező kapu

- A cél `public` sémája az ellenőrzéskor üres; így ott alkalmazástáblán RLS vagy policy még nincs.
- Az `anon` és `authenticated` szerepkörnek van `USAGE` jogosultsága a `public` sémán. A `postgres` és `supabase_admin` által létrehozandó `public` táblákra mindkettőnek **széles alapértelmezett jogosultságai** vannak, beleértve a `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER` és `MAINTAIN` jogosultságokat. Új szekvenciákra `USAGE`, `SELECT`, `UPDATE`, függvényekre `EXECUTE` is jár. A `service_role` is széles jogosultságokat kap és megkerüli az RLS-t.
- A `postgres` célrole nem superuser, de `BYPASSRLS` jogosultságú; az `authenticator` átállhat az `anon`, `authenticated`, `service_role` szerepkörre. Az ellenőrzéskor sem `dashboard_reader`, sem `spc_dashboard_reader` nem létezett.
- A lekérdezett `pgrst.db_schemas` munkamenet-beállítás `NULL`, és megfelelő adatbázis-/roleszintű beállítást sem találtunk. **Ebből nem következik**, hogy a Data API ki van kapcsolva vagy a `public` nincs kitéve: a PostgREST konfigurációja máshol is lehet. A Data API állapotát, az Exposed schemas listát és az Automatically expose new tables beállítást a Supabase Dashboardon külön kell ellenőrizni.
- **Blokkoló:** addig semmit nem szabad éles célra betölteni, amíg a tulajdonos nem igazolta, hogy az alkalmazásobjektumok nem érhetők el a Data API-n, illetve nincs jóváhagyott, kipróbált ACL/RLS-beállítás és hálózati védelem. A legegyszerűbb javaslat: ha más alkalmazás nem igényli, a Data API kikapcsolása vagy a `public` kivétele az exposed schemas listából. Ez más Supabase-funkciókat érinthet, ezért előzetes hatásvizsgálat szükséges.

A betöltés és éles átállás kötelező kapuja továbbá: azonosított és jóváhagyott migrációs bejelentkezés és tényleges owner; a tényleges `current_user` default ACL-jeinek és a már létező objektumok jogosultságainak külön ellenőrzése; valamint tesztelt RLS-, nézettulajdonosi és view-security modell. Az `anon`, `authenticated` és `PUBLIC` ne kapjon nem kívánt hozzáférést az alkalmazásobjektumokhoz. A dashboard külön, nem tulajdonos, `NOBYPASSRLS`, csak a szükséges objektumokat olvasó szerepkört és ellenőrzött TLS-t használjon. A Data API és a hálózat maradjon zárt a restore és az ellenőrzés alatt; az API-kitettséget és a közvetlen SQL-jogokat külön teszteljük. A `--no-owner --no-acl` önmagában nem korlátozza a cél default ACL-jeit. A [részletes technikai példák](#opcionális-függelék-postgresql-acl-és-rls-technikai-részletek) opcionálisak, maguk a fenti biztonsági kapuk nem.

### Hálózat és Streamlit

A migrációhoz a Supabase által ajánlott **direct** kapcsolatot használjuk, ha az IPv6/IPv4 elérhetőség adott; a pooler módját, hostját és felhasználónevét ne találgassuk, hanem a Supabase **Connect** képernyőről vegyük. A tartós Streamlit folyamathoz direct vagy IPv4 esetén session pooler javasolt; a custom role pooleres hitelesítését ténylegesen tesztelni kell. Transaction pooler használatakor a session state és prepared statement korlátozásokat külön validálni kell.

TLS-sel, lehetőleg `PGSSLMODE=verify-full` és a megfelelő bizalmi lánc használatával csatlakozzunk; a megfelelő CA, DNS és Cloud-hálózati útvonal előzetesen ellenőrizendő. A Streamlit Community Cloud titkait a szolgáltatás secrets felületén kezeljük, ne a repóban. A jelenlegi dashboard a fenti `PG*` változókat és a libpq TLS-beállításait használja; a cloud oldali konfiguráció és a hibaüzenetek érzékeny adatokat nem fedhetnek fel.

## Schema migration

### Forrásfrissesség, mentés és helyi próba

Az alábbiak jövőbeli, külön jóváhagyott lépések. A korábbi PASS és restore történeti bizonyíték, nem a mostani forrásállapot igazolása. A cél a meglévő PostgreSQL-eszközök és egy egyszerű, ellenőrzött sorösszehasonlítás használata; saját manifesztumrendszer vagy validátor implementálása nem előfeltétel.

1. **PG18-forrás és fagyasztás:** azonosítsuk a `localhost:5432` `spc_quality_monitoring` adatbázist, verzióval és porttal; vizsgáljuk meg a tényleges aktuális állapotot, a megbízhatóan megállapítható változásokat és a baseline-t. A DBA állítsa le és akadályozza meg az író alkalmazásokat, háttérfeladatokat, replikációs írókat, DDL-t és `nextval`/`setval` műveleteket; rendezze a folyamatban lévő és prepared tranzakciókat, valamint a sequence-cache-t használó író munkameneteket. A fagyasztás kezdetét, kontrollját és végét időbélyeggel jegyzőkönyvezze. A `pg_stat_activity` pillanatfelvétele vagy egy read-only tranzakció önmagában nem bizonyítja az írások kizárását.
2. **Friss PG18-mentés:** tulajdonosi jóváhagyással, a fagyasztás alatt PG18 `pg_dump` készítsen új, felülírást kizáró mentést a tényleges forrásról. Az archívum kilépési kódját, méretét és a megfelelő verziójú `pg_restore --list` eredményét ellenőrizzük; SHA-256 értékét védett jegyzőkönyvbe rögzítsük és felhasználás előtt ellenőrizzük. A hash sértetlenségvizsgálat, nem eredethitelesítés vagy teljes adatellenőrzés.
3. **Új PG17 migrációs forrás:** külön jóváhagyott, a régi tesztadatbázistól és a PG18-tól elkülönített, új vagy bizonyítottan üres PG17 adatbázisba állítsuk vissza a friss PG18-mentést. PG17 `pg_dump` nem menthet újabb főverziójú PG18 szervert; a PG18-eszközökkel előállított dump és SQL PG17-kompatibilitása nem garantált. A DBA vizsgálja át a PG18 `pg_restore` által generált SQL-t és válasszon előzetesen kipróbált PG18→PG17 restore-módszert, hibánál megállással; inkompatibilis objektum, nem bizonyított kompatibilitás vagy részleges restore esetén **FAIL / NO-GO**. A `public` létezését és az archívum TOC-ját külön ellenőrizzük; nincs automatikus törlés vagy javítás. A restore idején az azon kívüli írásokat, DDL-t és sequence-mozgásokat zárjuk ki, majd az új PG17-et tartsuk írásvédve.
4. **Frissességi és teljes sorösszehasonlítás:** a fagyasztott PG18 és az új PG17 között külön `REPEATABLE READ READ ONLY` kapcsolatokban hasonlítsuk össze mind a 12 tábla minden sorát és oszlopát stabil PK-sorrendben, beleértve a `NULL`, pontos numerikus és típusos időértékeket. A `timestamptz` azonos időpillanat, a `timestamp without time zone` változatlan helyi érték. Táblánként jegyezzük fel a két darabszámot, egyező, eltérő és csak egyik oldalon található sorokat; eltérésnél a PK-t és oszlopokat. A `spc_baseline` minden mezője, köztük az ACTIVE rekord és mind a hat limit a fenti jóváhagyott referenciával is egyezzen. **Darabszám vagy hash nem helyettesíti a teljes sorösszehasonlítást.**
5. **Séma és sequence:** ellenőrizzük a PK/FK-definíciókat és a NULL/duplikált PK, illetve árva FK hiányát, a CHECK/UNIQUE constraint-eket, az indexek definícióját és érvényességét, a 13 nézet, függvény és trigger definícióját. A PG18/17 verziófüggő katalógusreprezentációt, például a `NOT NULL` kezelését szemantikusan, a DBA által ellenőrzötten kell összevetni; ismeretlen eltérés **FAIL**. Mind a 11 sequence konfigurációját, identity/owner kapcsolatát, `last_value` és `is_called` értékét `nextval()` nélkül rögzítsük. A jóváhagyott, érzékeny adatokat nem nyilvánosan tartalmazó jegyzőkönyvben legyen forrásazonosság, időpont, tételes eredmény és felelős.
6. **PG17 migrációs mentés és izolált próba:** az igazolt új PG17-ből, a fagyasztás fenntartása mellett a következő szakasz szerint készüljön új PG17 custom `pg_dump` `CreateNew` módban; ellenőrizzük kilépési kódját, méretét, TOC-ját és SHA-256 hash-ét. Külön jóváhagyással, mindkét forrástól elkülönített, új vagy bizonyítottan üres második PG17 adatbázisba, PG17 `pg_restore --exit-on-error --single-transaction` használatával állítsuk vissza. Ha a `public` már létezik, a felülvizsgált TOC-listából csak a `SCHEMA - public` bejegyzést hagyjuk ki. Ne használjunk `--clean` vagy `--create` kapcsolót. Nem üres cél vagy restore-hiba esetén álljunk meg.
7. **Teljes restore-validáció:** a PG18 és az új PG17 forrás védelmét a restore és az összehasonlítás végéig tartsuk fenn. Read-only kapcsolatokkal az új PG17 forrás és a második visszaállított cél mind a 12 táblájának teljes sorhalmazát a 4. pont módszerével közvetlenül hasonlítsuk össze; az új PG17 előzőleg igazoltan egyezik a PG18-cal. Ellenőrizzük az 5. pontban felsorolt objektumokat és sequence-eket, a teljes baseline-t és a jóváhagyott limitértékeket. A mentés a teljes restore és egyezés után tekinthető bizonyítottan visszaállíthatónak.
8. **Dashboard és döntés:** kizárólag ideiglenes kapcsolati beállításokkal futtassuk az eredeti dashboard-lekérdezéseket és Streamlit AppTestet az izolált restore-adatbázison; ellenőrizzük a tényleges célazonosságot, baseline-t, szűrőket és eredményeket. Csak read-only dashboardtesztet használjunk; más, esetleg író tesztet ne futtassunk a restore-célon. **PASS:** minden fenti ellenőrzés teljes és egyező, a fagyasztás folytonossága igazolt, a DBA és a tulajdonos jóváhagyja. Ezután a DBA feloldhatja a források fagyasztását, de a második restore-referencia védelme a staging-összehasonlítás végéig megmarad. Bármely eltérés, hiányzó jogosultság, fagyasztási rés, hash-, dump-, restore- vagy teszthiba **FAIL / NO-GO**; a felelős döntsön a biztonságos feloldásról és a külön jóváhagyott újrakezdésről. A Supabase-re történő betöltés és az első stagingpróba csak a sikeres helyi validáció és a [rollback előfeltételei](#rollback-eljárás) után indulhat.

A sorösszehasonlításhoz használható a projekt meglévő `psycopg2` drivere és egy egyszerű, DBA által felülvizsgált, csak olvasó összehasonlító eszköz. Mindkét kapcsolaton ellenőrizzük a tényleges `transaction_read_only` és `REPEATABLE READ` állapotot, a teljes adathoz való hozzáférést és az RLS okozta sorhiány kizárását. A katalógusból azonosított mind a 12 táblára azonos oszlopsorrenddel és `ORDER BY` elsődleges kulccsal olvassuk végig és hasonlítsuk össze a két sorfolyamot; a kapcsolótábla kulcsa `(measurement_id, robot_id)`. A `numeric` értékeket pontos decimálisként kezeljük, float-konverzió nélkül. Nem támogatott típus, nem teljesen olvasható sorfolyam, hiba vagy ismeretlen lefedettség **FAIL**. Ennek teljes lefedettségét, hibakezelését és célazonosítását a valódi futás előtt külön tesztkörnyezetben igazolni kell; nem állítjuk, hogy ilyen eszköz már készen áll. Az eredményeket és a mentést hozzáférés-korlátozott, jóváhagyott helyen őrizzük; jelszó és soradat ne kerüljön nyilvános naplóba.

### Rövid végrehajtási ellenőrzőlista

Minden kapuhoz időbélyegzett bizonyíték és felelős szükséges. **PASS** csak teljes, igazolt egyezés; eltérés, sikertelen lépés vagy nem ellenőrizhető követelmény **FAIL / NO-GO**. A lista nem jelent előzetes jóváhagyást.

| Kapu | PASS feltétele |
|---|---|
| Forrásfrissesség | Az aktuális PG18 azonosított, a friss mentéshez kapcsolt állapota és a fagyasztás folytonossága igazolt; a régi PASS nem elég. |
| Mentés és SHA-256 | Friss PG18-mentés, majd az igazolt új PG17-ből PG17 migrációs mentés készült; a kilépési kód, TOC és a felhasználás előtt újra ellenőrzött SHA-256 mindkettőnél megfelelő. |
| Izolált PG17 restore | A friss PG18-mentésből új PG17 forrás, majd a PG17 migrációs mentésből külön üres PG17 cél sikeresen visszaállt; a verziókompatibilitás igazolt. |
| Teljes sorösszehasonlítás | PG18 ↔ új PG17, majd új PG17 ↔ külön restore: mind a 12 tábla minden sora és oszlopa egyezik; darabszám vagy hash önmagában nem elég. |
| Objektumok és jogosultságok | PK/FK-integritás, indexek, constraint-ek, nézetek, függvények, triggerek és sequence-ek megfelelőek; a cél ACL/RLS, role, Data API, view security és TLS ellenőrzése sikeres az adott kapun. |
| ACTIVE baseline | A teljes rekord, összes metaadat és mind a hat numerikus érték típusosan, pontosan egyezik; nincs újraszámítás vagy újrajóváhagyás. |
| Dashboard | Az izolált restore-on az eredeti lekérdezések és AppTest sikeresek; stagingen a dedikált role-lal és böngészőben is igazolt a működés. |
| Rollback | Az adott célra a kipróbált, hozzáférhető restore- vagy más, a rollback fejezetben megengedett út, a felelősök és a dashboard visszaútja igazoltak. |

A Supabase első izolált próbája csak a helyi kapuk és a rá vonatkozó rollback-előfeltételek után indulhat. Staging GO csak a második teljes próba után adható; az éles átálláshoz külön frissességi és biztonsági ellenőrzés, rollback és külön GO szükséges.

### Előkészítés és migrációs archívum

1. A fenti friss PG18-mentésből újonnan visszaállított PG17-forrás azonosságát és a **forrásfrissességi ellenőrzés** sikerét a tulajdonos írásban erősítse meg. Az alábbi PG17-archívum csak ebből a bizonyítottan új forrásból készülhet, nem a régi tesztadatbázisból. A DBA a futtatás előtt ellenőrizze és állítsa be a jóváhagyott új PG17 forrás `PGHOST`, `PGPORT`, `PGDATABASE` és `PGUSER` értékeit; a változók megléte önmagában nem bizonyítja a forrást. A stagingindítási engedély csak a mentés és az izolált helyi restore-ellenőrzés után következik. A dokumentált írás- és sequence-fagyasztást a helyi restore és teljes összehasonlítás befejezéséig tartsuk fenn. A következő parancs **csak jövőbeli, külön jóváhagyott művelet**, nem futott le:

   ```powershell
   if (-not $env:PGHOST -or -not $env:PGPORT -or -not $env:PGDATABASE -or -not $env:PGUSER) {
     throw 'A jóváhagyott új PG17-forrás kapcsolati beállításai hiányoznak.'
   }
   if ($env:PGDATABASE -eq 'spc_quality_monitoring_pg17_test') {
     throw 'A történeti tesztadatbázis nem migrációs forrás.'
   }
   $archive = 'C:\Users\Note\Documents\SPC-quality-monitoring\backups\spc_pg17_migration.dump'
   $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
   $startInfo.FileName = 'C:\Program Files\PostgreSQL\17\bin\pg_dump.exe'
   $startInfo.Arguments = '--no-password --schema=public --format=custom --no-comments'
   $startInfo.UseShellExecute = $false
   $startInfo.RedirectStandardOutput = $true
   $startInfo.RedirectStandardError = $true
   $process = $null
   $stream = $null
   try {
     $stream = [System.IO.File]::Open(
       $archive, [System.IO.FileMode]::CreateNew,
       [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
     $process = [System.Diagnostics.Process]::Start($startInfo)
     $stderrTask = $process.StandardError.ReadToEndAsync()
     $process.StandardOutput.BaseStream.CopyTo($stream)
     $process.WaitForExit()
     $stderr = $stderrTask.GetAwaiter().GetResult()
     if ($stderr) { [Console]::Error.WriteLine($stderr) }
     if ($process.ExitCode -ne 0) { throw "A pg_dump sikertelen: $($process.ExitCode)." }
     $stream.Dispose()
     $stream = $null
     & 'C:\Program Files\PostgreSQL\17\bin\pg_restore.exe' --list $archive
     if ($LASTEXITCODE -ne 0) { throw 'Az archívumjegyzék nem olvasható.' }
     Get-FileHash -LiteralPath $archive -Algorithm SHA256 -ErrorAction Stop
   }
   catch {
     if ($process -and -not $process.HasExited) {
       $process.Kill()
       $process.WaitForExit()
     }
     throw
   }
   finally {
     if ($process) { $process.Dispose() }
     if ($stream) { $stream.Dispose() }
   }
   ```

   A `CreateNew` atomi létrehozást biztosít: létező célfájl esetén hibával megáll, és a `pg_dump` sem indul el. A bináris stdout közvetlenül a kizárólagosan megnyitott fájlba kerül. Sikertelen vagy megszakított mentés után a részleges fájlt ne tekintsük érvényesnek; ellenőrzés és külön jóváhagyott kezelés szükséges, az újrafuttatás nem írja felül. A fájl érzékeny adatokat tartalmaz, Git-ignorált, hozzáférését korlátozni kell. A jegyzék és a hash önmagában nem igazolja a teljes tartalom épségét: az első stagingpróba előtt a teljes izolált helyi PostgreSQL 17-es restore és soronkénti forrásösszehasonlítás szükséges. A Supabase-kompatibilitást külön a második stagingpróba igazolja; az archívum nem tartalmaz cluster-szintű szerepköröket.
2. Kérjünk külön jóváhagyást a célprojektre, szerepkörökre, Data API-beállításokra, migrációs ablakra és rollbackra. Ellenőrizzük közvetlenül a projektazonosítót, szerververziót, `current_database()` értéket, cél-séma összes objektumát és a migrációs szerepkör jogait. Ha a `public` már nem üres, **állj**.
3. `pg_restore --list` és `pg_restore --file=-` segítségével vizsgáljuk meg a teljes létrehozandó SQL-t. A tényleges PostgreSQL 17-es sémadump **`CREATE SCHEMA public`** utasítást tartalmaz, de a Supabase-en a `public` már létezik. A TOC-listából csak a `SCHEMA - public` bejegyzést kell kihagyni; a sémát, annak tulajdonosát és ACL-jeit nem szabad újralétrehozni, felülírni vagy törölni. Ne hagyjunk ki táblákat, függvényeket, szekvenciákat vagy nézeteket.
4. A TOC módosításához használható egy ellenőrzött, nem repóba mentett lista. A következő példa csak a pontos, egyetlen sémabejegyzést kommenteli ki; sikertelen ellenőrzéskor megáll:

   ```powershell
   $env:SPC_ARCHIVE = $archive
   $env:SPC_TOC = Join-Path $env:TEMP 'spc_pg17_restore.toc'
   @'
   import os, pathlib, re, subprocess
   restore = r'C:\Program Files\PostgreSQL\17\bin\pg_restore.exe'
   archive = os.environ['SPC_ARCHIVE']
   out = pathlib.Path(os.environ['SPC_TOC'])
   result = subprocess.run([restore, '--list', archive], check=True,
                           capture_output=True, text=True, encoding='utf-8')
   lines = result.stdout.splitlines()
   matches = [i for i, line in enumerate(lines)
              if re.match(r'^\d+; \d+ \d+ SCHEMA - public(?:\s|$)', line)]
   if len(matches) != 1:
       raise SystemExit('A public SCHEMA TOC-bejegyzés nem pontosan egy.')
   lines[matches[0]] = '; ' + lines[matches[0]]
   with out.open('x', encoding='utf-8', newline='\n') as f:
       f.write('\n'.join(lines) + '\n')
   '@ | & '.\.venv\Scripts\python.exe' -
   if ($LASTEXITCODE -ne 0) { throw 'A TOC előkészítése sikertelen.' }
   ```

   A TOC pontos tartalmát és az archivált SQL-t embernek kell felülvizsgálnia. A `pg_restore` forrásból származó SQL-t és függvényeket hajt végre, ezért csak megbízható, ellenőrzött archívum használható.

### Staging és végrehajtási minta

A mentés, helyi restore-összehasonlítás, a [rollback előfeltételeinek](#rollback-eljárás) teljesítése és stagingindítási engedély után az alábbi négy, egymást követő szakaszt kell végrehajtani. Ezek mind külön jóváhagyott jövőbeli műveletek:

1. **Első izolált stagingpróba:** azonosítsuk az elkülönített staging projektet, verziót, céladatbázist és hálózati védelmet. Éles adat betöltése nélkül, szükség esetén külön jóváhagyott nem érzékeny próbobjektumokkal/adatokkal vizsgáljuk a migrációs bejelentkezést és `SET ROLE`-t, a tényleges owner jogait és default ACL-jeit, az RLS-t, a Data API/exposed schemas állapotát, a TLS-kapcsolatot és a nézettulajdonos/security-invoker viselkedését. Dokumentáljuk a tényleges jogokat, kockázatokat és hibákat; ez nem igényli az első próba utáni hardening előzetes sikerét. Nem igazolt izoláció vagy érzékeny adatok kitettsége esetén álljunk meg.
2. **Hardening:** az első próba jegyzőkönyve alapján, külön jóváhagyással tervezzük meg és hajtsuk végre a szükséges role-, default ACL-, Data API-, hálózati és TLS-korrekciókat a staging célon; az alkalmazásobjektumok RLS/ACL hardeningjét a második próba restore-tranzakciójában alkalmazzuk. Ellenőrizzük a korrekciókat és hatásukat, mielőtt teljes alkalmazásadat kerülne a célra. Sikertelen vagy nem igazolt védelem esetén nincs második teljes próba.
3. **Második stagingpróba:** a hardening után egy külön jóváhagyott, azonos beállítású, üres és izolált staging célon végezzük el az ellenőrzött archívum teljes migrációját és a restore-tranzakción belüli alkalmazásobjektum-hardeninget. Ha a második cél eltér az elsőtől, a szükséges role-okat, default ACL-eket és védelmet azon is előzetesen alkalmazni és ellenőrizni kell. Az első próba objektumait nem töröljük automatikusan. Futtassuk a teljes adat-, baseline-, view security-, Data API-, role- és dashboard-validációt az átvételi kritériumok szerint.
4. **Staging GO:** kizárólag a második teljes próba és valamennyi adat-, baseline-, jogosultsági, TLS-, nézet- és dashboard-ellenőrzés sikeres eredménye, valamint tulajdonosi jóváhagyás után adható meg. Bármely eltérés vagy nem bizonyított feltétel **NO-GO**. Az éles cutoverhez továbbra is külön frissességi ellenőrzés és külön végső GO szükséges.

A staging célhoz a Supabase Connect képernyőről származó `PGHOST`, `PGPORT`, `PGDATABASE=postgres`, `PGUSER`, valamint biztonságos jelszó- és TLS-konfiguráció szükséges. A jelszó nem lehet a parancsban. Külön ellenőrizzük, hogy valóban a jó projektbe csatlakoztunk.

A jóváhagyott migráció során a `--no-owner --no-acl` a helyi tulajdonosi/ACL-beállítások visszaállítását kerüli el: az új objektumok ownerje a restore SQL létrehozáskor aktuális `current_user` szerepköre, és ennek default ACL-je érvényes. Nem törli a cél alapértelmezett grantjeit. A következő csak SQL-t generál, nem csatlakozik a célhoz:

```powershell
$restoreSql = Join-Path $env:TEMP 'spc_pg17_restore.sql'
if (-not $env:SPC_TOC -or -not $env:SPC_ARCHIVE) {
  throw 'Hiányzik a TOC vagy az archívum útvonala.'
}
$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = 'C:\Program Files\PostgreSQL\17\bin\pg_restore.exe'
$startInfo.Arguments = '--use-list="{0}" --no-owner --no-acl --exit-on-error "{1}"' -f $env:SPC_TOC, $env:SPC_ARCHIVE
$startInfo.UseShellExecute = $false
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$process = $null
$stream = $null
try {
  $stream = [System.IO.File]::Open(
    $restoreSql, [System.IO.FileMode]::CreateNew,
    [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
  $process = [System.Diagnostics.Process]::Start($startInfo)
  $stderrTask = $process.StandardError.ReadToEndAsync()
  $process.StandardOutput.BaseStream.CopyTo($stream)
  $process.WaitForExit()
  $stderr = $stderrTask.GetAwaiter().GetResult()
  if ($stderr) { [Console]::Error.WriteLine($stderr) }
  if ($process.ExitCode -ne 0) { throw "A restore SQL előállítása sikertelen: $($process.ExitCode)." }
}
catch {
  if ($process -and -not $process.HasExited) {
    $process.Kill()
    $process.WaitForExit()
  }
  throw
}
finally {
  if ($process) { $process.Dispose() }
  if ($stream) { $stream.Dispose() }
}
```

A `CreateNew` meglévő fájlnál megállítja a folyamatot, mielőtt a `pg_restore` elindulna. Sikertelen vagy megszakított generálás részleges fájlja nem használható; kezeléséhez külön jóváhagyás kell, az újrafuttatás nem írja felül. Az SQL, a TOC és az esetleges napló is érzékeny; hozzáférésük és megőrzésük legyen korlátozott. A felülvizsgált `restore.sql`-t és az előre kipróbált, kizárólag alkalmazásobjektumokra célzott RLS/ACL SQL-t egy felülvizsgált psql wrapperben kell egymás után `\i`-vel meghívni, majd `psql --single-transaction --set=ON_ERROR_STOP=1 --file=<wrapper>` segítségével végrehajtani. A wrapper **ne** tartalmazzon saját `BEGIN`/`COMMIT`-ot, `\connect`-et, jelszót vagy `--clean`/`--create` műveletet. A migrációs szerepkör, RLS-policy-k, függvény-EXECUTE revoke-ok és role-grant-ek pontos SQL-jét stagingen tesztelni és külön jóváhagyni kell, mielőtt ez a parancs éles célra használható. A Data API és a hálózati védelem maradjon zárva a tranzakció és az ellenőrzés alatt.

Hibánál `ON_ERROR_STOP` mellett a tranzakció visszagördül; a cél állapotát külön ellenőrizni kell. A `setval` szekvenciaművelet általában nem tranzakciós, ezért **meglévő szekvenciát tilos célozni**: az üres séma és az új, a visszagörgetéssel eltűnő szekvenciák kötelező előfeltételek. Ne használjunk párhuzamos restore-t a single transaction mellett.

## Data migration

1. A `pg_dump` egy konzisztens pillanatképet készít; a `pg_restore` az archívum `COPY` adatblokkjait használja. Az identity értékek így megőrizhetők. Kézi `INSERT` esetén `GENERATED ALWAYS` miatt `OVERRIDING SYSTEM VALUE` szükséges, de a javasolt eljárás nem kézi INSERT.
2. A fenti táblasorrend mutatja a függőségeket. Archívumos restore esetén ne indítsunk külön, másodlagos táblánkénti betöltést: a TOC szerinti teljes adatbetöltés az irányadó, és megelőzi a post-data FK-k, indexek és triggerek végső létrehozását.
3. A `spc_baseline` minden sora és összes oszlopa kerüljön át változatlanul; ne futtassunk új baseline-fittinget, jóváhagyást vagy aktiválást. Ha később több verzió lesz, az önhivatkozásokra és a trigger-időzítésre külön próbát kell végezni.
4. A 11 `SEQUENCE SET` elemet tartsuk meg. Ellenőrizzük minden sequence `last_value` és `is_called` értékét, valamint identity-tulajdonlását és a következő érték ütközésmentességét **anélkül, hogy `nextval()`-t hívnánk**.
5. Az adatbetöltés és a struktúra helyreállítása után ne írjunk át értékeket javításként. Eltérés esetén álljunk meg; őrizzük meg a naplót, és külön jóváhagyással határozzuk meg a teendőt.

## Validation and acceptance criteria

Az ellenőrzések csak olvasó lekérdezések; a staging és a cél forrásával azonos pillanatképet hasonlítsunk össze. A forrás és cél `TimeZone`, `DateStyle`, client encoding és numerikus megjelenítés legyen egységes; `timestamptz` értékeket UTC-ben vagy típusos értékként hasonlítsunk.

1. **Darabszám és tartalom:** mind a 12 tábla darabszáma és teljes tartalma egyezzen a migrációs archívumhoz tartozó PG17 forrásállapottal. A régi darabszámok csak történeti referenciák; eltérésük önmagában nem hiba, ha a frissességi kapu sikeres. Az izolált helyi restore-t még a forrásfagyasztás alatt közvetlenül vessük össze a PG17 forrással; a staging célját ehhez a bizonyítottan egyező, változatlanul megőrzött izolált restore-hoz hasonlítsuk. A DBA a referencia megőrzéséhez zárja ki az írásokat, DDL-t, sequence-mozgásokat és háttérfolyamatokat, és dokumentálja az adatbázis azonosítóját és a védelem folytonosságát a staging-összehasonlítás végéig; read-only kapcsolat önmagában nem zárja ki mások írásait. Azonos oszlopsorrendben, stabil PK-sorrendben teljes soronkénti összehasonlítás készüljön, beleértve a `NULL`-okat és az identity értékeket; a kapcsolótábla rendezése `(measurement_id, robot_id)`. A hash csak kiegészítő sértetlenségvizsgálat, nem helyettesíti a teljes sorösszevetést. Ha a referenciaként szolgáló restore változatlansága nem igazolt vagy már nem érhető el, az egyezés nem igazolt: **FAIL**, és külön jóváhagyással friss ellenőrzés szükséges. A fájlok/sorok ne kerüljenek nyilvános naplóba.
2. **Séma:** egyezzen a 12 PK, 16 FK, 9 UNIQUE, 20 CHECK, 66 `NOT NULL`, 39 index és azok definíciója, oszlopsorrendje, feltétele, érvényessége. A Supabase platformobjektumokat ne számoljuk az alkalmazás leltárába. Nem validált FK/CHECK nem maradhat. Ellenőrizzük a 11 identity és sequence értékét és tulajdonlását.
3. **Függvények és triggerek:** mindkét függvény és trigger definíciója, engedélyezett állapota, a constraint trigger deferrálhatósága és kezdeti módja egyezzen. A tesztadatbázisban végzett külön jóváhagyott negatív tesztekkel ellenőrizhető az immutabilitás és a supersession; a production baseline-t ne módosítsuk teszt céljából.
4. **Mind a 13 nézet:** hasonlítsuk össze a `pg_get_viewdef` definícióját, oszlopaikat és függőségeiket. Futtassunk mindkét oldalon azonos szerepkör-/RLS-feltételekkel teljes sorhalmaz-összehasonlítást, vagy determinisztikus, a duplikátumokat is megőrző hash-t minden nézetre. A rendezési és típusformázási szabályokat előre rögzítsük; a hosszú SPC-lekérdezés és erőforrásigénye miatt stagingen állítsunk megfelelő időkorlátot.
5. **Baseline:** az egyetlen `ACTIVE` rekord legyen ID `1`, verzió `1`, BOOTH_01 / A-L1 / specifikáció `1`. A teljes `SELECT * FROM public.spc_baseline ORDER BY baseline_id` eredményt típusosan, minden mezőre, `NULL`-érzékenyen vessük össze a forrással és a fenti referenciával. Jóváhagyó, időbélyeg, fitting window, effektív időszak, counts és mind a hat numerikus érték pontosan egyezzen.
6. **Dashboard:** futtassuk az eredeti két lekérdezést és a Streamlit AppTestet a dedikált role-lal. A helyi referencián a Quality dashboard 167 400 mérést, 9 300 kabint és 1 881 specifikáción kívüli mérést mutatott; az SPC-scope 4 650 mérést, 4 200 lefedettet, 450 nem értékeltet és 267 jelzést. Ezek snapshotfüggő ellenőrző eredmények, nem új limitek. Hasonlítsuk össze a mérésazonosítókat, Rule 1–4 flag-eket, MR-t, baseline-időhatárokat, tárolt limiteket, diagramokat és a szűrők működését. Manuális böngészős ellenőrzés is szükséges.
7. **Biztonság:** a `spc_dashboard_reader` tudja olvasni a hat objektumot, de ne legyen írási, DDL, szekvencia-, role- vagy RLS-bypass joga; ellenőrizzük az örökölt és `PUBLIC` jogokat is. `anon` és `authenticated` a Data API-n és közvetlen szerepkörtesztben se érje el az alkalmazásobjektumokat. A nézetek tulajdonosi jogosultsága és az RLS együttes viselkedése külön tesztelendő. Negatív írási/DDL teszteket csak elkülönített, erre jóváhagyott stagingen végezzünk.
8. **Data API és hatobjektumos átvételi kapu:** `anon` és `authenticated` nem férhet hozzá **egyetlen** alkalmazásobjektumhoz sem a Data API-n: mind a 12 tábla, mind a 13 nézet, valamint az alkalmazás-függvények RPC-kitettsége vizsgálandó. A két triggerfüggvény nem feltétlenül hívható PostgREST RPC-ként; nem létező RPC-végpont önmagában nem bizonyítja az EXECUTE jogosultság hiányát. Ellenőrizzük külön a 11 szekvenciát, az összes táblaszintű és oszlopszintű jogot, függvény-EXECUTE-ot, `PUBLIC` és örökölt tagságokat is. `spc_dashboard_reader` tényleges bejelentkezéssel a pontosan szükséges két nézetet és négy táblát olvashassa, és a két tényleges dashboard-lekérdezés adjon teljes, helyes eredményt.
9. **Éles cutover előtti végső GO:** a második teljes stagingpróba utáni staging GO mellett a teljes adategyezés, a staging nézettulajdonosi RLS-teszt, az összes Data API-/SQL-jogteszt, TLS, kapcsolatszám, teljesítmény és a tulajdonosi felülvizsgálat sikeres, és a PostgreSQL 18/17 forrásfrissesség a cutoverkor továbbra is igazolt; a tulajdonos jóváhagyta az eredményt. Eltérés, hash-hiba, részleges restore, nem tisztázott migrációs role/default ACL vagy hozzáférés esetén nincs cutover.

### Data API ellenőrzése stagingen

1. Azonosítsuk a staging projektet, a Data API tényleges be-/kikapcsolt állapotát és az exposed schemas listát. A `public` kivétele vagy a teljes API kikapcsolása esetén ellenőrizzük a tényleges konfigurációt és a lezárás hatását, nem csak egy sikertelen hálózati kérést. Ha a `public` továbbra is kint van, minden objektumra a célzott grant/RLS-védelem és a 2. pontban leírt teszt szükséges.
2. Teszteljünk külön `anon` és érvényes, staging `authenticated` identitással a 12 tábla és 13 nézet REST-útvonalán, továbbá az alkalmazásfüggvények elérhető RPC-felületén; ne kerüljön token vagy válaszadat a jelentésbe. A végeredmény mindenhol objektum-hozzáférés megtagadása vagy megbízhatóan nem exponált útvonal legyen. Egy `200` üres sorhalmaz nem fogadható el: az SQL-szintű `SELECT` jogosultság önmagában is nem kívánt hozzáférés. A `401` hibás token, timeout, DNS-hiba, rossz projekt vagy általános szolgáltatáskimaradás nem bizonyíték. Hitelesítsük a szerepköröket és az API elérhetőségét olyan, külön jóváhagyott staging kontrollal, amely nem tesz ki alkalmazásadatot. Ha a Data API ki van kapcsolva, a konfigurációs bizonyíték mellett ellenőrizni kell, hogy a szolgáltatás tényleg nem érhető el, és nem csak átmeneti hiba történt.
3. Ellenőrizzük külön az SQL-katalógusban és role-jogokban az összes tábla, nézet, szekvencia és függvény hozzáférését, beleértve a `PUBLIC`/oszlopszintű és örökölt grantokat. A Data API HTTP-teszt és a közvetlen SQL ACL-teszt kiegészíti egymást; egyik sem helyettesíti a másikat. A reader szerepkört kizárólag közvetlen PostgreSQL-kapcsolaton teszteljük, ne tegyük API-role tagjává.

### Olvasási ellenőrző lekérdezések

Az alábbiakat a bizonyítottan változatlan izolált PG17 restore-referencián, majd a jóváhagyott Supabase-célon kell futtatni. Minden lépés előtt ellenőrizendő a tényleges projekt és kapcsolat; a két eredmény tárolása és összehasonlítása biztonságos helyen történjen. A régi tesztadatbázis vagy a már nem védett PG17-forrás önmagában nem helyettesíti ezt a referenciát.

```sql
SELECT current_database(), current_setting('server_version'),
       current_setting('TimeZone'), current_user;

SELECT c.relname AS table_name,
       (xpath('/row/count/text()', query_to_xml(
         format('SELECT count(*) AS count FROM %I.%I', n.nspname, c.relname),
         false, true, '')))[1]::text::bigint AS row_count
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
ORDER BY c.relname;

SELECT c.conrelid::regclass AS table_name, c.conname, c.contype,
       c.convalidated, pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace
WHERE n.nspname = 'public' AND c.contype IN ('p', 'f', 'u', 'c')
ORDER BY c.conrelid::regclass::text, c.conname;

SELECT tablename, indexname, indexdef
FROM pg_indexes WHERE schemaname = 'public'
ORDER BY tablename, indexname;

SELECT c.relname AS view_name, pg_get_viewdef(c.oid, true) AS definition
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'v'
ORDER BY c.relname;

SELECT c.relname AS table_name, t.tgname, t.tgenabled,
       t.tgdeferrable, t.tginitdeferred, pg_get_triggerdef(t.oid) AS definition
FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND NOT t.tgisinternal
ORDER BY c.relname, t.tgname;

SELECT p.proname, pg_get_functiondef(p.oid) AS definition
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' ORDER BY p.proname;

SELECT * FROM public.spc_baseline ORDER BY baseline_id;
```

## Risks and rollback strategy

- **Legfontosabb kockázat:** a Supabase `public` default grantjei és a nézetek tulajdonosi RLS-megkerülése adatot tehetnek elérhetővé. Data API-állapot és schema exposure jelenleg nincs igazolva; ezek lezárása/felülvizsgálata blokkolja a migrációt.
- **Pillanatkép-elavulás:** a PostgreSQL 17 másolat nem automatikusan követi a PostgreSQL 18 hiteles forrást. Az eltérést cutover előtt meg kell szüntetni egy jóváhagyott új snapshot-folyamattal.
- **Verzió/platform:** a helyi 17.12 siker nem bizonyítja a Supabase 17.11, nem-superuser `postgres`, pooler, extension, ACL vagy session-beállítások kompatibilitását. Elsőként elkülönített stagingen próbáljuk.
- **Üzemeltetés:** a Cloud kapcsolat, TLS-tanúsítvány, direkt IPv6/IPv4 vagy session pooler, poolméret, titkok és lekérdezési idő még ellenőrizendő. A jelenlegi dashboard hibakimeneteit is át kell tekinteni a titkok véletlen megjelenése ellen.
- **Tilos automatikus takarítás:** nem használunk `DROP SCHEMA public`, `pg_restore --clean`, `--create`, Supabase projekt-reset vagy platformobjektumokat érintő törlést. Bármilyen céloldali törlés vagy helyreállítás előtt külön jóváhagyás és objektumszintű terv szükséges.

### Rollback eljárás

Ez a szakasz jövőbeli, külön jóváhagyott műveleteket ír le; **sem backupot, sem rollbacket nem hajtottunk végre**. A staging és az éles cél külön projektként és külön jegyzőkönyvvel kezelendő. A PostgreSQL 18-as forrást és az ACTIVE baseline-t a rollback során sem módosítjuk, és a limitértékeket nem számítjuk újra.

#### Előfeltételek és döntési jogkör

Az első stagingváltoztatás, illetve külön az éles migráció előtt a tulajdonos jelölje ki név szerint az indításra és jóváhagyásra jogosult döntéshozót, a PostgreSQL-jogosultságokat kezelő DBA-t, a Supabase-projekt adminisztrátorát, a dashboard üzemeltetőjét és helyetteseiket. Rögzítsük az elérhetőségüket a védett üzemeltetési jegyzőkönyvben. A tényleges szerepköröket, jogosultságokat és hozzáférést **még nem igazoltuk**; megfelelő felelős vagy hozzáférés hiányában az adott célra nincs indulási engedély.

Változtatás előtt az adott célról védett helyen készüljön időbélyegzett, felülvizsgált **kiinduló állapot és változásnapló**:

1. Azonosítsuk a projektet, adatbázist, szervert, verziót, érintett alkalmazásobjektumokat és a rollback hatókörét. Rögzítsük az előzetes táblalistát, rekorddarabszámokat, teljes baseline-állapotot, objektumdefiníciókat, tulajdonosokat, sequence-állapotokat és az esetleges, már meglévő adatokat. Üres cél esetén ezt is bizonyítsuk; ne feltételezzünk ott korábbi baseline-t.
2. Katalógus alapján rögzítsük a módosítandó role-ok létezését, attribútumait, tagságait, grantorait és grant optionjeit; a `PUBLIC` és örökölt jogokat, az objektum- és oszlopszintű ACL-eket, valamint az érintett létrehozó szerepkörök globális és sémaspecifikus default ACL-jeit. A változásnapló minden tényleges műveletet, hatókört és az előző értéket külön azonosítsa; más alkalmazások és platform-role-ok jogosultságait ne soroljuk automatikusan visszavonandónak.
3. Rögzítsük az érintett táblák RLS-/`FORCE` jelzőit és policy-definícióit, a nézetek tulajdonosát és security-beállításait, továbbá a tényleges Data API-, exposed schemas-, hálózati és TLS-beállításokat. A Supabase Dashboardon vagy más, akkor hivatalosan támogatott felületen ellenőrizzük az értékek visszaállításának módját és az adminisztrátor hozzáférését. **Nem feltételezünk** automatikus API-t, mentést vagy jogosultságot e beállításokhoz.
4. Rögzítsük a dashboard korábbi adatforrásának azonosítóját, hálózati útvonalát, TLS-beállításait és a titokkezelőben tárolt konfigurációverzióra mutató hivatkozást. Jelszó, token vagy más titok ne kerüljön a jegyzőkönyvbe, SQL-be, parancsba vagy Gitbe. Ellenőrizzük, hogy a kijelölt üzemeltető szükség esetén el tudja érni és újra be tudja állítani a korábbi konfigurációt.
5. A cél backup/PITR rendelkezésre állása, az elérhető visszaállítási időpont, hatókör, megőrzési idő, helyreállítási eljárás és végrehajtói hozzáférés **nyitott előfeltétel**. Csak az adott projektre bizonyítottan elérhető és elkülönített próbán ellenőrzött mentés vagy PITR használható; a helyi PostgreSQL 18-as dump nem a Supabase teljes projektjének backupja. Jóváhagyott, kipróbált alternatíva vagy bizonyított visszaállítási út nélkül a cél módosítása **NO-GO**. Az elkülönített staging elhagyása mint alternatíva csak akkor fogadható el, ha a tulajdonos ezt előre jóváhagyta, az izoláció igazolt, és a próbák nem érintenek megosztott platformbeállításokat; ez nem helyettesíti az éles cél rollbackjét.
6. A kiinduló állapotból és a tervezett változásokból a DBA még az adott cél módosítása előtt készítsen és hagyasson jóvá objektumonkénti, sorrendhelyes `GRANT`/`REVOKE`, role-, policy- és `ALTER DEFAULT PRIVILEGES` visszaállítási műveletsort, a projektadminisztrátor pedig a ténylegesen támogatott platformfelület lépéseit. Az eljárást és az alkalmazható jogosultságokat elkülönített, nem érzékeny próbán ellenőrizni kell; a műveletsor titkot nem tartalmazhat. Ha a pontos visszaállítási műveletsor vagy a kipróbálható hozzáférés nem áll rendelkezésre, az adott változtatás **NO-GO**. Az első stagingpróba nem követeli meg a későbbi hardening előzetes végrehajtását.

**Rollback szükséges**, ha a jóváhagyott migráció sikertelen, részleges vagy nem konzisztens állapotban állt meg; ha baseline-, adat-, séma- vagy jogosultságeltérés keletkezett; ha az alkalmazásadat nem kívánt hozzáférése vagy annak közvetlen veszélye merült fel; vagy ha az átvételi kritériumok hibája miatt nem tartható fenn a cél biztonságos használata. Egy pusztán előfeltételként hiányzó bizonyíték esetén először **állj / NO-GO**: ha változtatás még nem történt, nincs mit visszagörgetni.

A kijelölt döntéshozó indítja el és hagyja jóvá a rollback hatókörét; a kijelölt DBA, projektadminisztrátor és dashboard-üzemeltető kizárólag saját, igazolt jogosultságával hajtja végre a rá eső lépéseket. Biztonsági incidensnél az arra felhatalmazott ügyeletes azonnal kezdeményezheti a jóváhagyott hozzáférés-korlátozást és értesíti a döntéshozót. Ismeretlen jogosultság vagy nem várt hatás esetén álljunk meg és kérjünk külön döntést.

#### Végrehajtási sorrend

1. **Leállítás és bizonyíték:** a dashboard-üzemeltető állítsa le vagy tiltsa a dashboard Supabase-kapcsolatát a jóváhagyott üzemeltetési felületen, és a projektadminisztrátor korlátozza az érintett hozzáférést a rendelkezésre álló, jóváhagyott módszerrel. Azonosítsuk a célt és az esemény időpontját; őrizzük meg a naplót, változásnaplót és a szükséges céloldali adatokat védett helyen. Ha a célon a migráció óta új adat keletkezett, a döntéshozó a helyreállítás előtt hagyja jóvá annak megőrzését és az adatvesztés kezelését. Ne írjuk felül a PostgreSQL 18-as forrást.
2. **Adatbázis-állapot:** ha az alkalmazás-restore és hardening egyetlen tranzakciója még nem commitált és a kapcsolat hibánál visszagörgetett, a DBA ellenőrizze a tényleges tranzakció végét és a kiinduló objektum-/ACL-állapotot. Ez **nem** vonja vissza a korábban külön commitált role-, default ACL- vagy platformváltozásokat; azokat a következő lépések kezelik. Ha már commitált adat/séma sérült, nem teljes vagy a kiinduló állapot másként nem állítható helyre, a teljes projekt-/adatbázis-restore szükségességéről a döntéshozó a platformfüggőségek, a célon keletkezett új adat és a helyreállítás hatókörének felmérése után döntsön. Üres staging cél hibája esetén alternatíva lehet az előre jóváhagyott izolált staging elhagyása, nem automatikus törlése.
3. **Teljes restore, ha jóváhagyott és szükséges:** a DBA és a Supabase-projekt adminisztrátora ellenőrizze újra a projektazonosítót, a bizonyított backup vagy PITR időpontját, hatókörét és az aktuális jogosultságot. A kijelölt, megfelelő restore- vagy projektadmin-joggal ténylegesen rendelkező végrehajtó kizárólag az adott projektben dokumentált és előzetesen kipróbált szolgáltatói restore-eljárást indítsa a jóváhagyott visszaállítási pontra; jegyezze fel az eredményt és az esetleges platform-/auth-hatást. Ha a PITR nem elérhető, csak a célra alkalmas, igazoltan visszaállítható backup és jóváhagyott restore-módszer használható. Ha egyik sem áll rendelkezésre, nincs teljes restore: a cél maradjon izolált, az eredeti forrás maradjon érintetlen, és külön helyreállítási tervről kell dönteni. A dokumentum nem állítja, hogy a szükséges jogosultság vagy mentés már létezik.
4. **PostgreSQL ACL és role-ok:** a DBA az 1–3. lépések után hasonlítsa össze a tényleges célállapotot az adott cél kiinduló katalógusfelvételével és a változásnaplóval. Csak a migráció által ténylegesen hozzáadott vagy elvett, azonosított objektum- és oszlopszintű `GRANT`/`REVOKE`, role-attribútum, role-tagság és grant option változásokat fordítsa vissza, objektumonként és a megfelelő grantor/jogosultság ellenőrzésével. Az érintett creator role globális és sémaspecifikus default ACL-jeit külön állítsa a kiinduló értékre; az `ALTER DEFAULT PRIVILEGES` nem javítja a már létező objektumokat. A teljes restore után se feltételezzük, hogy cluster-szintű role-ok vagy default ACL-ek helyreálltak: ezeket is külön ellenőrizzük.

   Kizárólag a migrációhoz létrehozott és a visszaállás után már nem szükséges role távolítható el külön jóváhagyással. A DBA előbb vonja vissza annak a változásnaplóban azonosított hozzáféréseit és tagságait, ellenőrizze tulajdonolt és egyéb függő objektumait **minden érintett adatbázisban**, majd csak jóváhagyott objektumszintű terv szerint rendezze a függőségeket. Meglévő vagy más szolgáltatás által használt role-t nem szabad törölni. A kijelölt dashboard-role új kapcsolatainak tiltása és aktív kapcsolatai azonosítása után a kizárólag hozzá tartozó, egyedileg ellenőrzött kapcsolatok megszüntetése csak külön jóváhagyással és megfelelő jogosultsággal végezhető. Ha bármely függőség vagy jogosultság nem tisztázott, a role maradjon letiltva, és a DBA álljon meg; ne használjunk általános `DROP OWNED` vagy tömeges kapcsolatmegszüntetést. `DROP ROLE` csak az 5. pontban szereplő, role-t érintő policy- és tulajdonosi visszaállítás, minden függőség és aktív használat megszűnése, valamint külön jóváhagyás után engedélyezett.
5. **Supabase és view security:** a projektadminisztrátor a védett kiinduló konfiguráció és változásnapló alapján, a ténylegesen támogatott felületen állítsa vissza a jóváhagyott Data API-, exposed schemas-, hálózati és TLS-értékeket; a DBA állítsa vissza az érintett alkalmazástáblák RLS-/`FORCE` állapotát és policy-it, valamint a nézetek eredeti tulajdonát és security-beállításait. Minden módosítást külön ellenőrizzünk; a nem érintett platformobjektumokat hagyjuk változatlanul. Ha egy beállításhoz nincs igazolt visszaállítási mechanizmus vagy adminhozzáférés, nincs automatikus helyreállítás: a cél maradjon zárt, az eltérést jegyezzük fel, és a döntéshozó külön helyreállításról határozzon. Korábban szélesebb API-hozzáférést nem szabad visszakapcsolni, amíg érzékeny alkalmazásadat maradna kitéve; ilyen ütközésnél maradjon a biztonságos lezárás és **NO-GO**.
6. **Dashboard visszaállítása:** a kijelölt üzemeltető a védett konfigurációreferenciából állítsa vissza a korábbi adatforrást és TLS-/hitelesítési konfigurációt a szolgáltatás biztonságos secrets felületén. A hitelesítő adatot ne írja ki. A hozzáférést csak akkor indítsa újra, ha a korábbi PostgreSQL 18-as adatforrás az adott futtatókörnyezetből ténylegesen elérhető, a hitelesítés sikeres, és a döntéshozó jóváhagyta. Ha például a cloud környezet nem éri el a helyi PostgreSQL-t, ne feltételezzünk működő visszaútvonalat: a dashboard maradjon leállítva, és külön jóváhagyott hozzáférési vagy üzemeltetési megoldás szükséges.

#### Rollback utáni ellenőrzés és lezárás

1. A DBA olvasó lekérdezésekkel hasonlítsa össze a cél tábláit, darabszámait, teljes tartalmát, objektum- és sequence-állapotát a cél kiinduló állapotával, illetve a jóváhagyott restore-ponttal. Ha a cél eredetileg üres volt, a célon az alkalmazásobjektumok hiányát kell igazolni; nem követelhető ott korábbi baseline.
2. A PostgreSQL 18-as forráson, illetve ahol a jóváhagyott visszaállítási pont ezt tartalmazza, típusosan és `NULL`-érzékenyen ellenőrizzük a baseline ID `1`, version `1`, `ACTIVE` állapotát, teljes metaadatait, jóváhagyóját és időpontját, valamint a `center_line`, `sigma`, `i_lcl`, `i_ucl`, `mr_center`, `mr_ucl` pontos értékét a fenti referencia szerint. A cél korábbi eltérő baseline-állapotát a saját kiinduló felvételével kell összevetni, nem szabad a forrás értékével felülírni.
3. A DBA és projektadminisztrátor ellenőrizze a tényleges objektum-, oszlop-, default ACL- és role-tagságokat, az RLS/policy és nézettulajdon/security állapotát, valamint a Data API tényleges kitettségét a kiinduló állapot és a jóváhagyott biztonságos eltérések szerint. Érzékeny adat véletlen kitettsége, hiányzó jog vagy ellenőrizetlen platformbeállítás esetén nincs lezárás.
4. A dashboard-üzemeltető ellenőrizze a korábbi forrásazonosságot, a biztonságos kapcsolatot, a szükséges lekérdezéseket és a tényleges dashboard-működést. Ha a visszaút nem érhető el, a dashboard leállítva marad, és a rollback nem tekinthető teljesnek.
5. A döntéshozó hagyja jóvá a jegyzőkönyvet: visszaállítási pont, érintett időszak, megtartott céloldali új adatok, ismert adatvesztés vagy eltérés, nyitott hozzáférési/beállítási problémák és felelősök. **Sikeres rollback** csak akkor mondható ki, ha a jóváhagyott célállapot és biztonság igazolt, a baseline és a dashboard ellenőrzése sikeres, az esetleges adatvesztést dokumentálták és elfogadták, és nincs nyitott blokkoló hiba. Ennek hiányában a rendszer maradjon biztonságos, korlátozott állapotban; további helyreállításhoz külön döntés szükséges.

### Nyitott döntések

1. A Supabase projekt tényleges neve/tulajdonosa megfelel-e az SPC-projektnek, és ki hagyja jóvá a célazonosítást?
2. Kikapcsolható-e a Data API vagy eltávolítható-e a `public` az exposed schemas listából más szolgáltatások károsítása nélkül?
3. Mely bejelentkező és tényleges `current_user` hozza létre az objektumokat, támogatja-e a Supabase a javasolt `NOLOGIN` owner és `SET ROLE` használatát, ki módosíthatja annak default ACL-jeit, és megengedett-e a `service_role` meglévő viselkedése?
4. Hol áll rendelkezésre azonos Supabase-verziójú staging és milyen adatvédelmi feltételekkel?
5. Milyen hálózati útvonal, CA, pooler, migrációs ablak, mentési/PITR és rollback eljárás használható?
6. Igazolható-e a PG18-forrás aktuális állapota és folyamatos fagyasztása, és rendelkezésre áll-e két külön, üres és izolált PG17-cél az új forráshoz és annak restore-próbájához?
7. Melyik előzetesen kipróbált PG18→PG17 restore-módszer használható, és elérhetők-e a szükséges verziójú eszközök, jogosultságok, tárhely és jóváhagyott időablak?
8. Rendelkezésre áll-e külön tesztkörnyezetben igazolt, teljes, típusos sor- és objektumösszehasonlító módszer, és biztosítható-e a restore-referencia változatlansága a staging végéig?
9. Az adott staging- és éles célra igazolt-e a rollback útja, a backup/PITR vagy megengedett alternatíva, az operátori hozzáférés és a dashboard korábbi adatforrásához vezető visszaút?

### Hivatkozások

- [Supabase: Data API biztonság és default privileges](https://supabase.com/docs/guides/api/securing-your-api)
- [Supabase: RLS és nézetek](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [Supabase: PostgreSQL-kapcsolattípusok](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [PostgreSQL 17: pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html)
- [PostgreSQL 17: CREATE VIEW és security_invoker](https://www.postgresql.org/docs/17/sql-createview.html)
- [PostgreSQL 17: row security](https://www.postgresql.org/docs/17/ddl-rowsecurity.html)
- [PostgreSQL 17: ALTER DEFAULT PRIVILEGES](https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html)

## Opcionális függelék: PostgreSQL ACL és RLS technikai részletek

Az itt leírt példák és magyarázatok tájékoztatóak; a fő folyamatban előírt biztonsági ellenőrzések kötelezőek.

### Szerepkörök, restore-tulajdon és RLS

| Szerepkör | Tervezett feladat és korlát |
|---|---|
| Migrációs bejelentkező | Csak a jóváhagyott restore-t és hardeninget hajtja végre. A szükséges `CONNECT`, a cél `public` sémán `USAGE`/`CREATE`, és a létrehozáshoz, `COPY`-hoz, FK-khoz, triggerekhez, szekvenciákhoz és jogosultságbeállításhoz szükséges jogok legyenek igazolva stagingen. Az adminisztrátori role-létrehozás és más platformbeállítás külön művelet; ne használjuk a migrációs bejelentkezést dashboardhoz. |
| Objektumtulajdonos | Javasolt külön, alkalmazásspecifikus `NOLOGIN`, `NOSUPERUSER`, `NOBYPASSRLS` owner role. Tulajdonolja az alkalmazástáblákat, -nézeteket, identity-szekvenciákat és függvényeket; e jogkör az objektumok módosításával és törlésével is jár, ezért a dashboard nem lehet tagja. Nincs szüksége globális `BYPASSRLS`, `CREATEROLE`, `CREATEDB` vagy superuser jogra. |
| `spc_dashboard_reader` | Külön `LOGIN`, nem tulajdonos, nem tagja a migráló/owner role-nak; `NOBYPASSRLS`, csak a felsorolt hat objektumra `SELECT` és a kapcsolathoz szükséges `CONNECT`/schema `USAGE`. Nincs írási, DDL, szekvencia- vagy tagságkezelési joga. |

A `pg_restore --no-owner` nem állítja vissza a dump eredeti tulajdonosát: az új táblák, nézetek és más objektumok tulajdonosa a létrehozó utasítások futtatásakor érvényes **`current_user`**, azaz alapesetben a restore-bejelentkezés szerepköre lesz. Ha egy jogosult bejelentkezés a restore előtt `SET ROLE`-lal a jóváhagyott owner role-ra vált, a létrehozó és tulajdonos az a role; ellenőrizzük a tényleges `current_user`-t a wrapperben, és stagingen igazoljuk a `SET ROLE`, schema `CREATE` és a teljes restore megengedettségét. A `NOLOGIN` owner közvetlenül nem tud csatlakozni. A tulajdonos későbbi módosítása külön DDL, nem következik a `--no-owner` használatából.

A választott alapértelmezett nézetmodellnél a `v_measurement_enriched` és `v_spc_rule_results` **nem `security_invoker`** nézet. A nézeten keresztüli alaptábla-hozzáférést és az RLS-t a nézet tulajdonosának jogosultságai határozzák meg; a nézetlánc minden tagját külön kell ellenőrizni. A javasolt, azonos alkalmazás-owner tulajdonolja a nézetek **valamennyi** alaptábláját is, amelyeken RLS engedélyezett, de `FORCE ROW LEVEL SECURITY` nincs bekapcsolva: tulajdonosként így a teljes szükséges sorhalmazt látja, globális `BYPASSRLS` nélkül. Ha más a táblatulajdonos, a nézettulajdonosnak az alaptáblákra `SELECT` és a megfelelő teljes sorhalmazt engedő RLS-policy szükséges. `FORCE ROW LEVEL SECURITY` esetén az adott táblatulajdonos is policy alá kerül, kivéve superuser/`BYPASSRLS`; e terv nem ad ilyen tág jogot. A `security_invoker=true` nézetlánc esetén más jogosultsági és policy-modell szükséges, ezt külön kell tervezni és tesztelni.

A tulajdonos RLS-megkerülése kizárólag a nézet olvasására jogosult szerepkörnek ad hozzáférést, de nem biztonsági akadály, ha véletlenül `anon`, `authenticated` vagy `PUBLIC` nézetjog keletkezik. A nézet nem `SECURITY DEFINER` függvény; a benne használt függvények jogosultsági szemantikáját külön kell kezelni. Ha a restore ténylegesen `postgres`-ként fut, az új objektumok tulajdonosa `postgres` lesz, amely a célon `BYPASSRLS`-es és jóval szélesebb jogosultságú; ezt ne tekintsük a dedikált owner modellel egyenértékűnek, és ne fogadjuk el automatikusan.

### Default ACL és létező objektumok külön kezelése

A 2026-11-13-i célellenőrzés megerősítette: mind a `postgres`, mind a `supabase_admin` `public`-beli default ACL-je az `anon`/`authenticated` szerepkörnek táblákra minden fenti jogot, szekvenciákra `SELECT`/`UPDATE`/`USAGE`, függvényekre `EXECUTE` jogot ad. A beépített globális default alapján mindkét role új függvényei `PUBLIC EXECUTE` jogot is kapnak. A két role bejegyzése külön kezelendő. Az MCP-lekérdezés `current_user` és `session_user` értéke `postgres` volt, ez azonban nem jelöli ki a migráció tényleges role-ját. Ha később `postgres` lesz a létrehozó, a fent ellenőrzött `postgres` default ACL alkalmazandó; más role vagy `SET ROLE` esetén az adott létrehozó aktuális ACL-jét külön kell vizsgálni. A tényleges migrációs `current_user`/owner **még nem ismert**: kiválasztása és vizsgálata kötelező blokkoló kapu.

Az új objektumok default ACL-jét a létrehozáskor aktuális `current_user` határozza meg, nem a bejelentkező más tagságainak default ACL-jei. A `pg_default_acl` üres eredménye nem jelent teljes tiltást: a PostgreSQL beépített globális alapértelmezései továbbra is érvényesek, többek között a függvények `PUBLIC EXECUTE` joga. A globális és sémaspecifikus ACL-ek összeadódnak; a sémaszintű default `REVOKE` nem vonja vissza a globális grantet.

Külön ellenőrzés kell **a jövőben létrehozott objektumok** default ACL-jeire és **a már létező objektumok** tényleges ACL-jeire: `ALTER DEFAULT PRIVILEGES` az utóbbiakat nem módosítja, a meglévő objektumokon végzett `REVOKE` pedig a későbbi objektumok alapértelmezését nem változtatja meg. A `--no-acl` csak a dump grantjeinek visszaállítását mellőzi, nem szünteti meg a cél új objektumokra vonatkozó default ACL-jeit. A default ACL változtatásai és a meglévő objektumok célzott visszavonásai külön, jóváhagyott lépések; más alkalmazások és `service_role` jogosultságai ne sérüljenek véletlenül.

A következő, csak olvasó lekérdezést a migrációs bejelentkezés és az esetleges `SET ROLE` **tényleges `current_user`-ének azonosítása után** futtassuk; a `<TÉNYLEGES_CURRENT_USER>` helyére a jóváhagyott role neve kerüljön. A három szerepkörhöz tartozó globális és `public` tételek szerepelnek; `acldefault` és célzott stagingteszt szükséges a hiányzó globális bejegyzések beépített értelmezéséhez.

```sql
SELECT current_user, session_user;
SELECT r.rolname AS creator, COALESCE(n.nspname, '<global>') AS scope,
       d.defaclobjtype, COALESCE(g.rolname, 'PUBLIC') AS grantee,
       x.privilege_type
FROM pg_default_acl d
JOIN pg_roles r ON r.oid = d.defaclrole
LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace
CROSS JOIN LATERAL aclexplode(d.defaclacl) x
LEFT JOIN pg_roles g ON g.oid = x.grantee
WHERE r.rolname IN ('postgres', 'supabase_admin', '<TÉNYLEGES_CURRENT_USER>')
  AND (d.defaclnamespace = 0 OR n.nspname = 'public')
ORDER BY 1, 2, 3, 4, 5;
```

### Dashboard-szerepkör

Javasolt egy külön `spc_dashboard_reader` LOGIN role, `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS` tulajdonságokkal, erős, külön kezelt jelszóval. Ne legyen táblatulajdonos, ne legyen `postgres`, `service_role`, `anon` vagy `authenticated` tagja, és ne kapjon írási, CREATE vagy szekvenciajogosultságot. A `default_transaction_read_only` kiegészítő védelem, **nem** helyettesíti a jogosultságkorlátozást.

A jelenlegi lekérdezésekhez a szerepkör kapjon `USAGE`-t a `public` sémára és `SELECT`-et kizárólag erre a hat objektumra:

```sql
GRANT SELECT ON
  public.v_measurement_enriched, public.v_spc_rule_results,
  public.dim_specification, public.spc_baseline,
  public.bridge_measurement_robot, public.dim_robot
TO spc_dashboard_reader;
```

Ez a grant **csak a szerepkör létrehozása és az alkalmazásobjektumok helyreállítása után**, jóváhagyott migrációban futtatható. A két nézet az előző szakaszban meghatározott tényleges tulajdonos jogosultságaival és RLS-feltételeivel működik; a teljes adatkészletet csak a jogosult dashboard-role számára szabad láthatóvá tenni.

A védelem rétegei:

1. Jóváhagyás és a más projektrészekre gyakorolt hatás ellenőrzése után a **migráló tényleges owner** `public` sémára vonatkozó default ACL-jeiből vonjuk vissza az `anon` és `authenticated` tábla-, szekvencia- és függvényjogait. A célban most a `postgres` és `supabase_admin` default ACL-je is széles; nem szabad feltételezni, hogy az egyik módosítása a másikat is kezeli. A globális `PUBLIC` függvény-EXECUTE alapjog külön kérdés: sémahatókörű default revoke önmagában nem távolítja el. A globális módosítás más sémákat is érinthet; azt csak külön hatásvizsgálattal, vagy helyette az alkalmazásfüggvényeken végzett célzott `REVOKE`-dal kezeljük.
2. A visszaállított **12 alkalmazástáblán** kapcsoljuk be az RLS-t, és alapértelmezésben ne legyen `anon`/`authenticated` policy. A dashboard által közvetlenül olvasott négy táblához (`dim_specification`, `spc_baseline`, `bridge_measurement_robot`, `dim_robot`) hozzunk létre kizárólag `spc_dashboard_reader` számára `FOR SELECT USING (true)` policy-t. A policy nem helyettesíti a `GRANT`-et.
3. Az alkalmazás 12 táblájáról, 13 nézetéről, 11 szekvenciájáról és két függvényéről ellenőrizzük és célzottan vonjuk vissza az `anon`, `authenticated` és szükség szerint `PUBLIC` jogosultságokat. A `service_role` kezelését a projekt többi szolgáltatásának ismeretében kell jóváhagyni. A teljes sémára vagy globálisan kiterjedő revoke más rendszert is érinthet.
4. A létrehozást és a konkrét RLS/ACL hardeninget lehetőleg **egyetlen tranzakcióban**, a Data API lezárása mellett végezzük. Amíg ez nem sikerült és nem ellenőrzött, a cél ne legyen nyilvános forgalomnak kitéve. Ellenőrizzük a tényleges jogosultságokat, az örökölt role-tagságot és a `PUBLIC` jogokat, majd negatív hozzáférési teszteket is futtassunk.

A dedikált role létrehozásához és jelszavához külön adminisztrátori jóváhagyás kell; a jelszó ne legyen SQL-fájlban, parancssori argumentumban, Gitben vagy jelentésben. A platform által biztosított biztonságos jelszóbeállítást használjuk.

### Példa jogosultsági lekérdezés

Az alábbi jogtesztet a célon az alkalmazásobjektumok és a role létrejötte után kell futtatni; az örökölt és `PUBLIC` jogokat a `has_table_privilege` is figyelembe veszi:

```sql
SELECT r.role_name, o.object_name,
       has_table_privilege(r.role_name, o.object_name, 'SELECT') AS can_select,
       has_table_privilege(r.role_name, o.object_name, 'INSERT') AS can_insert,
       has_table_privilege(r.role_name, o.object_name, 'UPDATE') AS can_update,
       has_table_privilege(r.role_name, o.object_name, 'DELETE') AS can_delete
FROM (VALUES ('anon'), ('authenticated'), ('spc_dashboard_reader')) r(role_name)
CROSS JOIN (VALUES
  ('public.v_measurement_enriched'), ('public.v_spc_rule_results'),
  ('public.dim_specification'), ('public.spc_baseline'),
  ('public.bridge_measurement_robot'), ('public.dim_robot')
) o(object_name)
ORDER BY r.role_name, o.object_name;
```

Az elvárt eredmény a hat objektumra a dashboard-role-nál csak SELECT, a két API-role-nál egyik felsorolt jog sem. Ez önmagában nem bizonyítja az API teljes lezárását: a többi nézetet/táblát, a szekvenciákat, függvényeket, role-tagságot és az API tényleges beállítását is külön vizsgálni kell.

### Kipróbálandó, objektumszintű hardening SQL

Az alábbi minta a **lezárt, kiértékelt első izolált stagingpróba után**, az annak eredményeire épülő hardening során, külön jóváhagyással próbálható ki stagingen. Az első próba nem követeli meg a későbbi hardening sikerét. Éles célon csak a második stagingpróba, a staging GO és külön éles jóváhagyás után alkalmazható. Előfeltétel a `spc_dashboard_reader` role jelszó nélküli SQL-lel történő létrehozása, majd jelszavának biztonságos külön beállítása; a role-létrehozásra és a cél owner jogosultságaira vonatkozó Supabase-korlátokat az első stagingpróbán kell vizsgálni. A `CREATE ROLE` nem tartalmaz jelszót:

```sql
CREATE ROLE spc_dashboard_reader LOGIN NOSUPERUSER NOCREATEDB
  NOCREATEROLE NOREPLICATION NOBYPASSRLS;
```

Az alábbi script a restore után, annak tranzakcióján belül futtatandó. Kizárólag a felsorolt alkalmazásobjektumokat érinti, de a `PUBLIC` revoke minden szerepkör örökölt jogát érintheti; a hatást stagingen ellenőrizni kell. Az `anon`/`authenticated` default ACL-eket és az API-kitettséget ettől külön, már a betöltés előtt kezelni kell.

```sql
DO $$
DECLARE
  obj text;
BEGIN
  FOREACH obj IN ARRAY ARRAY[
    'dim_booth', 'dim_shift', 'dim_measurement_point', 'dim_specification',
    'dim_track_axis', 'dim_robot', 'dim_batch', 'dim_cabin',
    'fact_quality_measurement', 'bridge_measurement_robot',
    'fact_process_event', 'spc_baseline'
  ]
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', obj);
    EXECUTE format(
      'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM PUBLIC, anon, authenticated', obj
    );
  END LOOP;

  FOREACH obj IN ARRAY ARRAY[
    'v_measurement_enriched', 'v_spc_rule_results',
    'v_spc_rule_results_booth01_a_l1', 'v_capability_measurements_booth01_a_l1',
    'v_drift_shift_measurements_booth01_a_l1', 'v_batch_quality',
    'v_event_evaluation_context', 'v_booth_quality_daily', 'v_cabin_quality',
    'v_measurement_point_quality', 'v_production_volume',
    'v_robot_attribution_quality', 'v_shift_quality_daily'
  ]
  LOOP
    EXECUTE format(
      'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM PUBLIC, anon, authenticated', obj
    );
  END LOOP;

  FOREACH obj IN ARRAY ARRAY[
    'dim_batch_batch_id_seq', 'dim_booth_booth_id_seq', 'dim_cabin_cabin_id_seq',
    'dim_measurement_point_measurement_point_id_seq', 'dim_robot_robot_id_seq',
    'dim_shift_shift_id_seq', 'dim_specification_specification_id_seq',
    'dim_track_axis_track_axis_id_seq', 'fact_process_event_event_id_seq',
    'fact_quality_measurement_measurement_id_seq', 'spc_baseline_baseline_id_seq'
  ]
  LOOP
    EXECUTE format(
      'REVOKE ALL PRIVILEGES ON SEQUENCE public.%I FROM PUBLIC, anon, authenticated', obj
    );
  END LOOP;
END
$$;

REVOKE ALL ON FUNCTION public.enforce_spc_baseline_immutability()
  FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.enforce_spc_baseline_supersession()
  FROM PUBLIC, anon, authenticated;

CREATE POLICY spc_dashboard_select ON public.dim_specification
  FOR SELECT TO spc_dashboard_reader USING (true);
CREATE POLICY spc_dashboard_select ON public.spc_baseline
  FOR SELECT TO spc_dashboard_reader USING (true);
CREATE POLICY spc_dashboard_select ON public.bridge_measurement_robot
  FOR SELECT TO spc_dashboard_reader USING (true);
CREATE POLICY spc_dashboard_select ON public.dim_robot
  FOR SELECT TO spc_dashboard_reader USING (true);

GRANT USAGE ON SCHEMA public TO spc_dashboard_reader;
GRANT SELECT ON
  public.v_measurement_enriched, public.v_spc_rule_results,
  public.dim_specification, public.spc_baseline,
  public.bridge_measurement_robot, public.dim_robot
TO spc_dashboard_reader;
```

A role tényleges `CONNECT` joga és bármely örökölt jogosultsága külön ellenőrzendő. A script nem módosít default ACL-t, nem zárja le a Data API-t és nem vonja vissza a `service_role` kifejezett grantjeit; ezek ezért változatlanul **külön átvételi kapuk**.

### Konkrét stagingteszt: nézettulajdonos és RLS

Ez a **második stagingpróbához** tartozó jövőbeli ellenőrzési eljárás, **nem futott le**. Csak elkülönített, azonos Supabase-beállítású stagingen végezhető el, miután az első próbát kiértékeltük, a szükséges hardeninget elvégeztük, és a második próba jóváhagyott teljes restore-ja megtörtént. Az első próbának nem előfeltétele a későbbi hardening vagy ez a teljes adatokon végzett teszt. Két külön tényleges bejelentkezést használjunk: az objektumtulajdonosként ellenőrzésre jogosult adminisztratív szerepkört, illetve a tényleges `spc_dashboard_reader` LOGIN-t. Ne támaszkodjunk kizárólag superuserként futtatott SELECT-re vagy a dashboard általános sikerüzenetére.

1. Az adminisztratív munkamenetben azonosítsuk a tényleges tulajdonost, a nézetbeállítást és **minden érintett alaptábla** RLS-jellemzőjét:

   ```sql
   SELECT c.relname, c.relkind, pg_get_userbyid(c.relowner) AS owner,
          c.relrowsecurity, c.relforcerowsecurity, c.reloptions
   FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public'
     AND c.relname IN (
       'v_measurement_enriched', 'v_spc_rule_results',
       'fact_quality_measurement', 'dim_cabin', 'dim_batch', 'dim_shift',
       'dim_booth', 'dim_measurement_point', 'dim_specification', 'spc_baseline'
     )
   ORDER BY c.relname;
   SELECT rolname, rolcanlogin, rolsuper, rolbypassrls
   FROM pg_roles WHERE rolname IN ('spc_dashboard_reader', '<TÉNYLEGES_OWNER>');
   SELECT schemaname, tablename, policyname, roles, cmd, qual
   FROM pg_policies WHERE schemaname = 'public' ORDER BY tablename, policyname;
   ```

   Elvárás az alapmodellben: a két nézet és a fenti nyolc alaptábla azonos, jóváhagyott owner alatt van; a táblákon `relrowsecurity=true`, `relforcerowsecurity=false`; a nézeteken nincs `security_invoker=true`; a reader nem owner/tag, és nincs `BYPASSRLS`. Más owner, `FORCE`, `security_invoker` vagy hiányzó jogosultság esetén csak a dokumentált alternatív policy-/SELECT-modell külön stagingtesztje után szabad továbbmenni.
2. Külön `spc_dashboard_reader` kapcsolattal előbb ellenőrizzük `current_user` és `session_user` értékét, a `row_security_active('public.dim_specification'::regclass)` eredményét, a hat objektumra a jogosultságot és az eredeti dashboard két teljes lekérdezését. A `row_security_active` a közvetlenül elérő role-ra vonatkozik, **nem** bizonyítja önmagában a nézettulajdonos alatti kiértékelést.
3. Ugyanezzel a readerrel futtassuk az alábbi SELECT-eket:

   ```sql
   SELECT current_user, session_user,
          row_security_active('public.dim_specification'::regclass) AS reader_rls_active;
   SELECT count(*) AS enriched_rows FROM public.v_measurement_enriched;
   SELECT count(*) AS observations,
          count(*) FILTER (WHERE baseline_id = 1) AS baseline_1,
          count(*) FILTER (WHERE baseline_id IS NULL) AS not_assessed,
          count(*) FILTER (WHERE spc_signal) AS signal
   FROM public.v_spc_rule_results
   WHERE booth = 'BOOTH_01' AND measurement_point = 'A-L1';
   ```

   A jelenlegi snapshot referenciaeredménye `167400`, illetve `4650`, `4200`, `450`, `267`; friss snapshot esetén a jóváhagyott, közvetlenül migráció előtt létrehozott referenciát kell használni. Nem elég a darabszám: mérésazonosító szerint össze kell vetni a teljes nézetkimenetet, külön a `baseline_id`, limit-, MR- és Rule 1–4 mezőket; külön vizsgáljuk a közvetlenül olvasott négy tábla RLS-policy-jainak eredményét is. A teljes halmazon egyező kivonat vagy soronkénti összehasonlítás szükséges; hiányzó sor vagy jogosultsági hiba bukás.
4. Igazoljuk a negatív kontrollt: az `anon` és `authenticated` ne rendelkezhessen SELECT-joggal a két nézeten vagy bármely más alkalmazásobjektumon, és ne szerepeljen a reader/owner tagságában. A nézetekbe beépített RLS-kikerülés nem adhat hozzáférést ezeknek a szerepköröknek. Staging Data API-negatív teszt szükséges a következő átvételi kapu szerint; hibás hitelesítést vagy hálózati hibát nem szabad jogosultsági bizonyítéknak tekinteni.
5. Az eredményeket, szerepkörneveket, objektumtulajdont, RLS-flageket és összehasonlítási módszert a stagingjegyzőkönyvben rögzítsük. Azonosság, RLS-policy és szerepkör-jogosultság eltérése esetén a migráció nem hagyható jóvá.

## Opcionális függelék: kiegészítő ellenőrzési infrastruktúra

A korábban tervezett saját, típusjelölt JSONL-sorreferencia és JSON-manifesztum, az age X25519 titkosítás, az Ed25519-aláírás és a külön snapshot-validátor használható, ha a tulajdonos és a biztonsági felelős ezt külön jóváhagyja. Nem előfeltétele az alapmigrációnak. Ha használjuk, védjük a kulcsokat és a teljes adatmásolatot, ellenőrizzük a teljes visszaolvasást, az aláírást és a fájlok sértetlenségét; az aláírás hitelesít, a SHA-256 önmagában nem.

Az opcionális eszköz vagy referencia sem helyettesíti az alapfolyamat teljes, PK szerinti sorösszehasonlítását, az izolált restore-t, a dashboardpróbát vagy a külön jóváhagyásokat. Új eszköz implementálása esetén előbb kizárólag izolált tesztadatbázisokon kell ellenőrizni. A **DESIGN READY** történeti tervezési döntés továbbra sem snapshot-, staging- vagy production-GO.
