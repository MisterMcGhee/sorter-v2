# Restart Goal: Main + Hive + YOLO Zones + C4 Five-Sector Channel

Stand: 2026-05-08

Branch: `restart/main-plus-hive-yolo-zones`

Basis: `origin/main`

## Leitentscheidung

Wir schwenken bewusst weg von der grossen `sorthive`-Runtime-Richtung und zurueck zu einem kleinen, nachvollziehbaren Aufbau auf `origin/main`.

`sorthive` bleibt ein Materiallager und Archiv. Es ist nicht mehr der Zielzustand. Alles, was wir daraus uebernehmen, wird klein, einzeln pruefbar und mit klarem Maschinenzweck neu in die Main-basierte Branch portiert.

Die wichtigste neue Grenze:

**Phase 1 wird komplett ohne echte Hardware umgesetzt und validiert.**

Keine Motorbewegungen, keine Homing-Laeufe, keine Kamera-Live-Diagnosen an der realen Maschine, keine API-Probes gegen laufende Hardware. Die reale Maschine kommt erst in einer spaeteren Hardware-Phase dran.

## Warum dieser Reset noetig ist

Wir hatten in der alten Richtung viele richtige Einzelideen, aber die Gesamtbewegung wurde zu breit:

- zu viele Runtime-Abstraktionen auf einmal
- zu viele neue Zustandsmodelle
- zu viel Tracking-/Throughput-/Runner-Logik gleichzeitig
- zu viele UI-Flaechen fuer Diagnose und Tuning
- zu viele Codepfade, die schwer direkt gegen Maschinenverhalten zu verifizieren sind

Gleichzeitig hat sich die Hardware- und Prozessannahme fuer C4 wieder vereinfacht:

- C4 ist hardwareseitig kein altes Direct-Drive-Carousel.
- C4 ist ein C-Channel mit Stepper, Gear Ratio, Microsteps, Treibergrenzen, Geschwindigkeit und Beschleunigung.
- C4 hat aber logisch einen 5-Sektor-Teller bekommen.
- Damit verhaelt sich C4 funktional wieder naeher am alten Carousel-Prinzip: diskrete Zielsektoren statt freies Multi-Object-Tracking-Chaos.

Der neue Plan nutzt diese Vereinfachung.

## Nicht verhandelbare Regeln

1. `origin/main` bleibt der Anker.
2. `sorthive` wird nur gelesen, nicht blind gemerged.
3. Jede uebernommene Aenderung braucht einen konkreten Maschinenzweck.
4. Phase 1 beruehrt keine echte Hardware.
5. C4 ist motionseitig ein C-Channel.
6. C4 ist logisch ein 5-Sektor-Platter.
7. Keine alte Carousel-Direktantrieb-Annahme fuer C4.
8. Keine neue grosse Runtime-Architektur.
9. Keine Throughput-Diagnostik in diesem Reset.
10. Kein BoxMOT, kein ReID, kein Shadow-Tracker-Framework.
11. Bewegungsausfuehrung bleibt default aus und braucht explizite Freigabe.
12. Wenn eine Geschwindigkeit oder Beschleunigung spaeter nicht erreichbar ist, muss das sichtbar diagnostiziert werden.

## Aktueller Branch-Stand

Die Branch ist aktuell 11 Commits vor `origin/main`.

Bereits auf der Branch umgesetzt:

- Hive Model Download-Filenames behalten sprechende Namen.
- C4 wird als Classification Channel ueber einen C-Channel-Axis-Pfad behandelt.
- C-Channel-Zone-Geometrie wurde praeziser.
- C4 Wall-Phase-Erkennung wurde hinzugefuegt.
- C4 Five-Sector-Platter-Modell wurde als kleine, isolierte Logik hinzugefuegt.
- C4 Sector Occupancy Debug-Endpunkt wurde hinzugefuegt.
- Settings-UI zeigt C4 Sector Occupancy.
- C4 Sector Move Planner wurde hinzugefuegt, standardmaessig planend statt ausfuehrend.
- Hive C4 Sector Models werden auf den Main-kompatiblen Detection Scope gemappt.
- C4 Sector Probe Helper wurde hinzugefuegt.
- Dashboard-Crops verwenden per-channel Resolution Metadata.
- Probe Helper kann aus Occupancy einen Plan ableiten, bleibt aber ohne explizite Freigabe nicht ausfuehrend.

Phase-1-Nachtrag vom 2026-05-08:

- `frame_luma`-Diagnostik fuer C4 Wall Phase und Sector Occupancy wurde umgesetzt.
- C4 Sector Move Responses transportieren Motion-Profile und Warnings.
- Der C4 Auto-Planer blockiert, wenn der Exit-Sektor bereits belegt ist.
- Dunkle/ungueltige Frames werden code-only mit strukturierter Diagnose getestet.

## Zielbild

Am Ende dieses Reset-Strangs wollen wir eine kleine Main-basierte Branch haben, die:

- Hive-relevante Verbesserungen sauber enthaelt.
- YOLO-Modell-Auswahl und C4-Sector-Modell minimal enthaelt.
- C2/C3/C4-Zonen praezise konfigurierbar macht.
- C4 als hardwareseitigen C-Channel korrekt modelliert.
- C4 logisch als 5-Sektor-System steuerbar macht.
- C4-Sektorbelegung aus Detection ableiten kann.
- C4-Bewegungen erst planen und spaeter kontrolliert ausfuehren kann.
- Keine breite neue Runtime enthaelt.
- Ohne Hardware vollstaendig lokal testbar ist.
- Spaeter eine klare, kurze Hardware-Validierung erlaubt.

## Begriffe

### C2 / C3

Normale C-Channels. Sie brauchen praezise Zone-Geometrie, Crop-/Masken-Zuordnung und klare Bewegungsparameter.

### C4 / Classification Channel

C4 ist der Classification Channel.

Wichtig:

- Hardware: C-Channel-Stepper mit Uebersetzung.
- Logik: 5-Sektor-Platter.
- Perception: YOLO/Zone-Erkennung fuer Sektorbelegung.
- State: Sektoren frei/belegt/Uebergabe/Exit.

C4 darf nicht als altes Carousel mit Direct Drive behandelt werden.

### Sector Occupancy

Eine kompakte Sektorbelegung fuer C4:

- welcher Sektor ist frei
- welcher Sektor ist belegt
- welcher Sektor ist am Exit
- welcher Sektor ist als Ziel fuer naechsten Move sinnvoll

Keine freie Langzeit-Track-Bank fuer beliebige Objekte.

## Phase 0: Ausgangspunkt sichern

Status: weitgehend erledigt.

Ziele:

- Alte Arbeit nicht verlieren.
- Main-basierte Branch als neuen Startpunkt nutzen.
- Unbeabsichtigtes Weiterarbeiten auf dem alten Ast vermeiden.

Erledigt:

- `sorthive` bleibt erhalten.
- `archive/sorthive-limbo-2026-05-08` existiert als Archiv/WIP-Sicherung.
- Neue Branch von `origin/main` wurde erstellt.
- Aktuelle Branch: `restart/main-plus-hive-yolo-zones`.

Noch pruefen:

- Ob alle relevanten alten lokalen Artefakte absichtlich untracked bleiben.
- Ob `data/`, `logs/`, SQLite-Backups und alte Lab-Dokumente bewusst nicht Teil dieser Branch werden sollen.

Akzeptanz:

- Kein unabsichtliches Loeschen.
- Kein Grossmerge aus `sorthive`.
- Branch-Historie bleibt klein und nachvollziehbar.

## Phase 1: Code-only Umsetzung ohne echte Hardware

Status: abgeschlossen, hardwarefrei validiert am 2026-05-08.

Diese Phase darf keine reale Maschine beruehren.

Verboten in Phase 1:

- `main.py` gegen die reale Maschine starten, um Hardware zu pruefen
- Homing
- Motorinitialisierung
- echte Stepper-Moves
- Live-Kamera-Probes an der Maschine
- Endpunkte mit `execute=true`
- Tests, die echte Geraete voraussetzen

Erlaubt in Phase 1:

- Unit Tests
- FastAPI TestClient mit Mocks
- synthetische Frames
- gemockte Vision Manager
- statische Config-Tests
- reine Planner-Tests
- Frontend Type/Check/Build
- Code-Audit gegen verbotene Komponenten

### Phase 1.1: Hive sauber retten

Behalten:

- Main-S3-Storage als Basis.
- Hive Model Download-Filenames.
- Hive Model-/Sample-UI-Verbesserungen, sofern unabhaengig.
- Tests fuer Download-Filename und Storage.

Nicht vermischen mit:

- Sorter Runtime
- C4 Runtime
- Tracking
- Hardwarebewegung

Akzeptanz:

- Hive Backend Tests laufen.
- Hive Frontend Check laeuft.
- Keine Sorter-Runtime-Abhaengigkeit in Hive-Ports.

### Phase 1.2: YOLO/Hive-Modellpfad minimal portieren

Behalten:

- Modellliste.
- Modell-Download.
- Runtime-Modellauswahl.
- ONNX/NCNN/Hailo-Ladepfad, soweit Main-kompatibel.
- Spezielles C4-Zone-/Sector-YOLO-Modell.

Nicht portieren:

- BoxMOT.
- ReID.
- Shadow Tracker Framework.
- grosse `rt/` Runner-/Perception-Architektur.

Akzeptanz:

- C4-Sector-Modelle tauchen in der Modelllogik korrekt auf.
- Modell-Scope-Mapping bleibt Main-kompatibel.
- Tests decken Alias-/Scope-Mapping ab.

### Phase 1.3: Zone-Editor und Zone Config portieren

Behalten:

- praezisere Polygon-Zonen.
- Arc-/Chord-Zonen fuer C-Channel-Geometrie.
- per-channel Resolution Metadata.
- bessere Crop-/Masken-Zuordnung.
- Tests fuer Polygon Config und Polygon Resolution.

Ziel:

C2, C3 und C4 muessen sauber zugeschnitten werden koennen, ohne dass dafuer eine neue Runtime-Architektur noetig ist.

Akzeptanz:

- Zone-Konfiguration ist pro Channel deterministisch speicherbar.
- Resolution Metadata wird beim Zuschneiden beruecksichtigt.
- Dashboard-/Preview-Crops nutzen die richtige Channel-Resolution.
- Synthetic Tests pruefen Crop/Mask-Zuordnung.

### Phase 1.4: C4 hardwareseitig korrekt modellieren

Wichtigste Regel:

**C4 ist ein C-Channel mit 5-Sektor-Logik.**

Motion-Seite:

- C-Channel-Stepper.
- Gear Ratio.
- Microsteps.
- NEMA-/Treibergrenzen.
- Speed.
- Acceleration.
- Richtung.
- Steps pro Sektor.

Logik-Seite:

- 5 Sektoren.
- diskrete Zielpositionen.
- Sector Occupancy.
- Exit-Sektor.
- Uebergabe-/Deposit-Sektor.

Nicht erlaubt:

- Direct-Drive-Carousel-Annahme.
- alte Carousel-Step-Berechnung fuer C4.
- implizite Annahme, dass ein Sektor-Move mechanisch einer Direct-Drive-Rotation entspricht.

Akzeptanz:

- Unit Tests fuer Gear-Ratio/Steps/Direction.
- Unit Tests fuer Sector-to-Angle.
- Unit Tests fuer Angle-to-C-Channel-Stepper-Move.
- Tests dokumentieren explizit, dass C4 nicht Direct Drive ist.

### Phase 1.5: C4 Five-Sector-Platter klein halten

Neu geschriebene kleine Logik statt alter grosser Branch:

- `C4SectorState`
- `C4FiveSectorPlatter`
- Mapping Detection -> Sector Occupancy
- Mapping gewuenschter Sektor-Move -> C-Channel-Rotation
- Planner fuer naechsten sinnvollen Move

Nicht uebernehmen:

- `SectorCarouselHandler`
- Landing Leases
- PieceTrackBank
- grosse Runtime State Machines

Akzeptanz:

- Sector Occupancy ist aus isolierten Inputs berechenbar.
- Planner kann ohne Hardware sagen: welcher Move waere sinnvoll.
- Planner fuehrt nicht automatisch aus.
- Edge Cases sind getestet:
  - keine Detection
  - mehrere Detections
  - Detektion auf Sektorgrenze
  - Exit-Sektor unbekannt
  - Zielsektor belegt

### Phase 1.6: API-Endpunkte defensiv halten

Behalten bzw. finalisieren:

- C4 Wall Phase Debug Endpoint.
- C4 Sector Occupancy Endpoint.
- C4 Sector Move Planner Endpoint.

Regeln:

- Endpunkte duerfen in Tests mit Mocks laufen.
- Planner default: `execute=false`.
- Ausfuehrung nur mit expliziter Bestaetigung.
- Fehler muessen als strukturierte Antwort sichtbar werden.
- Diagnosefelder duerfen helfen, aber keine neue Runtime erzwingen.

Sinnvolle Diagnosefelder:

- `ok`
- `message`
- `frame_resolution`
- `frame_luma`
- `wall_phase`
- `sector_count`
- `sector_offset_deg`
- `sectors`
- `candidate_bboxes`
- `detections`
- `blocked_reason`

Akzeptanz:

- TestClient Tests fuer Erfolgs- und Fehlerfaelle.
- Dunkles/ungueltiges synthetisches Frame liefert klare Diagnose.
- Keine echte Kamera noetig.

### Phase 1.7: UI minimal und versteckt halten

Behalten:

- C4 Sector Occupancy in Settings.
- Diagnose als Einstellungs-/Debugbereich.
- Keine prominente Sidebar fuer seltene Testmodi.

Nicht portieren:

- Direct Motion Panel.
- Sample Transport Panel.
- Runtime Tuning Panel.
- Run Trace UI.
- Throughput UI.

Akzeptanz:

- UI macht C4-Zustand sichtbar.
- UI loest nicht versehentlich Bewegung aus.
- Debug-Controls sind nicht als regulaerer Operator-Workflow missverstaendlich.

### Phase 1.8: Warnings fuer Motion-Limits vorbereiten

Das eigentliche Hardware-Verhalten wird erst spaeter live validiert. Trotzdem soll die Codebasis vorbereitet sein.

Code-only vorbereiten:

- Parameter fuer max speed und max acceleration pro C-Channel sichtbar machen.
- Planner soll erkennen koennen, welche Zielgeschwindigkeit angefordert wurde.
- Planner/API soll spaeter eine Warnung transportieren koennen, wenn ein Profil begrenzt wird.
- Keine stillen Clamps ohne Diagnose.

Noch nicht in Phase 1:

- echte Messung, ob C2/C3/C4 die Geschwindigkeit erreichen.
- echte Beschleunigungsprofile an der Maschine.
- echte Timing-/RPM-Validierung.

Akzeptanz:

- Tests koennen einen simulierten Limit-Fall pruefen.
- Antwortstruktur kann Warnings ins Frontend tragen.
- Keine Annahme, dass 64 RPM real sicher erreichbar sind.

### Phase 1.9: Test- und Audit-Paket

Mindestens ausfuehren:

- Hive Backend: Download-Filename-/Storage-Tests.
- Hive Frontend: Check.
- Sorter Backend: relevante C4-/Zone-/Detection-/Planner-Tests.
- Sorter Frontend: Check.

Zusaetzlicher Audit:

- Suche nach versehentlich portierten Altkomponenten:
  - BoxMOT
  - ReID
  - Shadow Tracker
  - `SectorCarouselHandler`
  - Landing Lease
  - PieceTrackBank
  - Throughput Baseline Ausbau
  - Direct Motion Panel
  - Runtime Tuning Panel

Akzeptanz:

- Tests gruen oder bewusst dokumentierte bestehende Fehler.
- Keine unerwuenschten Grosskomponenten in der Branch.
- Commits sind thematisch klein genug, um reviewbar zu bleiben.

## Phase 2: Hardware-freie Abschlusskontrolle

Status: noch offen.

Diese Phase ist immer noch ohne echte Hardware.

Ziel:

Vor der Maschine soll die Branch so stehen, dass wir genau wissen, was wir testen wollen und welche Abbruchbedingungen gelten.

Aufgaben:

1. Branch-Diff gegen `origin/main` reviewen.
2. Commitliste in fachliche Gruppen sortieren.
3. Untracked Artefakte bewusst ignorieren oder separat behandeln.
4. Alle Tests/Checks aus Phase 1 erneut laufen lassen.
5. C4-Hardware-Annahmen in Tests und Dokumentation pruefen.
6. Probe-Skripte auf sichere Defaults pruefen.
7. Sicherstellen, dass kein Script ohne explizite Flags Bewegung ausfuehrt.

Akzeptanz:

- Branch kann ohne Maschine reproduzierbar geprueft werden.
- Hardware-Testplan ist kurz und konkret.
- Alle riskanten Aktionen brauchen explizite Bedienerfreigabe.

## Phase 3: Erste reale Hardware-Validierung ohne Bewegung

Status: spaeter, nicht jetzt.

Diese Phase beruehrt die reale Maschine, aber fuehrt noch keine Bewegung aus.

Ziel:

Zuerst nur herausfinden, ob die Software die reale Maschine korrekt sieht.

Erlaubt:

- Backend starten.
- Status lesen.
- Setup lesen.
- Kamera-Config lesen.
- C4-Frame-/Detection-Diagnostik lesen.
- Occupancy planen.
- Sector Move nur als Plan mit `execute=false`.

Nicht erlaubt:

- Homing.
- Motor-Move.
- `execute=true`.
- automatische Recovery-/Purge-Routinen.

Konkrete Reihenfolge:

1. Maschine stabilisieren.
2. Backend starten.
3. `/api/system/status` lesen.
4. `/api/machine-setup` lesen.
5. `/api/cameras/config` lesen.
6. C4 Frame-Diagnostik lesen.
7. C4 Wall Phase lesen.
8. C4 Sector Occupancy lesen.
9. C4 Sector Move Plan berechnen lassen, aber nicht ausfuehren.

Abbruchbedingungen:

- Hardware State unklar.
- Homing aktiv.
- Stepper busy.
- Kamera liefert dunkles oder falsches Bild.
- C4 Frame Resolution passt nicht.
- Wall Phase nicht erkennbar.
- Exit-Sektor unbekannt.
- Occupancy widerspruechlich.
- Planner fordert Bewegung, obwohl Inputs unvollstaendig sind.

Akzeptanz:

- Wir koennen C4 sehen.
- Wir koennen C4-Sektoren logisch ableiten.
- Wir koennen einen Move planen.
- Noch kein Motor hat sich bewegt.

## Phase 4: Erste kontrollierte Hardware-Bewegung

Status: spaeter, nur nach Phase 3.

Ziel:

Eine einzelne, kleine C4-Bewegung mit vorher/nachher-Vergleich validieren.

Voraussetzungen:

- Phase 1 und 2 abgeschlossen.
- Phase 3 erfolgreich.
- Bediener steht an der Maschine.
- Mechanik ist frei.
- Not-Aus/Abbruch ist klar.
- Gewuenschte Bewegung ist klein und nachvollziehbar.

Konkrete Reihenfolge:

1. Status vorher erfassen.
2. Occupancy vorher erfassen.
3. Move planend berechnen.
4. Erwartete Steps/Richtung/RPM dokumentieren.
5. Nur mit expliziter Bestaetigung ausfuehren.
6. Status nachher erfassen.
7. Occupancy nachher erfassen.
8. Erwartung vs. Realitaet vergleichen.

Abbruchbedingungen:

- Richtung unklar.
- Gear Ratio unklar.
- Steps pro Sektor unplausibel.
- Speed/Acceleration wird still begrenzt.
- C4 bewegt sich anders als geplant.
- Occupancy nach Move nicht interpretierbar.

Akzeptanz:

- C4 bewegt sich in erwarteter Richtung.
- Sektorwechsel entspricht der Planung.
- Warnings werden sichtbar, falls Limits greifen.
- Kein verstecktes Clamping ohne UI/API-Diagnose.

## Phase 5: C2/C3/C4 Motion-Profile und Limits klaeren

Status: spaeter, nach erster sicherer Hardwarebewegung.

Ziel:

Zuverlaessig verstehen, warum C-Channels bei gleichen Faktoren unterschiedlich schnell wirken koennen.

Zu klaeren:

- Maximalgeschwindigkeit pro Channel.
- Maximale Beschleunigung pro Channel.
- Gear Ratio pro Channel.
- Microsteps pro Channel.
- Treiberlimits.
- Profilmodus.
- Ob UI-Faktor, RPM und Stepper-Speed sauber uebersetzt werden.
- Ob Limits still greifen.

Gewuenschter Zielzustand:

- Entweder Geschwindigkeit wird erreicht.
- Oder UI/API zeigt klar, warum sie nicht erreicht wird.

Akzeptanz:

- Keine stillen Unterschiede zwischen C2/C3/C4.
- Motion Profile sind transparent.
- Warnings poppen bis ins Frontend hoch.
- Testprofil fuer direkte Kontrolle kann existieren, aber versteckt/optional.
- Default-Operator-UI bleibt sauber.

## Explizite Nicht-Ziele fuer diesen Reset

Nicht bauen:

- neue allgemeine `rt/` Runtime Architektur
- BoxMOT Integration
- ReID
- Shadow Tracker Framework
- PieceTrackBank
- Landing Leases
- SectorCarouselHandler aus der alten Branch
- neue Throughput-Diagnostik
- Runtime Tuning Panel
- Run Trace UI
- Direct Motion Panel als permanente Sidebar-Flaeche
- Sample Transport Panel als regulaere UI
- breite Router-/Service-Extraktionen ohne direkten Maschinengewinn

## Commit-Strategie

Commits sollen klein und thematisch bleiben.

Empfohlene Gruppen:

1. Hive Download-/Storage-Fix.
2. C4 als Classification C-Channel Basis.
3. Zone Geometry / Resolution Metadata.
4. C4 Five-Sector Model.
5. C4 Occupancy API.
6. C4 Settings UI.
7. C4 Planner API.
8. Hive C4 Model Scope Mapping.
9. Probe Helper mit safe defaults.
10. Dashboard Crop Resolution.
11. Frame-Luma-Diagnostik.

Keine Sammelcommits mit Runtime-Architektur, UI und Hardwarelogik gleichzeitig.

## Naechste konkrete Schritte

1. `frame_luma`-Diagnostik als kleinen separaten Commit finalisieren.
2. Branch-Audit gegen `origin/main` machen.
3. Pruefen, ob unerwuenschte alte Komponenten versehentlich enthalten sind.
4. Phase-1-Testpaket laufen lassen.
5. Falls Tests fehlen, kleine Tests nachziehen.
6. Danach Phase-2-Hardware-freien Abschlussreview machen.
7. Erst danach Hardware-Phase planen und gemeinsam freigeben.

## Definition of Done fuer Phase 1

Phase 1 ist fertig, wenn:

- alle geplanten Code-only Funktionen vorhanden sind,
- Tests fuer Hive, Zone Config, C4 Gear Ratio, C4 Sector Occupancy und Planner existieren,
- Frontend Checks laufen,
- keine verbotenen Grosskomponenten portiert wurden,
- keine echte Hardware fuer die Validierung gebraucht wurde,
- alle Bewegungspfade default sicher sind,
- die spaetere Hardware-Validierung als kurzer, kontrollierter Ablauf dokumentiert ist.

## Phase 1 Abschlussaudit

Datum: 2026-05-08

Objective:

Alle Phase-1-Aufgaben aus dieser `Goal.md` code-only abschliessen, ohne echte Hardware zu beruehren.

### Requirement-to-Artifact-Checklist

1. Hive sauber retten
   - Artefakte:
     - `software/hive/backend/app/services/storage.py`
     - `software/hive/backend/app/routers/models.py`
     - `software/hive/backend/app/routers/machine_models.py`
     - `software/hive/backend/tests/test_model_download_filename.py`
     - `software/hive/frontend/src/routes/models/[id]/+page.svelte`
   - Evidence:
     - `uv run --with pytest --with httpx pytest -q tests/test_model_download_filename.py tests/test_models.py`
     - Ergebnis: 19 passed.

2. YOLO/Hive-Modellpfad minimal portieren
   - Artefakte:
     - `software/sorter/backend/server/hive_models.py`
     - `software/sorter/backend/vision/detection_registry.py`
     - `software/sorter/backend/vision/ml/factory.py`
     - `software/sorter/backend/tests/test_detection_registry_hive.py`
     - `software/sorter/backend/tests/test_hive_models.py`
     - `software/sorter/backend/tests/test_ml_factory.py`
   - Evidence:
     - C4/Hive scopes werden auf den Main-kompatiblen Carousel Detection Scope gemappt.
     - ONNX/NCNN/Hailo Artifact-Aufloesung und Factory-Pfade sind testgedeckt.

3. Zone-Editor und Zone Config portieren
   - Artefakte:
     - `software/sorter/frontend/src/lib/components/settings/ZoneSection.svelte`
     - `software/sorter/frontend/src/lib/components/setup/SetupZoneEditorModal.svelte`
     - `software/sorter/backend/subsystems/feeder/analysis.py`
     - `software/sorter/backend/server/routers/cameras.py`
     - `software/sorter/backend/tests/test_feeder_arc_config.py`
     - `software/sorter/backend/tests/test_camera_dashboard_crop_resolution.py`
   - Evidence:
     - Arc-/Chord-Zonen und per-channel Resolution Metadata sind testgedeckt.
     - Dashboard-Crops verwenden Channel-spezifische Resolution Metadata.

4. C4 hardwareseitig korrekt modellieren
   - Artefakte:
     - `software/sorter/backend/irl/config.py`
     - `software/sorter/backend/server/routers/setup.py`
     - `software/sorter/backend/server/routers/steppers.py`
     - `software/sorter/backend/subsystems/classification_channel/five_sector_platter.py`
     - `software/sorter/backend/tests/test_classification_channel_c4_hardware.py`
     - `software/sorter/backend/tests/test_c4_five_sector_platter.py`
   - Evidence:
     - C4 ist als `c_channel_4` aliasiert, aber auf der bisherigen Carousel-Port-Achse verdrahtet.
     - C4 nutzt C-Channel-Gear-Ratio, Microsteps und Stepper-Speed, nicht Direct-Drive-Carousel-Logik.
     - Gear-Ratio/Steps/Direction/Angle-Konvertierung sind unit-getestet.

5. C4 Five-Sector-Platter klein halten
   - Artefakte:
     - `software/sorter/backend/subsystems/classification_channel/five_sector_platter.py`
     - `software/sorter/backend/tests/test_c4_five_sector_platter.py`
   - Evidence:
     - `C4SectorState`, `C4FiveSectorPlatter`, Detection-to-Sector-Occupancy und Sector-Move-Planung sind isoliert.
     - Edge Cases sind getestet: mehrere Detections, keine Source-Detection, unbekannter Exit, belegter Exit, Wraparound, Grenzwinkel.

6. API-Endpunkte defensiv halten
   - Artefakte:
     - `software/sorter/backend/server/routers/detection.py`
     - `software/sorter/backend/server/routers/steppers.py`
     - `software/sorter/backend/tests/test_detection_routes.py`
     - `software/sorter/backend/tests/test_classification_channel_c4_hardware.py`
   - Evidence:
     - Wall Phase und Sector Occupancy laufen mit gemocktem Vision Manager und synthetischen Frames.
     - Dunkles Frame liefert strukturierte `frame_luma`-Diagnose und laesst Detection nicht weiterlaufen.
     - Sector Move default bleibt `execute=false`.
     - Execute-Pfad ist testbar, aber nur explizit.

7. UI minimal und versteckt halten
   - Artefakte:
     - `software/sorter/frontend/src/lib/components/settings/C4SectorOccupancyPanel.svelte`
     - `software/sorter/frontend/src/routes/settings/[station]/+page.svelte`
   - Evidence:
     - C4 Sector Occupancy liegt in Settings.
     - Kein Direct Motion Panel, Sample Transport Panel, Runtime Tuning Panel oder Run Trace UI wurde in dieser Branch portiert.
     - Sorter Frontend Check: 0 errors, 0 warnings.

8. Warnings fuer Motion-Limits vorbereiten
   - Artefakte:
     - `software/sorter/backend/subsystems/classification_channel/five_sector_platter.py`
     - `software/sorter/backend/server/routers/steppers.py`
     - `software/sorter/backend/tests/test_c4_five_sector_platter.py`
     - `software/sorter/backend/tests/test_classification_channel_c4_hardware.py`
   - Evidence:
     - C4 Move Response enthaelt effektive Speed-/Acceleration-Parameter.
     - Response enthaelt requested Speed/Acceleration, konfigurierte Stepper Default Speed und `warnings`.
     - Simulierter Limit-/Mismatch-Fall ist getestet.
     - Es wird nicht still geclamped.

9. Test- und Audit-Paket
   - Evidence:
     - Sorter Backend Phase-1-Set:
       `PYTHONPATH=. uv run pytest -q tests/test_c4_five_sector_platter.py tests/test_classification_channel_c4_hardware.py tests/test_c4_sector_probe_script.py tests/test_detection_routes.py tests/test_c4_wall_phase.py tests/test_camera_dashboard_crop_resolution.py tests/test_feeder_arc_config.py tests/test_detection_registry_hive.py tests/test_hive_models.py tests/test_ml_factory.py tests/test_setup_wizard.py tests/test_zone_manager.py`
       Ergebnis: 92 passed, 4 warnings.
     - Sorter Backend breit:
       `PYTHONPATH=. uv run pytest -q -k 'not overlay_renders_zone_as_annulus_sector and not collect_tracked_images_adds_c2_fallback_when_direct_detail_lacks_it'`
       Ergebnis: 295 passed, 2 deselected, 4 warnings.
     - Sorter Frontend:
       `pnpm run check`
       Ergebnis: 0 errors, 0 warnings.
     - Hive Frontend:
       `pnpm run check`
       Ergebnis: 0 errors, 16 bestehende Warnings.
     - Forbidden-component audit gegen Branch-Diff und Working-Diff:
       keine Treffer fuer BoxMOT, ReID, Shadow Tracker, SectorCarouselHandler, Landing Lease, PieceTrackBank, Direct Motion, Sample Transport, Runtime Tuning oder Run Trace.

### Bekannte Baseline-Abweichungen ausserhalb Phase 1

Diese zwei Tests schlagen im breiten Sorter-Backend-Lauf fehl, obwohl die betroffenen Dateien gegen `origin/main` unveraendert sind:

- `tests/test_classification_channel_zone_overlay.py::ClassificationChannelZoneOverlayTests::test_overlay_renders_zone_as_annulus_sector`
  - Ursache: Test sampelt einen gefuellten Sektor; aktueller Overlay-Code zeichnet nur eine duenne Outline-Lane.
- `tests/test_classification_channel_recognition.py::test_collect_tracked_images_adds_c2_fallback_when_direct_detail_lacks_it`
  - Ursache: bestehende Recognition-/Fallback-Abweichung ausserhalb der Phase-1-Aenderungsflaeche.

Diese Baseline-Fails wurden nicht in Phase 1 geloest, weil sie nicht Teil des Reset-Scope sind.

### Hardware-Grenze

Waehrend Phase 1 wurde keine echte Hardware validiert:

- kein Homing
- keine Motorinitialisierung
- keine echten Stepper-Moves
- kein `execute=true` gegen einen laufenden Backend-Prozess
- keine Live-Kamera-Abhaengigkeit fuer Tests

Die lokalen Backend-/Frontend-Server sind gestoppt; auf `8000` und `5173` lauscht kein Prozess.

## Offene Punkte

- Untracked `docs/`, `logs/`, `data/` und SQLite-Dateien bleiben bewusst ausserhalb dieses Phase-1-Abschlusses.
- Die zwei bekannten Baseline-Testabweichungen koennen spaeter separat bereinigt werden.
- Reale C4-Sector-YOLO-Qualitaet ohne BoxMOT wird erst in der Hardware-/Kamera-Phase bewertet.
- Echte C2/C3/C4 Speed-/Acceleration-Limits werden erst in Phase 5 gemessen.
