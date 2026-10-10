---
tags: [begleiter, haustiere, kreaturenkämpfe, xeno-arena, holo-arena, fähigkeiten, affinität, eier, anleitung]
language: de
---

# No Man's Sky: Begleiter und Kreaturenkämpfe (Kurzreferenz, Deutsch)

Kurzfassung des englischen Dokuments *No Man's Sky Companions and Creature Battles*. Quellen und Prüfung: offizielle
Seiten zu Xeno Arena (6.3, April 2026) und Cosmos (7.0), Anleitungen von TheGamer, GameRant, KeenGamer,
PlayerAuctions und dtgre, Spielerberichte auf Steam, sowie die Dateien des installierten Spiels (Build 25732212)
und ein echter Spielstand, geprüft am 2026-10-10. Kennzeichnung: **(offiziell)**, **(Spieldateien)**,
**(Spielstand)**, **(zwei Quellen)**, **(eine Quelle)**, **(unbestätigt)**, **(strittig)**.

## Begleiter beim Erkunden

- **Drei Eigenschaftspaare**, jeweils in Prozent **(zwei Quellen)**: hilfsbereit oder verspielt, sanft oder
  aggressiv, treu oder eigenständig. Ein Spielstand speichert pro Begleiter genau drei Zahlen mit Vorzeichen
  **(Spielstand)**; welche Zahl welches Paar ist, ist **(unbestätigt)**.
- **Was sie tun** **(zwei Quellen)**: Wildtiere und Notsignale anzeigen, Punkte markieren, Rohstoffe ausgraben und
  bringen, scannen, Ernte hinterlassen, vor Gefahr warnen, auf Befehl jagen.
- **Nützlich?** **(strittig)**: Ein langer Steam-Thread sagt, Haustiere seien nutzlos; andere berichten, manche Tiere
  holen zuverlässig Dinge. Der Nutzen hängt vom einzelnen Tier ab.
- **Ernte** **(Spieldateien)**: Jede Kreaturenart hat einen eigenen Erntetext und ein eigenes Produkt, zum Beispiel
  gibt eine Kuh *Frische Milch* (und *Rohes Steak* als Fleisch). Der Reiter „Begleiter“ des Plugins zeigt die Ernte
  jedes Begleiters.
- **Vertrauen** **(Spielstand)**: Wert von 0 bis 1; ein geschlüpftes Ei beginnt bei 0,7 **(Spielstand)**.
- **Genetik ändern** **(offiziell)**: Der Eiersequenzer auf der Raumanomalie verändert die Genetik und kann seit dem
  Xeno-Arena-Update Beweglichkeit, Gesundheit und Kampfeigenschaften verbessern.

## Kreaturenkämpfe: Grundlagen

- **3 gegen 3, rundenbasiert** **(zwei Quellen)**; eine Kreatur ist aktiv, ein Wechsel ist in der eigenen Runde möglich.
- **Fünf Fähigkeiten pro Kreatur**, eine pro Runde; starke Fähigkeiten haben eine Abklingzeit **(zwei Quellen)**.
  Jede Kreatur hat ihren eigenen Satz, abhängig von Art und Heimatklima **(offiziell)**. Im Spielstand stehen die fünf
  Fähigkeiten als Vorlagen-Kennungen, etwa `ATTACK_DUST` **(Spielstand, Spieldateien)**.
- **Reihenfolge** bestimmt die **Beweglichkeit**: die höhere zieht zuerst **(zwei Quellen)**.
- **Holo-Arena**-Tische wurden zur Raumanomalie hinzugefügt **(offiziell)**; die Liga kennt die Stufen *Ungetestet*,
  *Stationschampion* und *Stellares Phänomen* **(Spieldateien)** (Namen sinngemäß; das Spiel nutzt die Texte seiner
  Sprachdateien).

## Die drei Kampfwerte

Jede Kreatur hat **Kampfstärke**, **Gesundheit** und **Beweglichkeit**, jeweils mit einer Klasse **S, A, B oder C**
**(eine Quelle)**. Fähigkeiten können zusätzlich Treffsicherheit, kritische Treffer, Ausweichen und Verteidigung
verändern **(Spieldateien)**.

## Die neun Affinitäten

Physisch, Feuer, Frost, Tropisch, Wüste, Toxisch, Radioaktiv, Mechanisch, Anomal **(Spieldateien)**.

Wer gegen wen stark ist, steht **nicht** in den Spieldateien; es stammt aus Anleitungen **(zwei Quellen)**:

- **Feuer -> Frost -> Wüste -> Radioaktiv -> Feuer** (jede ist stark gegen die nächste)
- **Toxisch -> Tropisch -> Anomal -> Mechanisch -> Toxisch**
- **Physisch** ist neutral.

**(strittig)** Eine Tabelle nennt zusätzlich „Radioaktiv schwach gegen Toxisch“ und „Anomal schwach gegen Wüste“;
das sind Übergänge zwischen den Zyklen und **unbestätigt**.

## Was nicht bekannt ist

Genaue Wirkungswerte, die Bedeutung der drei Eigenschaftszahlen, die Wartezeit bis ein Begleiter wieder ein Ei
legen kann (keine Konstante in den Spieldateien) und der Artname, den das Spiel anzeigt (er wird aus Startwerten
erzeugt und steht in keiner Texttabelle - das Plugin zeigt deshalb keinen).
