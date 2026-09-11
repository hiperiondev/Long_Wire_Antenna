# NEC2 Antenna Length Optimizer — Manuale utente completo

**Autore del software:** LU3VEA (released CC0 v1.0)
**Versione del manuale:** 1.3 (verificato rispetto al codice)
**Ambito di questo manuale:** installazione, concetti, interfaccia grafica (GUI) in dettaglio completo, interfaccia a riga di comando (CLI), file di output prodotti e risoluzione dei problemi.

---

## Indice

1. [Cosa fa questo software](#1-cosa-fa-questo-software)
2. [Come funziona, in termini semplici](#2-come-funziona-in-termini-semplici)
3. [Requisiti e installazione](#3-requisiti-e-installazione)
4. [Avvio del programma](#4-avvio-del-programma)
5. [L'interfaccia grafica (GUI) — panoramica](#5-linterfaccia-grafica-gui--panoramica)
6. [Scheda 1 — Banda / Sorgente](#6-scheda-1--banda--sorgente)
7. [Scheda 2 — Intervallo di ricerca](#7-scheda-2--intervallo-di-ricerca)
8. [Scheda 3 — Fisica](#8-scheda-3--fisica)
9. [Scheda 4 — File di output](#9-scheda-4--file-di-output)
10. [Scheda 5 — Esecuzione](#10-scheda-5--esecuzione)
11. [Scheda 6 — UnUn / Transmatch](#11-scheda-6--unun--transmatch)
12. [Barra dell'intestazione e controlli globali](#12-barra-dellintestazione-e-controlli-globali)
13. [Comprendere i file di output](#13-comprendere-i-file-di-output)
14. [L'interfaccia a riga di comando (CLI) — riferimento completo](#14-linterfaccia-a-riga-di-comando-cli--riferimento-completo)
15. [Flussi di lavoro tipici, passo dopo passo](#15-flussi-di-lavoro-tipici-passo-dopo-passo)
16. [Risoluzione dei problemi](#16-risoluzione-dei-problemi)
17. [Glossario](#17-glossario)
18. [Appendice: bande radioamatoriali conosciute](#18-appendice-bande-radioamatoriali-conosciute)
19. [Appendice: database dei nuclei toroidali (scheda UnUn)](#19-appendice-database-dei-nuclei-toroidali-scheda-unun-tab)

---

> **Nota sull'ambito:** questo programma è uno strumento di modellazione e ottimizzazione. Non sostituisce la verifica dell'antenna realmente installata. I risultati dipendono dalle ipotesi geometriche, dal modello del terreno, dalle perdite, dalla segmentazione e dagli oggetti vicini.

## 1. Cosa fa questo software

Il **NEC2 Antenna Length Optimizer** è uno strumento di progettazione per antenne filari (un radiatore inclinato con un contrappeso inclinato opzionale) alimentate in un unico punto di alimentazione — la classica configurazione "random wire" / end-fed usata da molti radioamatori.

Dati:

- una o più **bande** radioamatoriali (o personalizzate) sulle quali si desidera operare, e
- una **lunghezza iniziale del filo** e una **lunghezza del contrappeso**,

il programma cerca combinazioni vicine di lunghezza del filo e del contrappeso, valuta le prestazioni elettriche (impedenza e VSWR) di ciascuna su ogni banda richiesta e restituisce la combinazione che offre le migliori **prestazioni aggregate su tutte le bande contemporaneamente** — non solo su una banda a scapito delle altre.

Può valutare i candidati in due modi:

- **Modalità empirica** — un'approssimazione matematica molto rapida per il cribaggio (screening) delle geometrie. Non modella il terreno reale né la geometria reale del contrappeso, e i suoi valori di reattanza non devono essere usati per progettare una rete di adattamento.
- **Modalità NEC2** — esegue il motore di simulazione d'antenna a momenti `nec2c` per ogni geometria candidata (più lento, ma fisicamente accurato).

Oltre alla geometria dell'antenna, il software include anche due calcolatori di reti di adattamento accessibili dalla stessa finestra:

- Un progettista di **autotrasformatori UnUn (unbalanced-to-unbalanced)** basato su nuclei toroidali in ferrite o polvere di ferro.
- Un progettista di **Transmatch (rete di adattamento L/C a bobina con prese)**.

Entrambi gli strumenti di adattamento possono leggere automaticamente le impedenze dell'antenna trovate dall'ottimizzatore e proporre una soluzione di adattamento.

---

## 2. Come funziona, in termini semplici

1. **Descrivi il problema dell'antenna**: quali bande utilizzare, quali sono approssimativamente le lunghezze del filo e del contrappeso e quanto estendere la ricerca attorno a tali valori.
2. Il programma costruisce una **griglia di geometrie candidate** (ogni combinazione di lunghezza del filo × lunghezza del contrappeso nella finestra di ricerca, distanziata secondo i passi scelti).
3. **Ogni candidato viene valutato** su ogni banda richiesta:
   - In *modalità NEC2*, il programma scrive un file di input `.nec` che descrive la geometria (raggio del filo, materiale, tipo di terreno, segmentazione, frequenza) e invoca il simulatore esterno `nec2c`, quindi legge la resistenza (R) e la reattanza (X) al punto di alimentazione e calcola il Rapporto d'Onda Stazionaria (ROS/VSWR).
   - In *modalità empirica*, R e X vengono stimati con approssimazioni in forma chiusa invece di una simulazione completa (molto più veloce, meno precisa vicino alla risonanza).
4. Ogni candidato riceve un **punteggio aggregato** che combina la penalità di ROS su ogni banda attiva (ROS peggiore = punteggio peggiore), una penalità di "avoidance" per geometrie che cadono in posizioni sfavorevoli vicino ai bordi di banda e, facoltativamente, un termine legato al guadagno irradiato al basso angolo di decollo scelto.
5. Il programma mantiene inoltre l'**insieme ottimale di Pareto**: candidati per i quali nessun altro candidato è contemporaneamente almeno altrettanto buono su ogni banda. Questo mostra i compromessi reali disponibili, non solo un singolo "vincitore".
6. Il candidato migliore (e, facoltativamente, i suoi vicini) viene **nuovamente simulato ad alta precisione** (segmentazione "fine"), in modo che i numeri usati realmente per la costruzione siano affidabili, anche se la ricerca ampia ha usato un'impostazione più grossolana e veloce.
7. Infine il programma **scrive i risultati**: un report di testo classificato, un grafico a dispersione/mappa di calore, un CSV con i dati per banda della geometria vincente, un file NEC2 pronto all'uso, diagrammi del pattern di radiazione, un disegno costruttivo e, facoltativamente, una brochure PDF di una pagina che riassume il progetto.

---

## 3. Requisiti e installazione

### 3.1 Python

Lo strumento è implementato in un singolo script Python 3. Richiede:

- **Python 3** (qualsiasi versione ragionevolmente recente).
- Il toolkit grafico **Tkinter**, se si intende usare l'interfaccia grafica. Tkinter è incluso nella maggior parte delle installazioni desktop di Python; su alcune distribuzioni Linux deve essere installato separatamente:
  ```bash
  sudo apt install python3-tk
  ```
  Se Tkinter manca, la GUI si rifiuterà di avviarsi e stamperà esattamente questa istruzione.

### 3.2 Pacchetti Python opzionali ma consigliati

| Pacchetto | Scopo | Cosa succede se manca |
|---|---|---|
| `colorama` | Output colorato della console nel terminale | Viene utilizzato testo semplice, senza colori. Nessuna perdita funzionale. |
| `matplotlib` | Grafico dello spazio di ricerca, diagrammi di radiazione e disegni costruttivi, compresi i disegni degli strumenti di adattamento | Le uscite grafiche non possono essere generate senza questo pacchetto. |
| `numpy` | Usato internamente dal renderer dei diagrammi di radiazione | I diagrammi di radiazione non possono essere generati senza. In pratica è quasi sempre già presente, poiché viene installato automaticamente come dipendenza di `matplotlib`. |
| `reportlab` | Generazione della brochure PDF | Il PDF viene saltato se `reportlab` non è installato. |
| `Pillow` (`PIL`) | Inserisce i PNG di costruzione/radiazione nella brochure PDF | Il PDF viene comunque generato, ma la sezione immagine interessata viene sostituita da un avviso "non disponibile". |

Installazione tipica:

```bash
pip install colorama matplotlib numpy reportlab pillow
```

`matplotlib` e `reportlab` sono indipendenti: `matplotlib` genera le immagini e `reportlab` genera il PDF. L'assenza dell'uno non implica necessariamente l'assenza dell'altro.

> **Nota sull'installer Windows:** `Setup_Long_Wire_Antenna.exe` installa con `pip` anche un pacchetto chiamato `tabulate`, oltre ai quattro sopra elencati. Lo script in realtà non importa né usa `tabulate` da nessuna parte nel codice — è un residuo inutilizzato nell'elenco delle dipendenze dell'installer, non un requisito reale dello strumento. Non è necessario installarlo se si configura lo script manualmente.
>
> L'installer esegue anche un passo successivo all'installazione (`post_install_setup.py`) che prova opzionalmente a scaricare una build più recente del motore NEC2 da un progetto GitHub esterno, come aggiornamento rispetto al `nec2c.exe` incluso, tornando al binario incluso se il tentativo fallisce. La sua logica di ripiego cerca un file chiamato `onec.exe`/`onec_bundled.exe`, che questo installer in realtà non include (include solo `nec2c.exe`), quindi quel particolare percorso di ripiego attualmente non fa nulla — innocuo, poiché il launcher installato (`run_gui.bat`) individua e usa autonomamente `nec2c\nec2c.exe`, indipendentemente dall'esito di questo passo. Puoi tranquillamente ignorare eventuali menzioni di `onec.exe` nei log dell'installer.

### 3.3 Motore di simulazione NEC2 (`nec2c`)

Per utilizzare la **modalità NEC2** (consigliata per ottenere cifre finali affidabili) è necessario avere installato sul sistema il binario `nec2c` — un'implementazione compilata del simulatore d'antenna a metodo dei momenti NEC-2. Fonti tipiche:

- Il gestore di pacchetti della propria distribuzione Linux (il nome del pacchetto varia, ad es. `nec2c`).
- La compilazione dal progetto sorgente pubblico `nec2c`.

**La modalità empirica non richiede `nec2c`**. Può essere utilizzata senza un motore NEC2 esterno, ma rimane un'approssimazione.

> **Alternativa Linux con un clic:** invece di installare manualmente `nec2c` e i pacchetti Python sopra elencati, è possibile usare il file `Long_Wire_Antenna-x86_64.AppImage` precompilato (oppure crearne uno proprio con `others/build_appimage.sh`), che include un proprio interprete Python, tutti i pacchetti opzionali e un binario `nec2c` compilato staticamente, tutto in un unico file portatile. Vedere il `README` del progetto per i dettagli. L'AppImage avvia sempre direttamente la GUI.

### 3.4 Individuazione del binario `nec2c`

Il programma cerca `nec2c` automaticamente, nell'ordine seguente:

1. Un percorso esplicito indicato con `--nec2c /percorso/a/nec2c` (CLI) oppure digitato nel campo **Binario NEC2** (GUI).
2. La variabile d'ambiente `$NEC2C`.
3. Il `PATH` di sistema (cerca i nomi eseguibili `nec2c`, `nec2c-mpich` e `onec` — questo è l'elenco attuale e corretto; note precedenti che citavano `xnec2c` erano errate e sono state superate).
4. Un elenco di percorsi di installazione comuni (`/usr/bin`, `/usr/local/bin`, `/opt/nec2c/bin`, `/opt/homebrew/bin`, ecc.), inclusi percorsi specifici di `onec` come `C:\Program Files\OpenNEC\onec.exe` su Windows.
5. Come ultima risorsa, solo dalla riga di comando, chiederà interattivamente di digitare il percorso (a meno che sia impostato `--no-interactive`).

Nella GUI, usare il pulsante **Rilevamento automatico** nella scheda Fisica per attivare questa ricerca su richiesta.

---

## 4. Avvio del programma

### 4.1 Avvio della GUI

```bash
python src/Long_Wire_Antenna.py --gui
```

Questo apre la finestra interattiva descritta nel resto del manuale. Non servono altri parametri per aprire la GUI — ogni impostazione viene poi inserita tramite l'interfaccia stessa.

`--gui` viene rilevato in una fase di pre-analisi prima che venga letto il resto della riga di comando, quindi eventuali altri flag aggiunti insieme ad esso (es. `python src/Long_Wire_Antenna.py --gui --bands 40m`) vengono ignorati silenziosamente — la GUI si apre comunque con i propri valori predefiniti. Usare i campi della GUI stessa, non flag CLI aggiuntivi, per configurare un'esecuzione in modalità GUI.

### 4.2 Esecuzione dalla riga di comando (senza GUI)

```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
```

Vedere la [Sezione 14](#14-linterfaccia-a-riga-di-comando-cli--riferimento-completo) per l'elenco completo dei parametri. La GUI è, di fatto, un front-end che assembla esattamente questo tipo di riga di comando e la esegue — ogni opzione visibile nella GUI corrisponde a uno di questi flag, e la **casella di anteprima del comando nella scheda Esecuzione mostra il comando letterale che viene costruito** in tempo reale.

### 4.3 Ottenere la guida della riga di comando

```bash
python src/Long_Wire_Antenna.py --help
```

### 4.4 Lingua dell'interfaccia

Il testo del programma (sia i messaggi CLI sia la GUI) è disponibile in **inglese, spagnolo e italiano**. Vedere la [Sezione 12.3](#123-lingua) per come cambiarla nella GUI, e `--lang` per la CLI.

---

## 5. L'interfaccia grafica (GUI) — panoramica

Quando viene avviato con `--gui`, il programma apre una singola finestra contenente:

- Una **barra dell'intestazione** (titolo, cambio lingua, controlli della dimensione del carattere).
- Una riga per il **percorso dello script dell'ottimizzatore** (quale file di script Python la GUI eseguirà effettivamente — vedere [12.1](#121-percorso-dello-script)).
- Un **insieme di sei schede**, ciascuna con impostazioni correlate:
  1. **Banda / Sorgente** — per quali bande progettare e la geometria di partenza.
  2. **Intervallo di ricerca** — quanto ampia e quanto fine deve essere la ricerca, più le opzioni di contrappeso/ritorno a terra.
  3. **Fisica** — motore di simulazione, modello di terreno, conduttore e impostazioni di precisione.
  4. **File di output** — dove vengono scritti i risultati e come vengono chiamati.
  5. **Esecuzione** — l'anteprima del comando, i controlli Run/Stop e una console dal vivo.
  6. **UnUn / Transmatch** — due calcolatrici di rete di adattamento indipendenti (sotto-schede).

La GUI **non calcola mai direttamente un progetto d'antenna** — costruisce una riga di comando a partire dalle impostazioni e avvia lo script dell'ottimizzatore come processo separato, esattamente come se quella riga di comando fosse stata digitata a mano. Questo significa che:

- L'**anteprima del comando** nella scheda Esecuzione riflette sempre le impostazioni correnti e può essere copiata ed eseguita manualmente, se preferito.
- Le ricerche lunghe vengono eseguite in background; la finestra resta reattiva ed è possibile seguire l'avanzamento nella console.
- In linea di principio, è possibile puntare il campo "script dell'ottimizzatore" verso una *copia o versione diversa* dello script, e la GUI guiderebbe quella al posto dell'originale.

Ogni campo di testo, casella di controllo, pulsante radio e menu a discesa delle sei schede è descritto dettagliatamente di seguito, scheda per scheda.

---



## 6. Scheda 1 — Banda / Sorgente

Questa scheda definisce le bande, le frequenze e le lunghezze iniziali utilizzate come centro della ricerca.

### 6.1 Campo "Band(s)"

- Elenco di nomi di banda separati da virgole, ad esempio `40m,20m,15m`.
- Predefinito: `40m,20m,15m`.
- È obbligatorio indicare almeno una banda.
- Sono accettate le bande integrate nell'Appendice 18 oppure nomi personalizzati.

### 6.2 Campo "Frequencies (MHz)"

- Una frequenza centrale in MHz per ogni banda, nello stesso ordine.
- È facoltativo quando tutte le bande sono riconosciute dal programma.
- È obbligatorio per una banda personalizzata/non riconosciuta.
- Il programma usa automaticamente la frequenza centrale integrata per le bande riconosciute.

### 6.3 "Wire length (m)"

Lunghezza iniziale del radiatore inclinato e centro della finestra di ricerca. Predefinita: `21.0 m`.

### 6.4 "Counterpoise length (m)"

Lunghezza iniziale del contrappeso e centro della relativa finestra di ricerca. Predefinita: `5.0 m`. Se il contrappeso è disabilitato, il campo viene disabilitato ma il valore resta memorizzato.

### 6.5 "Active Bands"

Permette di simulare tutte le bande indicate in "Band(s)", ma di utilizzare nel punteggio solo un sottoinsieme. Campo vuoto = tutte le bande sono attive.

### 6.6 "Optimizer language"

Lingua dell'output del programma ottimizzatore e dei report: `auto`, `en`, `es`, `it`. Predefinita: `auto`. È indipendente dalla lingua visualizzata dalla GUI.

---

## 7. Scheda 2 — Intervallo di ricerca

### 7.1 "Search margin"

Se non sono impostati limiti espliciti, la ricerca si estende di ± questo valore attorno alle lunghezze iniziali. Predefinito: `2.0 m`.

### 7.2 Intervallo del radiatore

| Campo | Significato | Predefinito |
|---|---|---|
| `wire-min` | Lunghezza minima del radiatore | iniziale − margine |
| `wire-max` | Lunghezza massima del radiatore | iniziale + margine |
| `wire-step` | Passo della ricerca | `0.25 m` |

### 7.3 "Use counterpoise"

Se selezionato, il modello contiene radiatore e contrappeso collegati allo stesso punto di alimentazione. Se deselezionato, il contrappeso viene rimosso e deve essere definito un percorso di ritorno RF per NEC2.

### 7.4 Percorso di ritorno senza contrappeso

Tre scelte:

- `ground-rod` — connessione galvanica del punto di alimentazione a terra perfetta NEC2 (`GN 1`). **Non** è un modello dell'impedenza di una vera picchetta di terra.
- `coax-stub` — breve conduttore verticale che rappresenta in modo semplificato la calza/coassiale e il percorso di corrente di modo comune.
- `reject` — rifiuta il modello senza contrappeso invece di introdurre automaticamente un percorso di ritorno.

Con `ground-rod`, il programma forza il modello di terra a `perfect` e registra un'avvertenza.

### 7.5 Radiazione / angolo di elevazione

| Campo | Significato | Predefinito |
|---|---|---|
| Target TOA | Angolo di elevazione sopra l'orizzonte usato per il termine di guadagno | `25°` |
| Gain weight | Peso del guadagno nel punteggio, per dB | `0.20` |
| Re-rank top N | Candidati ri-simulati con pattern completo per la riclassificazione | `6` |

Il guadagno a un determinato TOA non è necessariamente il massimo guadagno dell'antenna. Per la riclassificazione viene considerato il massimo sul piano degli azimut a quell'elevazione.

### 7.6 Intervallo del contrappeso

| Campo | Significato | Predefinito |
|---|---|---|
| `cp-min` | Lunghezza minima | iniziale − margine |
| `cp-max` | Lunghezza massima | iniziale + margine |
| `cp-step` | Passo | `0.25 m` |

Questi campi hanno effetto solo quando il contrappeso è abilitato.

### 7.7 Geometria dell'antenna

| Campo | Significato | Predefinito |
|---|---|---|
| Height | Altezza del punto di alimentazione dal terreno | `8.0 m` |
| Wire slope end height | Altezza dell'estremità lontana del radiatore | vuoto = orizzontale |
| Counterpoise end height | Altezza dell'estremità lontana del contrappeso | vuoto = alla quota del punto di alimentazione |

`0.0` per l'estremità del radiatore significa che l'estremità arriva al terreno. Impostare "Wire slope end height" forza la modalità NEC2, perché il modello empirico non rappresenta questa geometria inclinata.

### 7.8 "Maximum retries"

Da `0` a `10`, predefinito `0`. Se il vincitore cade esattamente sul bordo della finestra di ricerca, il programma può spostare la finestra e ripetere automaticamente la ricerca fino al numero di tentativi indicato.

### 7.9 "Top N"

Numero di candidati mostrati nella classifica del report. Predefinito: `20`; la GUI consente da `5` a `200`.

---

## 8. Scheda 3 — Fisica

### 8.1 Modalità di valutazione

- `auto` — usa NEC2 se trova un motore funzionante; altrimenti passa al modello empirico.
- `nec2` — richiede obbligatoriamente un motore NEC2 funzionante.
- `empirical` — usa sempre le formule approssimate.

Il modello empirico è utile per lo screening, ma non rappresenta il terreno, la geometria NEC2 o il comportamento reale del contrappeso e le sue reattanze non devono essere usate per dimensionare un adattatore.

### 8.2 Motore NEC2

Il campo "NEC2 binary" accetta il percorso completo del programma. "Browse" apre un selettore di file; "Auto-detect" esegue la stessa ricerca automatica dell'ottimizzatore.

I nomi cercati nel `PATH` sono `nec2c`, `nec2c-mpich` e `onec` (vedere la [Sezione 3.4](#34-individuazione-del-binario-nec2c) per i dettagli). `onec` è l'eseguibile di OpenNEC.

### 8.3 Terreno

| Campo | Predefinito |
|---|---:|
| Conductivity | `0.005 S/m` |
| Permittivity | `13.0` |

Preset integrati:

| Preset | Conductivity (S/m) | Permittività |
|---|---:|---:|
| Poor ground | 0.001 | 5 |
| Average ground | 0.005 | 13 |
| Good ground | 0.010 | 20 |
| Excellent ground | 0.030 | 25 |
| Salt water | 5.000 | 80 |

`sommerfeld` usa il modello Sommerfeld-Norton con terreno finito; `perfect` usa un terreno perfettamente conduttivo (`GN 1`) e costituisce un'idealizzazione.

### 8.4 Conduttore

- Diametro predefinito: `2.0 mm`.
- Materiale predefinito: rame.
- Materiali disponibili: `copper`, `aluminium`, `aluminum`, `brass`, `silver`, `steel`, `perfect`.
- È possibile specificare direttamente la conducibilità in S/m per sovrascrivere il materiale.

Le perdite del conduttore influenzano resistenza e guadagno. Un modello a conduttore perfetto non rappresenta le perdite ohmiche del filo reale.

### 8.5 Segmentazione

- `fine`: `90` segmenti per mezza lunghezza d'onda; è la densità usata per i risultati finali.
- `fast`: `21` segmenti per mezza lunghezza d'onda; serve allo screening/pattern e può produrre errori importanti su R e persino sul segno di X.
- `custom`: densità scelta dall'utente.
- Senza override, la scansione usa internamente `45` segmenti per mezza lunghezza d'onda e le esecuzioni finali `90`.

"Re-check convergence" esegue il vincitore a densità 2× e 4× e confronta la deriva di R e X. La soglia di circa 3% riguarda R; X ha una propria tolleranza. Se X non converge, non va usata per dimensionare una rete di adattamento.

---

## 9. Scheda 4 — File di output

Il campo "Working directory" indica la cartella di destinazione e per impostazione predefinita corrisponde alla directory home dell'utente.

| Opzione | File predefinito | Contenuto |
|---|---|---|
| `out-txt` | `optimizer_report.txt` | Top-N, Pareto, risultati e interpretazione del vincitore |
| `out-png` | `optimizer_plot.png` | Spazio di ricerca e grafici VSWR |
| `out-csv` | `optimizer_best.csv` | Dati per banda del vincitore; viene letto automaticamente dagli strumenti di adattamento |
| `out-nec` | `best_antenna.nec` | Modello NEC2 della geometria vincente con richieste RP per le bande attive |
| `out-radiation` | `radiation_diagrams.png` | Diagrammi di radiazione NEC2 |
| `out-construction` | `antenna_construction.png` | Disegno quotato di costruzione |
| `out-pdf` | `antenna_brochure.pdf` | Riepilogo PDF di una pagina |

`matplotlib` è necessario per i grafici, il disegno costruttivo e i diagrammi di radiazione. I diagrammi di radiazione vengono generati solo in modalità NEC2. `reportlab` è necessario per il PDF.

Il report di testo non contiene tutti i candidati in forma tabellare: mostra i candidati Top-N e il fronte di Pareto.

---

## 10. Scheda 5 — Esecuzione

### 10.1 Opzioni

La GUI parte con `Quiet` e `No interactive prompts` selezionati.

- `Quiet` aggiunge `--quiet`.
- `No interactive prompts` aggiunge `--no-interactive`.

### 10.2 Anteprima del comando

La casella mostra il comando esatto che la GUI sta per eseguire. Viene aggiornata automaticamente quando cambiano le impostazioni.

### 10.3 Run / Stop

"Run" avvia il processo ottimizzatore in background. "Stop" termina il processo corrente. A fine esecuzione i pulsanti per report, pattern e PDF vengono abilitati quando i relativi file esistono.

### 10.4 Console

La console GUI riproduce l'output del processo con una semplice codifica cromatica per errori, avvisi e messaggi di successo.

### 10.5 Caricamento automatico

Al termine di una ricerca riuscita, la GUI tenta di caricare `optimizer_best.csv` nella scheda UnUn / Transmatch.

---

## 11. Scheda 6 — UnUn / Transmatch

Questa scheda è **indipendente dall'esecuzione dell'ottimizzatore** — può essere usata in qualsiasi momento, con qualsiasi dato di impedenza, indipendentemente dal fatto che sia già stata eseguita un'ottimizzazione. Contiene due sotto-schede.

### 11.1 Sotto-scheda: UnUn Toroid

Progetta un autotrasformatore a banda larga (UnUn) avvolto su un nucleo toroidale in ferrite o polvere di ferro per trasformare l'impedenza al punto di alimentazione dell'antenna verso un'impedenza coassiale standard (tipicamente 50 Ω).

#### 11.1.1 Sezione "Antenna"

- **Selettore di banda (menu a discesa)** — una volta caricati i dati dell'antenna (vedi sotto), consente di scegliere di quale banda usare l'impedenza; selezionando una banda vengono compilati automaticamente i campi sottostanti con frequenza, R e X di quella banda.
- **Pulsante Reload** — rilegge il file `optimizer_best.csv` dalla posizione di output configurata, aggiornando il menu delle bande e i dati.
- **Pulsante Export** — esporta i risultati correnti del calcolo UnUn.
- **Riga di stato** — indica se i dati dell'antenna sono stati caricati correttamente e da dove.
- Campi modificabili manualmente (compilati automaticamente dal selettore di banda, ma liberamente modificabili per esplorare scenari "what if" senza dover rieseguire l'ottimizzatore):
  - **Frequenza (MHz)** — predefinita `7.100`.
  - **R_out, X_out (Ω)** — l'impedenza lato antenna (uscita) da cui l'UnUn deve trasformare. Predefinite `450`, `150`.
  - **R_in, X_in (Ω)** — l'impedenza lato coassiale (ingresso) verso cui l'UnUn deve trasformare. Predefinite `50`, `0`.

#### 11.1.2 Sezione "Core" (nucleo)

- **Menu a discesa Core** — scegliere il codice del toroide dal database integrato (vedere la [Sezione 19](#19-appendice-database-dei-nuclei-toroidali-scheda-unun-tab) per l'elenco completo e le specifiche). Predefinito: `FT-240-31`.
- **Riga informativa** — mostra le specifiche principali del nucleo selezionato (materiale, dimensioni, ecc.).
- **Numero di spire primarie (Np)** — predefinito `15`.
- **Diametro del filo (mm)** — predefinito `2.0`.
- Un **disegno costruttivo** del toroide avvolto viene disegnato a destra di questi campi e si aggiorna automaticamente al variare di nucleo/spire/filo, così da vedere esattamente cosa si andrebbe ad avvolgere.

#### 11.1.3 Pannello "Results" (risultati)

Un pannello di testo a spaziatura fissa, scorrevole e a colori, che riporta il progetto UnUn calcolato: rapporto di spire, impedenza trasformata, qualità di adattamento attesa, stima delle perdite/riscaldamento del nucleo, ed eventuali avvertenze (ad es. spire insufficienti, nucleo vicino alla saturazione o alla sovratemperatura, o l'avvertenza sull'autorisonanza descritta in 11.1.4).

#### 11.1.4 Sezione "Multi-band"

Poiché un singolo progetto UnUn viene usato su tutte le bande coperte dall'antenna, questa sezione valuta quanto bene **un UnUn scelto** si comporti su **tutte** le bande caricate dal CSV dell'ottimizzatore contemporaneamente — non solo sulla singola banda selezionata sopra.

- Casella **Auto** (selezionata per impostazione predefinita) — se abilitata, il programma cerca automaticamente il miglior valore di componente della rete di adattamento e il miglior rapporto di spire su tutte le bande; se deselezionata, i valori vengono forniti manualmente.
- Menu a discesa **Type** — `L`, `C` o `none`: se la rete di compensazione multi-banda è induttiva, capacitiva o assente.
- Campo **Value** — il valore di componente scelto manualmente (usato solo quando Auto è deselezionato).
- Campo **Ratio** — il rapporto di spire dell'UnUn scelto manualmente (usato solo quando Auto è deselezionato).
- Campo **Z0** — l'impedenza di riferimento/obiettivo per la valutazione multi-banda. Predefinita `50` Ω.
- **Tabella dei risultati** — una riga per banda, con: nome banda, frequenza, R, X, reattanza compensante, impedenza di ingresso risultante, VSWR senza e con compensazione, e la differenza tra le due.

> **Nota tecnica importante integrata nello strumento:** un trasformatore toroidale a presa/avvolgimento si comporta come un autotrasformatore ideale solo **al di sotto** della propria frequenza di autorisonanza (SRF). Al di sopra della SRF, l'avvolgimento diventa a dominanza capacitiva e il semplice modello a rapporto di spire non è più valido — eppure progetti ingenui precedenti potevano silenziosamente riportare un VSWR plausibile (ma sbagliato) per una banda che in realtà si trova sopra la SRF dell'avvolgimento. Questo strumento verifica la SRF dell'avvolgimento e accorcia/regola automaticamente l'avvolgimento di riferimento finché la SRF non supera la banda richiesta più alta con un margine di sicurezza (1.5×), e segnala le righe in cui la reattanza propria dell'avvolgimento non è comodamente superiore all'impedenza dell'antenna (segno che la presa viene "caricata" dalla bobina invece di trasformare in modo pulito).

### 11.2 Sotto-scheda: Transmatch

Progetta una rete di adattamento a bobina con prese (in stile autotrasformatore) — un classico "Transmatch" o "ATU" — come alternativa o complemento all'UnUn.

#### 11.2.1 Sezione "Global" (globale)

| Campo | Significato | Predefinito |
|---|---|---|
| Z0 | Impedenza di riferimento/obiettivo | `50` Ω |
| Diametro filo | Diametro del filo della bobina | `1.0` mm |
| Diametro supporto | Diametro del supporto della bobina | `50` mm |
| Spaziatura spire | Spaziatura tra le spire | `1.0` mm |
| Avvolgimento di riferimento (spire) | Numero di spire usato come presa di riferimento Z0 | vuoto |
| Casella **Auto reference** | Se selezionata, la lunghezza dell'avvolgimento di riferimento sopra viene calcolata automaticamente invece di essere inserita manualmente | selezionata per impostazione predefinita |

#### 11.2.2 Tabella "Taps" (prese)

Una tabella modificabile con fino a **11 righe**, ciascuna rappresentante una banda che si desidera coprire con il Transmatch, con colonne: **Presa n.**, **Banda**, **Frequenza (MHz)**, **R (Ω)**, **X (Ω)**, e una casella **Active** per includere/escludere quella riga dal calcolo. Tre righe sono precompilate con valori di esempio (40 m / 20 m / 10 m), così la pagina è utilizzabile anche prima di aver mai eseguito l'ottimizzatore:

| # | Banda | Freq (MHz) | R (Ω) | X (Ω) |
|---|---|---|---|---|
| 1 | 40m | 7.150 | 75 | −12 |
| 2 | 20m | 14.170 | 67 | 23 |
| 3 | 10m | 28.000 | 45 | 10 |

Un **disegno costruttivo** della bobina e delle sue prese viene disegnato accanto a questa tabella e si aggiorna dal vivo.

#### 11.2.3 Tabella dei risultati "Winding" (avvolgimento)

Per ogni riga di presa attiva: banda, frequenza, R, R realizzata (dopo la quantizzazione della presa), l'errore risultante, spire dal riferimento, spire totali/delta, lunghezza del filo, resistenza in DC, lunghezza cumulativa, impedenza e fase risultanti, VSWR, return loss, mismatch loss e frazione di potenza riflessa.

#### 11.2.4 Tabella dei risultati "Compensation" (compensazione)

Per ogni riga di presa attiva: banda, frequenza, R, X, la reattanza compensante necessaria, e i valori equivalenti di induttore/condensatore serie o induttore/condensatore in derivazione che ridurrebbero ulteriormente il VSWR (utile se la sola bobina con presa non annulla completamente la reattanza), più il VSWR risultante a una cifra di riferimento (con tolleranza di 5 Ω).

#### 11.2.5 Pannello di testo "Coil construction" (costruzione della bobina)

Un riepilogo a spaziatura fissa e a colori di come avvolgere fisicamente la bobina: spire totali, dove posizionare ogni presa, lunghezza di filo necessaria, ed eventuali avvertenze (spire insufficienti, spaziatura delle prese non realistica, ecc.).

#### 11.2.6 Nota guida per la costruzione

Una breve etichetta/promemoria in fondo alla sotto-scheda con indicazioni pratiche di costruzione.

> I calcolatori di adattamento sono strumenti di progetto. Le capacità parassite, le perdite del nucleo, la SRF, il Q reale e la disposizione meccanica devono essere verificati sul componente costruito.

---


## 12. Barra dell'intestazione e controlli globali

### 12.1 Percorso dello script

La riga superiore indica quale copia di `Long_Wire_Antenna.py` la GUI eseguirà. Per impostazione predefinita è lo script usato per avviare la GUI.

### 12.2 Dimensione del carattere

I pulsanti `−` e `+` modificano la dimensione dei caratteri della GUI senza riavviare il programma.

### 12.3 Lingua

La GUI può essere visualizzata in inglese, spagnolo o italiano. Questa impostazione è distinta da "Optimizer language", che controlla report e console del processo ottimizzatore.

---

## 13. Comprendere i file di output

### 13.1 Report

Contiene il riepilogo della ricerca, i candidati Top-N, il fronte di Pareto, l'interpretazione del vincitore e, se richiesto, il controllo di convergenza.

### 13.2 Grafico

Rappresenta l'intera griglia cercata, con il punteggio aggregato, il fronte di Pareto e i VSWR del vincitore.

### 13.3 CSV

Contiene i risultati per banda della sola geometria vincente e il rapporto UnUn utilizzato. È il formato utilizzato dalle calcolatrici di adattamento.

### 13.4 File NEC2

Contiene la geometria vincente alla densità finale e le schede RP per le bande attive. È un modello NEC2 e non una garanzia che l'antenna reale abbia gli stessi risultati.

### 13.5 Pattern di radiazione

Sono generati solo quando è disponibile un motore NEC2. Non sono disponibili dal modello empirico.

### 13.6 Disegno costruttivo

Mostra le dimensioni principali della geometria vincente, inclusi lunghezze e quote.

### 13.7 PDF

Il PDF è una sintesi di una pagina e richiede `reportlab`. Le immagini vengono incluse solo se sono state generate con successo.

### 13.8 Limiti del modello

- NEC2 non sostituisce una misura dell'antenna installata.
- Il risultato reale dipende da terreno, supporti, edifici, cavi, radiali, correnti di modo comune e geometria reale.
- `ground-rod` significa terra perfetta in NEC2, non una vera impedenza di picchetta.
- Il modello empirico non è un sostituto di NEC2 per una geometria reale.
- I valori R/X e dei componenti di adattamento devono essere verificati con analizzatore/VNA prima dell'uso definitivo.

---

## 14. Interfaccia a riga di comando (CLI) — riferimento completo

| Opzione | Predefinito | Descrizione |
|---|---|---|
| `--bands NAMES` | obbligatorio | Bande separate da virgole |
| `--freqs MHZ` | vuoto | Frequenze centrali; necessarie per bande personalizzate |
| `--wire-len M` | obbligatorio | Lunghezza iniziale del radiatore |
| `--cp-len M` | obbligatorio salvo `--no-counterpoise` | Lunghezza iniziale del contrappeso |
| `--active-bands BANDS` | tutte | Bande utilizzate per il punteggio |
| `--mode` | `auto` | `empirical`, `nec2` o `auto` |
| `--nec2c PATH` | auto | Percorso del motore |
| `--margin M` | `2.0` | Margine di ricerca |
| `--wire-min/max M` | auto | Limiti del radiatore |
| `--wire-step M` | `0.25` | Passo del radiatore |
| `--cp-min/max M` | auto | Limiti del contrappeso |
| `--cp-step M` | `0.25` | Passo del contrappeso |
| `--height M` | `8.0` | Altezza del punto di alimentazione |
| `--wire-slope-end-height M` | vuoto | Quota dell'estremità del radiatore; forza NEC2 |
| `--cp-end-height M` | vuoto | Quota dell'estremità del contrappeso |
| `--no-counterpoise` | disattivo | Elimina il contrappeso |
| `--no-cp-return` | `ground-rod` | `ground-rod`, `coax-stub`, `reject` |
| `--cp-stub-len M` | `2.0` | Lunghezza dello stub |
| `--ground-model` | `sommerfeld` | `sommerfeld` o `perfect` |
| `--ground-cond S/M` | `0.005` | Conducibilità del terreno |
| `--ground-diel EPS` | `13.0` | Permittività relativa |
| `--wire-diameter MM` | `2.0` | Diametro del filo |
| `--wire-material` | `copper` | Materiale del conduttore |
| `--wire-conductivity S/M` | da materiale | Conducibilità personalizzata |
| `--segs-per-half-wave N` | `45/90` | Densità di scansione/finale |
| `--fast` | disattivo | Scansione a 21 segmenti/mezza onda |
| `--converge` | disattivo | Controllo a 2× e 4× |
| `--target-toa DEG` | `25` | Angolo di elevazione |
| `--gain-weight W` | `0.20` | Peso del guadagno |
| `--rerank-top N` | `6` | Candidati ri-simulati per il guadagno |
| `--top-n N` | `20` | Candidati nel report |
| `--out-txt FILE` | `optimizer_report.txt` | Report |
| `--out-png FILE` | `optimizer_plot.png` | Grafico |
| `--out-csv FILE` | `optimizer_best.csv` | CSV |
| `--out-nec FILE` | `best_antenna.nec` | Deck NEC2 |
| `--out-radiation FILE` | `radiation_diagrams.png` | Pattern |
| `--out-construction FILE` | `antenna_construction.png` | Disegno |
| `--out-pdf FILE` | `antenna_brochure.pdf` | PDF |
| `--retry N` | `0` | Ripetizioni per limiti di finestra |
| `--no-interactive` | disattivo | Nessun prompt interattivo |
| `--quiet`, `-q` | disattivo | Riduce l'output verboso |
| `--lang {en,es,it}` | auto | Lingua |
| `--gui` | disattivo | Avvia la GUI |

### 14.1 Esempi

```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
```

```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \
    --active-bands 40m,20m --wire-len 21.0 --cp-len 5.0
```

```bash
python src/Long_Wire_Antenna.py --bands 40m,20m --wire-len 21.0 \
    --no-counterpoise --no-cp-return coax-stub --cp-stub-len 3.0
```

```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0 \
    --mode nec2 --nec2c /usr/local/bin/nec2c --converge
```

---

## 15. Flussi di lavoro tipici

### 15.1 Primo progetto con GUI

1. Avviare `python src/Long_Wire_Antenna.py --gui`.
2. Inserire le bande.
3. Lasciare vuote le frequenze se tutte le bande sono riconosciute.
4. Impostare le lunghezze iniziali.
5. In Fisica lasciare `auto`.
6. Verificare `nec2c` con Auto-detect se si desiderano risultati NEC2.
7. Eseguire una prima ricerca con margine `2.0 m`.
8. Controllare il report e la posizione del vincitore nella finestra.

### 15.2 Vincitore sul bordo

Allargare manualmente i limiti oppure impostare `Maximum retries` a un valore piccolo, ad esempio `2`.

### 15.3 Progetto da costruire

Per una decisione costruttiva usare NEC2, segmentazione `fine`, una finestra di ricerca sufficientemente ampia e il controllo di convergenza. Verificare poi l'antenna reale con analizzatore/VNA.

### 15.4 Rete di adattamento

Dopo una ricerca riuscita, utilizzare UnUn / Transmatch. I dati del CSV vengono caricati automaticamente. Verificare sempre il componente reale, il Q, la SRF, le perdite e la potenza RF.

---

## 16. Risoluzione dei problemi

| Problema | Causa probabile | Soluzione |
|---|---|---|
| La GUI non parte | Tkinter mancante | Installare il pacchetto Tkinter della propria distribuzione |
| Manca `--freqs` | Banda personalizzata senza frequenza | Inserire una frequenza per ogni banda |
| Risultati sospetti con `fast` | Segmentazione troppo bassa | Usare `fine` |
| NEC2 richiesto ma non trovato | Motore non installato/non rilevato | Installare il motore o specificare `--nec2c` |
| Campi del contrappeso disabilitati | Contrappeso non selezionato | Abilitare "Use counterpoise" |
| Percorso di ritorno disabilitato | Il contrappeso è presente | Disabilitare il contrappeso per usare questa funzione |
| Vincitore sul bordo | Ricerca troppo stretta | Allargare la finestra o usare `Maximum retries` |
| Nessun dato nelle calcolatrici | CSV assente o directory diversa | Eseguire una ricerca o usare Reload nella directory corretta |
| VSWR UnUn anomalo | SRF dell'avvolgimento insufficiente | Controllare l'avviso SRF e ridurre le spire se necessario |
| Mancano i PNG | `matplotlib` assente (o `numpy`, per i soli diagrammi di radiazione) | Installare `matplotlib numpy` |
| Manca il PDF | `reportlab` assente | Installare `reportlab` |
| Diagramma nel PDF segnato "non disponibile" | `Pillow` (`PIL`) assente | Installare `pillow` |
| Anteprima comando inattesa | Campo o checkbox non aggiornato | Controllare l'anteprima prima di Run |

---

## 17. Glossario

- **VSWR/ROE:** rapporto d'onda stazionaria; 1.0 è il valore ideale minimo.
- **R + jX:** impedenza al punto di alimentazione.
- **Counterpoise:** conduttore che fornisce l'altra parte del circuito RF in una configurazione non bilanciata.
- **NEC2:** codice elettromagnetico numerico basato sul metodo dei momenti.
- **Segmentazione:** suddivisione dei fili in segmenti per il calcolo NEC2.
- **Sommerfeld-Norton:** modello NEC2 per terreno a conducibilità e permittività finite.
- **Pareto-optimal:** candidati per i quali nessun altro candidato è migliore o uguale su tutte le metriche attive.
- **UnUn:** trasformatore da sbilanciato a sbilanciato.
- **Transmatch:** rete di adattamento, qui realizzata come bobina con prese e componenti L/C.
- **Nucleo toroidale:** un nucleo magnetico a forma di anello (ferrite o polvere di ferro) usato per avvolgere trasformatori/choke RF; "mix" e dimensioni diversi bilanciano in modo diverso range di frequenza, perdite e capacità di potenza.
- **SRF:** frequenza di autorisonanza di un avvolgimento.
- **TOA:** angolo di elevazione sopra l'orizzonte al quale viene valutato il guadagno.

---

## 18. Appendice — Bande radioamatoriali conosciute

| Banda | Frequenza centrale MHz |
|---|---:|
| 2200m | 0.1365 |
| 630m | 0.475 |
| 160m | 1.850 |
| 80m | 3.650 |
| 60m | 5.350 |
| 40m | 7.100 |
| 30m | 10.125 |
| 20m | 14.175 |
| 17m | 18.118 |
| 15m | 21.225 |
| 12m | 24.940 |
| 10m | 28.500 |
| 6m | 50.200 |
| 4m | 70.200 |
| 2m | 144.200 |
| 70cm | 432.100 |
| 23cm | 1296.200 |

I nomi non presenti nell'elenco sono trattati come personalizzati e richiedono `--freqs`.

---

## 19. Appendice — Database dei nuclei toroidali

Il menu UnUn contiene i nuclei integrati nel programma. Le specifiche principali sono materiale, AL in nH/N², diametro esterno/interno, altezza, area efficace Ae e limite approssimativo di densità di flusso.

Nuclei disponibili nel menu a discesa **Core** della sotto-scheda UnUn Toroid, con le loro specifiche principali (AL in nH per spira², diametro esterno/interno e altezza in mm, area efficace Ae in cm², e un limite approssimativo raccomandato di densità di flusso RF B_sat in mT):

| Nucleo | Materiale | AL (nH/N²) | OD (mm) | ID (mm) | H (mm) | Ae (cm²) | B_sat (mT, circa) |
|---|---|---|---|---|---|---|---|
| FT-114-43 | Ferrite Mix 43 | 510.0 | 29.0 | 19.0 | 7.5 | 0.38 | 200 |
| FT-140-43 | Ferrite Mix 43 | 885.0 | 35.6 | 22.9 | 12.7 | 0.63 | 200 |
| FT-240-43 | Ferrite Mix 43 | 1075.0 | 61.0 | 35.6 | 12.7 | 1.52 | 200 |
| FT-114-31 | Ferrite Mix 31 | 800.0 | 29.0 | 19.0 | 7.5 | 0.38 | 200 |
| FT-140-31 | Ferrite Mix 31 | 1390.0 | 35.6 | 22.9 | 12.7 | 0.63 | 200 |
| **FT-240-31** (predefinito) | Ferrite Mix 31 | 1800.0 | 61.0 | 35.6 | 12.7 | 1.52 | 200 |
| FT-114-52 | Ferrite Mix 52 | 175.0 | 29.0 | 19.0 | 7.5 | 0.38 | 200 |
| FT-140-52 | Ferrite Mix 52 | 225.0 | 35.6 | 22.9 | 12.7 | 0.63 | 200 |
| FT-240-52 | Ferrite Mix 52 | 300.0 | 61.0 | 35.6 | 12.7 | 1.52 | 200 |
| FT-114-61 | Ferrite Mix 61 | 79.3 | 29.0 | 19.0 | 7.5 | 0.38 | 236 |
| FT-140-61 | Ferrite Mix 61 | 140.0 | 35.6 | 22.9 | 12.7 | 0.63 | 236 |
| FT-240-61 | Ferrite Mix 61 | 170.0 | 61.0 | 35.6 | 12.7 | 1.52 | 236 |
| T-130-2 | Polvere di ferro Mix 2 | 11.0 | 33.0 | 19.8 | 11.1 | 0.85 | 300 |
| T-200-2 | Polvere di ferro Mix 2 | 12.0 | 50.8 | 31.8 | 14.0 | 1.58 | 300 |
| T-130-6 | Polvere di ferro Mix 6 | 9.6 | 33.0 | 19.8 | 11.1 | 0.85 | 300 |
| T-200-6 | Polvere di ferro Mix 6 | 11.6 | 50.8 | 31.8 | 14.0 | 1.58 | 300 |

> **Nota sulla modellazione delle perdite del nucleo:** in HF, il limite di potenza pratico di un trasformatore in ferrite è determinato dal **riscaldamento del nucleo**, non dalla saturazione magnetica (il limite di saturazione diventa rilevante solo a frequenze molto più basse per un dato numero di spire). Il modello di perdita dello strumento usa la permeabilità complessa di ciascun materiale (µ′, µ″) alla frequenza di lavoro per stimare una resistenza di perdita parallela, e da essa un limite di potenza continua basato sulla superficie del nucleo e su un innalzamento di temperatura ammissibile ipotizzato. Queste cifre sono approssimazioni ingegneristiche (accurate a un fattore di circa 1.5), non valori da datasheet — trattare le stime di potenza della scheda UnUn come un controllo di buon senso, non come una specifica certificata.

I dati del database sono valori di progetto utilizzati dal calcolatore e non costituiscono una garanzia delle prestazioni di un nucleo commerciale reale. Per applicazioni di potenza verificare sempre il datasheet del produttore, le perdite, la temperatura e la densità di flusso.

