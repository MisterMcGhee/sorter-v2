Ja. Der wichtigste Perspektivwechsel wäre: **Ihr optimiert kein deterministisches Maschinchen, sondern ein stochastisches Flusssystem mit anonymen Partikeln.**
Ihr braucht deshalb weniger „ein Test, eine Änderung, ein Bauchgefühl“ und mehr:

1. **systematische Beobachtbarkeit**,
2. **saubere Kennzahlen pro Teilprozess**,
3. **kontrollierte Experimente mit Wiederholungen**,
4. **ein einfaches Flussmodell**, das euch sagt, *wo* der Engpass liegt.

Die Kameras reichen dafür ziemlich gut aus, auch wenn ihr einzelne Lego-Steine nicht dauerhaft über alle Teller verfolgen könnt.

---

## 1. Den Gesamtprozess als Flussmodell betrachten

Stellt euch die Anlage als lineare Kette vor:

```text
Bulkfeeder → Teller 2 → Teller 3 → Teller 4 → Distributor
```

Jeder Teller ist dabei kein einzelner Zustand, sondern eine kleine Folge von Zonen:

```text
Dropzone → Transportbereich → Exit-Zone → Übergabe zum nächsten Teller
```

Wenn ihr die Teller „aufwickelt“, bekommt ihr ungefähr:

```text
Bulk
  ↓
T2 Drop → T2 Transport → T2 Exit
  ↓
T3 Drop → T3 Transport → T3 Exit
  ↓
T4 Drop → T4 Transport → T4 Exit/Klassifikation → Distributor
```

Wichtig: Ihr müsst nicht jedes Teil mit ID verfolgen. Ihr könnt stattdessen erfassen:

```text
Zu Zeitpunkt t:
Wie viele Teile befinden sich in welcher Zone?
Wie dicht liegen sie?
Wie stark sind sie vereinzelt?
Wie schnell wandert die Dichte von Drop zu Exit?
Wie zuverlässig korreliert T2-Exit mit T3-Drop?
Wie zuverlässig korreliert T3-Exit mit T4-Drop?
Wie oft ist T4 in einem guten Vereinzelungszustand?
```

Das gibt euch schon sehr viel mehr Kausalität als ein globales „Test war besser/schlechter“.

---

## 2. Nicht nur Endergebnis messen, sondern Zwischen-KPIs

Euer Endziel ist vermutlich ungefähr:

> möglichst viele korrekt erkannte, einzeln separierte Teile pro Minute am Distributor.

Das ist aber als einzige Kennzahl zu spät im Prozess. Ihr braucht Zwischenkennzahlen, die jeder Teller verantwortet.

### Globale Ziel-KPIs

Zum Beispiel:

| KPI                        | Bedeutung                                                             |
| -------------------------- | --------------------------------------------------------------------- |
| `good_parts_per_min`       | korrekt einzeln übergebene Teile pro Minute                           |
| `single_part_success_rate` | Anteil der Übergaben, bei denen wirklich nur ein Teil übergeben wurde |
| `misclassification_rate`   | Klassifikationsfehler, falls messbar                                  |
| `jam_rate`                 | Stau-/Blockierereignisse pro Minute                                   |
| `starvation_time_T4`       | Zeitanteil, in dem Teller 4 keine verwertbaren Teile bekommt          |
| `overload_time_T4`         | Zeitanteil, in dem Teller 4 zu viele Teile hat                        |

### Pro-Teller-KPIs

Für Teller 2, 3 und 4 würde ich pro Zeitfenster, zum Beispiel pro Sekunde oder alle 2 Sekunden, erfassen:

| KPI                   | Beispiel                                               |
| --------------------- | ------------------------------------------------------ |
| `N_total`             | Anzahl Teile auf dem Teller                            |
| `N_drop`              | Anzahl Teile in der Dropzone                           |
| `N_exit`              | Anzahl Teile in der Exit-Zone                          |
| `arrival_rate`        | neue Teile pro Minute in Dropzone                      |
| `exit_rate`           | Teile pro Minute in Exit-Zone/Übergabe                 |
| `crowding_score`      | wie stark Teile beieinander liegen                     |
| `single_ratio`        | Anteil der Situationen mit genau einem isolierten Teil |
| `dwell_time_estimate` | geschätzte Aufenthaltszeit auf dem Teller              |
| `burstiness`          | wie unregelmäßig der Zufluss ist                       |
| `recirculation_rate`  | wie oft Teile eine Runde drehen, ohne zu verlassen     |

Gerade `starvation_time_T4`, `overload_time_T4` und `single_ratio_T4` sind wahrscheinlich extrem wertvoll. Denn ein schlechter finaler Output kann aus völlig unterschiedlichen Gründen entstehen:

```text
T4 bekommt nichts        → upstream zu langsam / Übergabe schlecht
T4 bekommt zu viel       → upstream überfüttert / T4 zu langsam
T4 bekommt Bursts        → Bulk oder T2/T3 puffern/metern schlecht
T4 hat Teile, aber nicht einzeln → Vereinzelung auf T3/T4 schlecht
T4 ist gut, Distributor scheitert → Problem liegt nach T4
```

Ohne diese Trennung optimiert ihr blind.

---

## 3. Eure Kameradaten als „anonyme Partikelwolke“ speichern

Ihr könnt pro YOLO-Detection ungefähr folgende Daten speichern:

```text
run_id
timestamp
table_id              # 2, 3, 4
x_px, y_px
x_table, y_table      # normalisierte Tellerkoordinaten
r, theta              # Polarkoordinaten auf dem Teller
zone_id               # Drop, Transport, Exit, Klassifikation etc.
bbox_width, bbox_height, bbox_area
class_id / part_type, falls vorhanden
confidence
```

Dann aggregiert ihr daraus Zeitfensterdaten:

```text
run_id
window_start
window_end
table_id
zone_id
count_mean
count_max
count_p95
arrival_events
exit_events
crowding_score
single_object_time_fraction
mean_bbox_area
large_part_fraction
small_part_fraction
```

Das ist viel wichtiger als nur Videoaufnahmen zu haben. Videos sind gut zur Diagnose, aber die Optimierung braucht strukturierte Zeitreihen.

Eine einfache Datenstruktur könnte so aussehen:

```text
runs
----
run_id
date
config_id
part_mix_id
bulk_start_mass_or_count
operator
notes
software_version
yolo_model_version

configs
-------
config_id
speed_T2
speed_T3
speed_T4
bulk_feeder_setting
mechanical_variant_T2
mechanical_variant_T3
mechanical_variant_T4
thresholds
other_settings

detections
----------
run_id
timestamp
table_id
x
y
r
theta
zone
bbox_area
class_id
confidence

window_metrics
--------------
run_id
window_start
table_id
N_total
N_drop
N_exit
arrival_rate
exit_rate
crowding_score
single_ratio
jam_score
burstiness

events
------
run_id
timestamp
event_type
table_id
zone
confidence
details
```

Am Anfang reicht auch Parquet/CSV plus Python-Auswertung. Eine Datenbank ist nett, aber der entscheidende Punkt ist nicht die Datenbank selbst, sondern dass ihr **jedes Experiment reproduzierbar mit Konfiguration und Messwerten verknüpft**.

---

## 4. Lokal tracken, aber nicht global erzwingen

Ihr sagt, dass ihr einzelne Teile nicht nachhaltig über alle Teller hinweg verfolgen könnt. Das ist okay.

Was ihr trotzdem machen könnt: **kurze lokale Tracklets pro Teller**.

Also nicht:

```text
Teil #123 wird von Teller 2 bis Teller 4 verfolgt.
```

Sondern:

```text
Ein Objekt wurde auf Teller 3 über 18 Frames ungefähr konsistent gesehen
und ist von Transportzone in Exit-Zone gewandert.
```

Dafür braucht ihr kein perfektes Re-Identification-System. Ein einfacher Tracker reicht oft:

```text
Frame t:
Detection A bei Winkel θ und Radius r

Frame t+1:
Suche Detection, die ungefähr dort liegt, wo A nach Tellerrotation sein sollte.
```

Der Matching-Score kann enthalten:

```text
erwartete Winkelbewegung durch Tellerrotation
räumliche Nähe
BBox-Größe
Klasse/Objekttyp
YOLO-Konfidenz
```

Damit könnt ihr Ereignisse zählen wie:

```text
Objekt betritt Dropzone
Objekt erreicht Exit-Zone
Objekt verschwindet nach Exit-Zone
Objekt bleibt ungewöhnlich lange auf Teller
Objekt bewegt sich nicht wie erwartet
Objekt rotiert mehrfach ohne Exit
```

Aber: Erzwingt keine perfekte Identität. Sobald es unsicher ist, lieber abbrechen und wieder anonym weiterzählen.

Das Ziel ist nicht perfekte Objektgeschichte, sondern bessere Flussmessung.

---

## 5. Übergaben statistisch messen: Exit-Signal gegen Drop-Signal

Ein sehr nützlicher Ansatz ist Kreuzkorrelation zwischen benachbarten Tellern.

Ihr erzeugt pro Teller Zeitreihen:

```text
E2(t) = Anzahl/Rate der Teile in T2-Exit
D3(t) = Anzahl/Rate neuer Teile in T3-Drop

E3(t) = Anzahl/Rate der Teile in T3-Exit
D4(t) = Anzahl/Rate neuer Teile in T4-Drop
```

Dann schaut ihr:

```text
Wenn T2-Exit hochgeht, steigt T3-Drop kurz danach?
Mit welcher Verzögerung?
Wie zuverlässig?
Wie stark?
```

Daraus bekommt ihr:

| Messwert             | Bedeutung                                               |
| -------------------- | ------------------------------------------------------- |
| Transfer-Lag         | typische Übergabezeit von Teller i zu Teller i+1        |
| Transfer-Effizienz   | wie viel Exit-Aktivität downstream wirklich ankommt     |
| Burst-Verstärkung    | ob ein Teller Zufluss-Bursts glättet oder verschlimmert |
| Übergabeinstabilität | ob die Korrelation stark schwankt                       |

Das ist extrem hilfreich, weil ihr dann nicht nur seht:

```text
Ende war schlecht.
```

Sondern zum Beispiel:

```text
T2 produziert genug Exit-Aktivität,
aber T3-Drop bekommt sie unregelmäßig.
Also liegt das Problem wahrscheinlich in der Übergabe T2→T3.
```

Oder:

```text
T3-Drop ist stabil,
aber T3-Exit kommt in großen Pulsen.
Also erzeugt T3 selbst Bursts oder Staus.
```

---

## 6. Little's Law als einfache, robuste Diagnose

Auch ohne individuelles Tracking könnt ihr Aufenthaltszeiten abschätzen.

Wenn ihr ungefähr kennt:

```text
L = mittlere Anzahl Teile auf einem Teller
λ = Durchflussrate durch diesen Teller
```

dann gilt näherungsweise:

```text
W = L / λ
```

Also:

```text
mittlere Aufenthaltszeit = mittlere Teileanzahl / Durchflussrate
```

Beispiel:

```text
Teller 3 hat im Mittel 12 Teile.
Teller 3 liefert 6 Teile/min weiter.

W_T3 ≈ 12 / 6 min = 2 min
```

Wenn `W_T3` plötzlich hochgeht, heißt das:

```text
Teile bleiben zu lange auf Teller 3.
```

Das kann bedeuten:

```text
Exit-Geometrie schlecht
Teller zu langsam
Teile kleben/stauen
zu viel Zufluss
Downstream blockiert
```

Diese Kennzahl ist robust, weil sie keine perfekte Teilverfolgung braucht.

---

## 7. Eine sehr wichtige Unterscheidung: Input-Varianz ist kein Fehler, sondern eine Störgröße

Der Bulkfeeder erzeugt unregelmäßigen Zufluss. Das ist eine Hauptursache dafür, dass einzelne Tests schwer interpretierbar sind.

Deshalb solltet ihr den Bulk-Zufluss nicht ignorieren, sondern als Störgröße messen.

Da Teller 2 eine Kamera hat, könnt ihr den Bulk-Zufluss indirekt erfassen:

```text
bulk_arrival_rate(t) = neue Teile in T2-Dropzone pro Zeitfenster
bulk_burstiness(t)   = Varianz / Mittelwert der Ankünfte
bulk_peak_rate(t)    = maximale Ankunftsrate in kurzem Fenster
```

Dann könnt ihr Testergebnisse nicht mehr nur vergleichen als:

```text
Konfiguration A hatte 27 Teile/min.
Konfiguration B hatte 31 Teile/min.
```

Sondern besser:

```text
Konfiguration B hatte bei vergleichbarer Bulk-Zuflussrate
und vergleichbarer Burstiness 15 % mehr gute Einzelübergaben.
```

Das ist der Unterschied zwischen Korrelation und brauchbarer Kausaldiagnose.

---

## 8. Nicht einzelne Tests vergleichen, sondern Verteilungen

Ein einzelner Testlauf ist bei eurem System wahrscheinlich fast wertlos.

Besser:

```text
Konfiguration A: 10–20 Läufe oder viele Zeitfenster
Konfiguration B: 10–20 Läufe oder viele Zeitfenster
Vergleich der Verteilungen
```

Aber Achtung: Videoframes sind nicht unabhängig. Wenn ihr mit 30 FPS aufzeichnet, habt ihr nicht 30 unabhängige Messungen pro Sekunde. Besser sind aggregierte Fenster:

```text
1-Sekunden-Fenster
2-Sekunden-Fenster
5-Sekunden-Fenster
```

Und dann eher vergleichen:

```text
Median
p10/p90
Konfidenzintervall
Anteil schlechter Zustände
Anteil guter Vereinzelungszustände
```

Nicht nur Mittelwerte.

Beispiel:

```text
A:
good_parts_per_min Median 24
overload_time_T4 18 %
starvation_time_T4 4 %

B:
good_parts_per_min Median 27
overload_time_T4 3 %
starvation_time_T4 15 %
```

Dann ist B nicht einfach „besser“. B erzeugt eventuell höheren Peak-Output, aber mehr Starvation. Je nach Ziel kann das gut oder schlecht sein.

---

## 9. Experimentdesign statt wildem Iterieren

Das größte methodische Problem bei euch scheint zu sein:

```text
Änderung machen → Test laufen lassen → Ergebnis anschauen → spekulieren
```

Das führt bei hoher Varianz fast zwangsläufig zu falschen Schlüssen.

Besser ist ein echtes Experimentdesign.

### Erst Baseline-Rauschen messen

Bevor ihr optimiert, nehmt eine Konfiguration und wiederholt sie mehrfach unverändert.

Ziel:

```text
Wie stark schwankt unser System, wenn wir gar nichts ändern?
```

Erst wenn ihr das wisst, könnt ihr sagen:

```text
Eine Änderung von +3 Teile/min ist relevant.
```

Oder:

```text
+3 Teile/min liegt komplett im normalen Rauschen.
```

### A-B-A statt nur A-B

Wenn möglich:

```text
A = alte Konfiguration
B = neue Konfiguration
A = alte Konfiguration nochmal
```

Wenn A am Ende anders ist als A am Anfang, hattet ihr Drift im System:

```text
anderer Teilemix
anderer Füllstand
mechanische Erwärmung
anderer Bulkzustand
Zufall
YOLO-Verhalten
```

Dann ist der Vergleich A gegen B weniger vertrauenswürdig.

### Randomisierte Reihenfolge

Nicht immer:

```text
A, dann B, dann C
```

Sondern zum Beispiel:

```text
A, C, B, A, B, C, C, A, B
```

Sonst verwechselt ihr Konfigurationswirkung mit zeitlichem Drift.

### Blockweise testen

Wenn der Teilemix stark variiert, testet innerhalb vergleichbarer Blöcke:

```text
Block 1: gleicher Teilebatch, A/B/C randomisiert
Block 2: anderer Teilebatch, A/B/C randomisiert
Block 3: wieder anderer Batch, A/B/C randomisiert
```

Dann könnt ihr später modellieren:

```text
Effekt der Konfiguration
plus Effekt des Teilebatches
plus Effekt des Bulk-Zuflusses
```

---

## 10. Für viele Stellschrauben: Design of Experiments statt „one factor at a time“

Wenn ihr mehrere Parameter habt, zum Beispiel:

```text
speed_T2
speed_T3
speed_T4
bulk_feeder_power
mechanical_guide_T3
exit_geometry_T4
YOLO_threshold
```

dann ist „immer nur eine Sache ändern“ oft schlechter als ein geplantes faktorielles Experiment, weil viele Effekte Wechselwirkungen haben.

Beispiel:

```text
T3 schneller machen ist schlecht, wenn T4 langsam ist.
T3 schneller machen ist gut, wenn T4 schneller läuft.
```

Dann hat `speed_T3` keinen isolierten Effekt. Der Effekt hängt von `speed_T4` ab.

Eine einfache Screening-Phase könnte so aussehen:

| Faktor    | niedrig | hoch |
| --------- | ------: | ---: |
| T2-Speed  |    40 % | 70 % |
| T3-Speed  |    40 % | 70 % |
| T4-Speed  |    40 % | 70 % |
| Bulk Duty |    20 % | 50 % |

Statt alle 16 Kombinationen perfekt auszutesten, könnt ihr mit einem reduzierten faktoriellen Plan starten. Ziel ist zuerst nicht die perfekte Einstellung, sondern:

```text
Welche 2–3 Faktoren dominieren überhaupt?
Welche Interaktionen sind offensichtlich?
Welche Faktoren sind fast egal?
```

Danach optimiert ihr nur noch die wichtigen Parameter feiner.

---

## 11. Ein statistisches Modell bauen, aber einfach anfangen

Ihr braucht kein riesiges Machine-Learning-System. Ein einfaches Regressionsmodell kann schon sehr helfen.

Zum Beispiel pro Zeitfenster:

```text
target = good_single_rate_T4
```

mit Features:

```text
speed_T2
speed_T3
speed_T4
bulk_arrival_rate_T2
bulk_burstiness_T2
N_T2
N_T3
N_T4
crowding_T3
crowding_T4
exit_rate_T2
exit_rate_T3
part_size_mix
```

Dann lernt ihr ungefähr:

```text
good_single_rate_T4 =
    f(Einstellungen, aktueller Systemzustand, Zuflussqualität)
```

Wichtig ist: Ihr trennt Stellgrößen von Störgrößen.

```text
Stellgrößen:
- Teller-Geschwindigkeiten
- Bulk-Duty
- mechanische Führungen
- Schwellenwerte
- Taktung

Störgrößen:
- zufälliger Bulk-Zufluss
- Teilemix
- Verkettungen
- temporäre Bursts
- Detektionsunsicherheit
```

Dann könnt ihr Aussagen treffen wie:

```text
Bei gleichem Bulk-Zufluss und ähnlicher T4-Belegung
erhöht Konfiguration B die Vereinzelungsrate auf T4 um ca. 12 %.
```

Das ist viel wertvoller als:

```text
B sah im Video irgendwie besser aus.
```

---

## 12. Root-Cause-Diagnose über Zustandsklassen

Ich würde jedem Zeitfenster zusätzlich einen Systemzustand zuweisen.

Beispiel:

```text
STARVED_T4
OVERLOADED_T4
GOOD_SINGLE_T4
JAM_T3
JAM_T4
BURST_INCOMING
TRANSFER_LOSS_T2_T3
TRANSFER_LOSS_T3_T4
```

Dann könnt ihr pro Run sagen:

```text
Run 17:
42 % GOOD_SINGLE_T4
21 % OVERLOADED_T4
8 % STARVED_T4
12 % JAM_T3
17 % sonstig
```

Das ist diagnostisch viel stärker als nur ein Score.

Eine mögliche Logik:

```text
Wenn N_T4 == 0 für länger als x Sekunden:
    STARVED_T4

Wenn N_T4 > Schwellwert oder crowding_T4 hoch:
    OVERLOADED_T4

Wenn N_T4_exit == 1 und Abstand zu anderen Teilen groß genug:
    GOOD_SINGLE_T4

Wenn N_T3 hoch, aber exit_rate_T3 niedrig:
    JAM_T3 oder RECIRCULATION_T3

Wenn exit_rate_T2 hoch, aber arrival_rate_T3 niedrig:
    TRANSFER_LOSS_T2_T3

Wenn arrival_rate_T4 stark pulst:
    BURST_INCOMING_T4
```

Dann wisst ihr, welche Stellschraube überhaupt plausibel ist.

---

## 13. Typische Diagnose-Matrix

So würde ich Ursachen grob ableiten:

| Beobachtung                            | Wahrscheinliche Ursache                                | Eher ändern an                               |
| -------------------------------------- | ------------------------------------------------------ | -------------------------------------------- |
| T4 oft leer                            | Upstream liefert zu wenig oder Übergabe T3→T4 schlecht | T3-Exit, T3-Speed, Übergabe T3→T4            |
| T4 oft überfüllt                       | T3 liefert zu viel oder T4 verarbeitet zu langsam      | T3 drosseln, T4 beschleunigen, T4-Geometrie  |
| T3 voll, T4 leer                       | Übergabe T3→T4 problematisch                           | mechanische Übergabe, T3-Exit-Zone           |
| T2 voll, T3 leer                       | Übergabe T2→T3 problematisch                           | T2-Exit/T3-Drop                              |
| T4 hat Teile, aber selten einzeln      | Vereinzelung auf T3/T4 schlecht                        | T3-Ausgabe drosseln, T4-Geometrie, T4-Speed  |
| Output stark bursty                    | Bulk/T2/T3 glätten nicht                               | Pufferung, Regelung, Bulk-Duty               |
| Gute Rate steigt, aber Fehler auch     | zu aggressiver Durchsatz                               | Vereinzelung/Detektionsfenster stabilisieren |
| Lange Aufenthaltszeit auf einem Teller | Teile zirkulieren/stauen                               | Exit-Geometrie, Geschwindigkeit, Führung     |

---

## 14. Wahrscheinlich braucht ihr Closed-Loop-Control, nicht nur feste Einstellungen

Bei unregelmäßigem Bulk-Zufluss ist eine statisch optimierte Einstellung vielleicht grundsätzlich begrenzt. Besser wäre eine einfache Regelung.

Beispiel:

```text
Ziel:
Teller 4 soll meistens 1–3 Teile haben,
aber möglichst nur ein Teil in der Klassifikations-/Exit-Zone.
```

Dann regelt ihr nicht blind mit festen Geschwindigkeiten, sondern abhängig vom Zustand:

```text
Wenn T4 überfüllt:
    T3 langsamer oder kurz stoppen
    eventuell T4 schneller

Wenn T4 leer und T3 Exit hat Teile:
    T3 schneller

Wenn T3 überfüllt und T4 nicht überfüllt:
    T3 schneller oder T2 langsamer

Wenn T2 überfüllt:
    Bulkfeeder reduzieren, falls steuerbar
    oder T2 erhöhen, falls T3 Kapazität hat

Wenn Bulk-Burst erkannt:
    downstream temporär puffern/drosseln
```

Das kann am Anfang eine einfache Zustandsmaschine sein, kein komplexer Controller.

Zum Beispiel:

```text
if N_T4 > overload_threshold:
    speed_T3 = low
    speed_T4 = high

elif N_T4 == 0 and N_T3_exit > 0:
    speed_T3 = high
    speed_T4 = normal

elif N_T3 > overload_threshold:
    speed_T2 = low
    speed_T3 = high

else:
    speeds = nominal
```

Mit Hysterese, damit es nicht hektisch hin- und herschaltet.

Langfristig könntet ihr daraus einen PI-Regler oder einen kleinen Model-Predictive-Controller machen. Aber schon eine einfache regelbasierte Version kann bei eurem chaotischen Zufluss deutlich robuster sein als feste Drehzahlen.

---

## 15. Die „aufgewickelte Teller“-Visualisierung wäre sehr wertvoll

Ich würde eine Visualisierung bauen, die Zeit gegen Prozessposition zeigt.

Y-Achse:

```text
T2 Drop
T2 Transport
T2 Exit
T3 Drop
T3 Transport
T3 Exit
T4 Drop
T4 Transport
T4 Exit
Distributor
```

X-Achse:

```text
Zeit
```

Farbe:

```text
Teiledichte / Anzahl / Crowding
```

Dann seht ihr sofort:

```text
Wo entstehen Wellen?
Wo staut es?
Wo verschwinden Teile?
Wo werden Bursts verstärkt?
Wo entstehen gute Vereinzelungsfenster?
```

Das wäre vermutlich eines der mächtigsten Debugging-Tools für euch.

Zusätzlich pro Run:

```text
Zeitreihe N_T2, N_T3, N_T4
Zeitreihe Drop/Exit je Teller
Zeitreihe good_single_state_T4
Zeitreihe Bulk-Burstiness
```

---

## 16. Eine sinnvolle Iterationsstruktur

Ich würde euer Vorgehen ungefähr so aufbauen:

### Phase 1: Messsystem stabilisieren

Ziel:

```text
Wir können zuverlässig sagen, wie viele Teile wo sind
und welche Zustände pro Teller auftreten.
```

Dazu:

```text
Tellerkoordinaten kalibrieren
Zonen sauber definieren
YOLO-Daten speichern
Zeitfenster-KPIs erzeugen
Dashboard/Plots bauen
```

Noch keine große Optimierung.

---

### Phase 2: Baseline charakterisieren

Eine unveränderte Standardkonfiguration mehrfach laufen lassen.

Fragen:

```text
Wie groß ist die natürliche Streuung?
Wie bursty ist der Bulk-Zufluss?
Wie oft ist T4 leer?
Wie oft ist T4 überfüllt?
Wo entstehen die meisten schlechten Zustände?
```

Ergebnis dieser Phase sollte sein:

```text
Unser Hauptproblem ist zu 60 % Overload T4,
zu 25 % Transferverlust T3→T4,
zu 15 % sonstiges.
```

Oder eben eine andere Verteilung.

---

### Phase 3: Teilprozesse isoliert untersuchen

Nicht sofort das Gesamtsystem optimieren.

Gezielt anschauen:

```text
Bulk → T2: Wie unregelmäßig ist der Input?
T2 → T3: Wie stabil ist die Übergabe?
T3 → T4: Wie stabil ist die Übergabe?
T4 → Distributor: Wie gut ist die Vereinzelung?
```

Wenn möglich, einzelne Segmente vereinfachen:

```text
konstanter Teilebatch
definierte Startmenge
ein Tellerpaar separat testen
Bulkfeeder temporär standardisieren
```

---

### Phase 4: Experimentdesign

Dann gezielt Parameter testen:

```text
T2-Speed
T3-Speed
T4-Speed
Bulk-Duty
Exit-Geometrie
Führungen
```

Aber nicht wild, sondern mit:

```text
randomisierter Reihenfolge
Wiederholungen
A-B-A-Checks
gleichen oder dokumentierten Teilebatches
Auswertung gegen Zwischen-KPIs
```

---

### Phase 5: Regelung einführen

Wenn ihr wisst, welche Zustände schlecht sind, baut ihr eine einfache Online-Regelung:

```text
Zielbelegung je Teller
Zielzustand auf T4
Drosselung bei Overload
Nachschub bei Starvation
Bulk-Reduktion bei downstream congestion
```

Danach optimiert ihr nicht mehr nur mechanische Parameter, sondern auch die Regelstrategie.

---

## 17. Konkreter Minimalstart

Wenn ihr morgen anfangen wollt, würde ich nicht mit einem großen ML-Projekt starten, sondern mit diesen fünf Dingen:

### Erstens: Pro Run eine vollständige Konfiguration speichern

Keine Testläufe mehr ohne:

```text
run_id
Teller-Geschwindigkeiten
Bulk-Einstellung
mechanische Varianten
Teilebatch
Software-/YOLO-Version
Start-/Endzeit
Kommentar
```

### Zweitens: Pro Sekunde aggregierte Tellerdaten erzeugen

Für Teller 2, 3, 4:

```text
N_total
N_drop
N_exit
crowding_score
single_ratio
arrival_rate_drop
exit_activity
```

### Drittens: T4-Zustände klassifizieren

Mindestens:

```text
T4_STARVED
T4_GOOD_SINGLE
T4_OVERLOADED
T4_UNCLEAR
```

### Viertens: Übergaben als Korrelationen messen

```text
T2 Exit → T3 Drop
T3 Exit → T4 Drop
```

Mit Verzögerung und Effizienz.

### Fünftens: Baseline 10-mal laufen lassen

Ohne Änderung.

Danach wisst ihr:

```text
Was ist normales Rauschen?
Welche Zustände dominieren?
Welche Metrik ist überhaupt stabil genug?
```

Erst danach würde ich ernsthaft optimieren.

---

## 18. Der zentrale Leitsatz

Eure Optimierung sollte nicht mehr lauten:

```text
Wir ändern etwas und schauen, ob der Endtest besser aussieht.
```

Sondern:

```text
Wir messen den Prozess als Fluss aus anonymen Partikeln,
klassifizieren die schlechten Zustände,
identifizieren den dominanten Engpass,
ändern gezielt eine Stellgröße oder eine geplante Parameterkombination,
und vergleichen die Verteilungen unter kontrollierten Störgrößen.
```

Oder noch kürzer:

> **Erst Observability, dann Diagnose, dann Experimentdesign, dann Regelung.**

Die wahrscheinlich größte Verbesserung wird nicht aus einem einzelnen mechanischen Trick kommen, sondern daraus, dass ihr das System in messbare Teilprozesse zerlegt und nicht mehr den finalen Output als einzige Wahrheit verwendet.
