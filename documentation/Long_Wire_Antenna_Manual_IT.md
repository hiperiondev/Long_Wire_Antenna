# NEC2 Antenna Length Optimizer — Manuale utente completo

**Autore del software:** LU3VEA (rilasciato CC0 v1.0)
**Versione del manuale:** 1.6 (verificato rispetto al codice attuale). Novità della 1.6: è documentato per la prima volta l'intero insieme dei **tipi di antenna** — le tre topologie (`long-wire`, `ocfd`, `carolina-windom`), il gruppo della GUI che le seleziona ([6.1](#61-sezione-antenna-type)) e le quattordici opzioni CLI finora mancanti; `--jobs` è corretto ovunque — ora è onorato in **entrambe** le modalità, normale e `--fast-run`, e la GUI *lo emette* da un campo della scheda Esecuzione; lo schema del CSV acquisisce le sue sei colonne riservate ai dipoli. Nella 1.5: Questa revisione porta il manuale italiano alla stessa copertura delle edizioni inglese e spagnola: la procedura guidata della GUI è ora completa scheda per scheda, la sezione 14 elenca ogni opzione della riga di comando, e sono state corrette le cifre di `--converge` (fattori di segmentazione 0.5× e 2×, non 2× e 4×), l'ultima colonna della tabella di compensazione del Transmatch (residuo del 5 %, non tolleranza di 5 Ω) e tutti gli ancoraggi dell'indice (i titoli del tipo `## N — Titolo` generano un ancoraggio con trattino *doppio*).
**Ambito del manuale:** installazione, concetti, interfaccia grafica (GUI) in dettaglio, interfaccia a riga di comando (CLI), file di output prodotti e risoluzione dei problemi.

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
    - [13.8 Limiti importanti degli output e della modellazione](#138-limiti-importanti-degli-output-e-della-modellazione)
14. [Interfaccia a riga di comando (CLI) — riferimento completo](#14-interfaccia-a-riga-di-comando-cli--riferimento-completo)
15. [Flussi di lavoro tipici, passo per passo](#15-flussi-di-lavoro-tipici-passo-per-passo)
16. [Risoluzione dei problemi](#16-risoluzione-dei-problemi)
17. [Glossario](#17-glossario)
18. [Appendice — Bande radioamatoriali conosciute](#18-appendice--bande-radioamatoriali-conosciute)
19. [Appendice — Database dei nuclei toroidali](#19-appendice--database-dei-nuclei-toroidali)

---

> **Nota sull'ambito:** questo programma è uno strumento di modellazione e ottimizzazione. Non sostituisce la verifica dell'antenna realmente installata. I risultati dipendono dalle ipotesi geometriche, dal modello di terreno, dalle perdite, dalla segmentazione e dagli oggetti circostanti.

## 1. Cosa fa questo software

Il **NEC2 Antenna Length Optimizer** è uno strumento di progetto per antenne a filo multibanda. Modella tre topologie, selezionabili con `--antenna-type` (o con il menu descritto in [6.1](#61-sezione-antenna-type)):

- **`long-wire`** (predefinito) — un radiatore inclinato od orizzontale alimentato da un unico punto, con contrappeso, picchetto di terra o spezzone di coassiale opzionale come percorso di ritorno RF: la classica configurazione "random wire" / end-fed usata da molti radioamatori. Adattato con un **UnUn**.
- **`ocfd`** — un dipolo alimentato fuori centro (Windom), dove i due bracci *sono* l'antenna e non serve alcun conduttore di ritorno. Adattato con un **balun**.
- **`carolina-windom`** — un OCFD con in più una sezione verticale radiante fra il balun e un isolatore di linea.

Il tipo di antenna cambia il significato delle lunghezze in ingresso, quale dispositivo di adattamento viene progettato, quale modello empirico si usa quando NEC2 non è disponibile e quale metrica di qualità geometrica stampa il report. Tutto quanto segue vale per tutti e tre, salvo dove indicato diversamente.

Dati:

- una o più **bande** radioamatoriali (o personalizzate) su cui si vuole operare, e
- una **lunghezza iniziale del filo** e una **lunghezza del contrappeso**,

il programma esplora le combinazioni vicine di lunghezza del filo e del contrappeso, valuta le prestazioni elettriche (impedenza e ROS) di ciascuna su ogni banda richiesta e riporta la combinazione che offre le migliori **prestazioni aggregate su tutte le bande contemporaneamente** — non una banda sola a scapito delle altre.

I candidati possono essere valutati in due modi:

- **Modalità empirica** — un'approssimazione matematica molto rapida per lo screening delle geometrie. Non modella il terreno reale né la geometria del contrappeso, e i suoi valori di reattanza non devono essere usati per progettare una rete di adattamento.
- **Modalità NEC2** — esegue il simulatore a metodo dei momenti `nec2c` per ogni geometria candidata. È un calcolo elettromagnetico numerico molto più dettagliato del modello empirico, ma l'accuratezza rispetto all'antenna reale dipende dal modello, dalla segmentazione, dal terreno e dalle condizioni di installazione.

Oltre alla geometria dell'antenna, il software include due calcolatori di reti di adattamento raggiungibili dalla stessa finestra:

- Un **progettista di autotrasformatori UnUn** (unbalanced-to-unbalanced) su nuclei toroidali di ferrite o polvere di ferro — oppure, a scelta, in aria.
- Un **progettista di Transmatch** (rete di adattamento a bobina con prese).

Entrambi possono leggere automaticamente le impedenze d'antenna trovate dall'ottimizzatore e proporre una soluzione di adattamento per esse.

---

## 2. Come funziona, in termini semplici

1. **Si descrive il problema**: quali bande, quanto lunghi all'incirca il filo e il contrappeso, e quanto ampiamente cercare attorno a quelle lunghezze.
2. Il programma costruisce una **griglia di geometrie candidate** (ogni combinazione di lunghezza del filo × lunghezza del contrappeso all'interno della finestra di ricerca, spaziata dai passi scelti).
3. **Ogni candidato viene valutato** su ogni banda richiesta:
   - In *modalità NEC2* il programma scrive un file `.nec` che descrive la geometria (raggio del filo, materiale, tipo di terreno, segmentazione, frequenza) e invoca `nec2c`, poi rilegge la resistenza (R) e la reattanza (X) al punto di alimentazione e calcola il rapporto d'onda stazionaria (ROS).
   - In *modalità empirica* R e X sono stimate con formule in forma chiusa invece che con una simulazione completa (molto più veloce, meno accurata vicino alla risonanza).
4. Ogni candidato riceve un **punteggio aggregato** che combina la penalità di ROS su ogni banda attiva (ROS peggiore = punteggio peggiore), una penalità di "evitamento" per i candidati che cadono in una classe di risonanza scomoda e — opzionalmente — un bonus/penalità legato al guadagno a un angolo di elevazione obiettivo.
5. Il programma tiene traccia anche dell'**insieme Pareto-ottimale**: i candidati per i quali nessun altro candidato è almeno altrettanto buono su tutte le bande. Mostra i compromessi realmente disponibili, non solo un unico "vincitore".
6. Il candidato migliore (e, opzionalmente, i suoi vicini) viene **risimulato ad alta accuratezza** (segmentazione "fine"), così i numeri da cui si costruisce sono affidabili anche se la ricerca ampia ha usato una densità più grossolana e veloce.
7. Infine il programma **scrive i risultati**: un report di testo ordinato, una mappa di calore/grafico a dispersione, un CSV con le cifre per banda della geometria vincente, un file NEC2 pronto all'uso, i diagrammi di radiazione, un disegno costruttivo e un opuscolo PDF di una pagina, se `reportlab` è installato.

---

## 3. Requisiti e installazione

### 3.1 Python

Lo strumento è un singolo script Python 3. Richiede:

- **Python 3** (qualsiasi versione ragionevolmente recente; 3.8 o successiva).
- Il toolkit grafico **Tkinter**, se si intende usare l'interfaccia grafica. Tkinter è incluso nella maggior parte delle installazioni desktop di Python; su alcune distribuzioni Linux va installato a parte:
  ```bash
  sudo apt install python3-tk
  ```
  Se Tkinter manca, la GUI si rifiuta di partire e stampa esattamente questa istruzione.

### 3.2 Pacchetti Python opzionali ma consigliati

| Pacchetto | Scopo | Cosa succede se manca |
|---|---|---|
| `colorama` | Output di console colorato | Si ripiega sul testo semplice. Nessuna perdita funzionale. |
| `matplotlib` | Grafico dello spazio di ricerca, diagrammi di radiazione e disegni costruttivi, compresi i disegni degli strumenti di adattamento | Quegli output grafici non possono essere generati. |
| `numpy` | Usato internamente dal generatore dei diagrammi di radiazione | I diagrammi di radiazione non possono essere generati. In pratica `numpy` è quasi sempre già presente, perché viene installato automaticamente come dipendenza di `matplotlib`. |
| `reportlab` | Generazione dell'opuscolo PDF | Il PDF viene saltato. |
| `Pillow` (`PIL`) | Inserisce i PNG costruttivi/di radiazione dentro il PDF | Il PDF viene comunque generato, ma la sezione immagine interessata è sostituita da un segnaposto "(non disponibile)". |

Installazione tipica:

```bash
pip install colorama matplotlib numpy reportlab pillow
```

`matplotlib`, `reportlab` e `Pillow` sono indipendenti tra loro: `matplotlib` crea le immagini, `reportlab` crea il contenitore PDF e `Pillow` incorpora le immagini in quel PDF. La mancanza di uno non impedisce necessariamente gli altri output.

> **Nota sull'installer Windows:** `Setup_Long_Wire_Antenna.exe` installa anche, via `pip`, un pacchetto chiamato `tabulate` oltre a quelli qui sopra. Lo script non importa né usa `tabulate` da nessuna parte — è un residuo inutilizzato nell'elenco delle dipendenze dell'installer, non un requisito reale. Non serve installarlo se si configura lo script a mano.
>
> L'installer esegue anche uno script post-installazione (`post_install_setup.py`) che tenta facoltativamente di scaricare una build più recente del motore NEC2 da un progetto GitHub esterno, ripiegando sul binario incluso se il download fallisce. La sua logica di fallback cerca un file chiamato `onec.exe`/`onec_bundled.exe`, che questo installer non distribuisce (distribuisce solo `nec2c.exe`), quindi quel particolare ramo di fallback è oggi un'operazione a vuoto — innocua, perché il lanciatore installato (`run_gui.bat`) individua e usa `nec2c\nec2c.exe` indipendentemente dall'esito. Si possono ignorare tranquillamente i riferimenti a `onec.exe` nei log di installazione.

### 3.3 Motore di simulazione NEC2 (`nec2c`)

Per usare la **modalità NEC2** (consigliata per i numeri finali affidabili) serve il binario `nec2c` — un'implementazione compilata del simulatore NEC-2 a metodo dei momenti — installato sul sistema. Fonti tipiche:

- Il gestore di pacchetti della propria distribuzione Linux (il nome varia, es. `nec2c`).
- La compilazione dai sorgenti pubblici del progetto `nec2c`.

**La modalità empirica non richiede affatto `nec2c`.** Può essere usata senza motore esterno, ma resta un'approssimazione.

> **Alternativa Linux in un clic:** invece di installare `nec2c` e i pacchetti Python a mano si può usare la `Long_Wire_Antenna-x86_64.AppImage` precompilata (o costruirne una propria con `others/build_appimage.sh`), che racchiude in un unico file portabile il proprio interprete Python, tutti i pacchetti opzionali e un `nec2c` collegato staticamente. Vedere il `README` del progetto. L'AppImage si avvia sempre direttamente nella GUI.

### 3.4 Individuazione del binario `nec2c`

Il programma cerca `nec2c` automaticamente, in quest'ordine:

1. Un percorso esplicito indicato con `--nec2c /percorso/a/nec2c` (CLI) o digitato nel campo **NEC2 binary** (GUI).
2. La variabile d'ambiente `$NEC2C`.
3. Il `PATH` di sistema (cerca i nomi di eseguibile `nec2c`, `nec2c-mpich` e `onec` — questo è l'elenco corretto attuale; note più vecchie che citavano `xnec2c` erano errate e sono superate).
4. Un elenco di percorsi d'installazione comuni (`/usr/bin`, `/usr/local/bin`, `/opt/nec2c/bin`, `/opt/homebrew/bin`, ecc.), compresi percorsi specifici di `onec` come `C:\Program Files\OpenNEC\onec.exe` su Windows.
5. Come ultima risorsa, solo da riga di comando, chiede interattivamente di digitare il percorso (a meno che non sia attivo `--no-interactive`).

Nella GUI il pulsante **Auto-detect** della scheda Fisica avvia questa ricerca su richiesta.

`onec` è il nome dell'eseguibile della build del motore del progetto OpenNEC; `nec2c` e `nec2c-mpich` sono le build classiche più diffuse. Tutti e tre sono supportati indifferentemente dalla ricerca per nome.

> ⚠️ **Bug noto — la ricerca fissa in `Program Files\OpenNEC` su Windows:** l'installer Windows copia il motore in `C:\Program Files\OpenNEC\nec2c.exe` e `C:\Program Files (x86)\OpenNEC\nec2c.exe`. I due percorsi `OpenNEC` cablati nel passo 4 cercano però un file chiamato letteralmente **`onec.exe`**, non `nec2c.exe` — quindi quel fallback non troverà mai la copia posata lì dall'installer. Nell'uso normale la cosa è invisibile, perché l'avvio dal collegamento sul Desktop (`run_gui.bat`) imposta direttamente `$NEC2C` (passo 2) e non ha bisogno di quel fallback. Conta solo se si esegue `Long_Wire_Antenna.py` a mano da un terminale dopo un'installazione Windows, senza `run_gui.bat` e senza `$NEC2C`: in quel caso passare esplicitamente `--nec2c "C:\Program Files\OpenNEC\nec2c.exe"` (o impostare `$NEC2C`) invece di affidarsi alla ricerca automatica.

---

## 4. Avvio del programma

### 4.1 Avvio della GUI

```bash
python src/Long_Wire_Antenna.py --gui
```

Apre la finestra interattiva descritta nel resto del manuale. Non serve nessun altro flag: ogni impostazione si inserisce poi dall'interfaccia.

`--gui` viene rilevato in una pre-analisi della riga di comando, prima che il resto venga letto, quindi qualunque altro flag passato insieme (es. `python src/Long_Wire_Antenna.py --gui --bands 40m`) viene **ignorato silenziosamente** — la GUI si apre comunque con i propri valori predefiniti. Per configurare un'esecuzione in modalità GUI si usano i campi della GUI, non flag aggiuntivi.

### 4.2 Esecuzione dalla riga di comando (senza GUI)

```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
```

Vedere la [sezione 14](#14-interfaccia-a-riga-di-comando-cli--riferimento-completo) per l'elenco completo dei flag. La GUI è in effetti un front-end che assembla per l'utente esattamente questo tipo di riga di comando e la esegue: ogni opzione visibile nella GUI corrisponde a uno di questi flag, e l'**anteprima del comando** nella scheda Esecuzione mostra in tempo reale il comando costruito dalle impostazioni correnti.

### 4.3 Ottenere la guida della riga di comando

```bash
python src/Long_Wire_Antenna.py --help
```

### 4.4 Lingua dell'interfaccia

Il testo del programma (sia i messaggi CLI sia la GUI) è disponibile in **inglese, spagnolo e italiano**. Vedere la [sezione 12.3](#123-lingua) per cambiarla nella GUI e `--lang` per la CLI.

---

## 5. L'interfaccia grafica (GUI) — panoramica

Avviato con `--gui`, il programma apre un'unica finestra contenente:

- Una **barra di intestazione** (titolo, cambio lingua, controlli della dimensione del carattere).
- Una riga con il **percorso dello script dell'ottimizzatore** (quale file di script la GUI eseguirà davvero — vedere [12.1](#121-percorso-dello-script)).
- Un **blocco di sei schede**, ciascuna con impostazioni affini:
  1. **Banda / Sorgente** — per quali bande progettare e la geometria iniziale.
  2. **Intervallo di ricerca** — quanto ampiamente e finemente cercare, più le opzioni di contrappeso/ritorno di massa.
  3. **Fisica** — motore di simulazione, modello di terreno, modello di alimentazione, conduttore e accuratezza.
  4. **File di output** — dove vengono scritti i risultati e come si chiamano.
  5. **Esecuzione** — anteprima del comando, comandi Esegui/Ferma, console e riepilogo dal vivo.
  6. **UnUn / Transmatch** — due calcolatori di reti di adattamento indipendenti (sotto-schede).

La GUI **non esegue l'ottimizzazione dentro la finestra**: costruisce una riga di comando dalle impostazioni e lancia lo script come processo separato, esattamente come se il comando fosse stato digitato a mano. Ne consegue che:

- L'**anteprima del comando** nella scheda Esecuzione riflette le impostazioni correnti e può essere copiata ed eseguita manualmente.
- Le ricerche lunghe girano in background: la finestra resta reattiva e si segue l'avanzamento nella console.
- In linea di principio si può puntare il campo "script dell'ottimizzatore" a una copia o versione *diversa* dello script, e la GUI piloterà quella.

Ogni campo di testo, casella, pulsante di opzione e menu a discesa delle sei schede è descritto in dettaglio qui sotto, scheda per scheda.

---

## 6. Scheda 1 — Banda / Sorgente

Questa scheda definisce **per cosa** si sta progettando: la topologia dell'antenna, le bande di lavoro, le frequenze (se necessarie) e la stima iniziale delle due lunghezze.

### 6.1 Sezione "Antenna type"

È il **primo gruppo di controlli della scheda**, e non per caso: cambia il *significato* di tutti gli altri campi del programma. È anche l'unico punto della GUI in cui si sceglie la topologia dell'antenna.

- **Antenna type (menu a tendina)** — `long-wire` (predefinito), `ocfd` o `carolina-windom`. CLI: `--antenna-type`.
  - **`long-wire`** — il classico radiatore end-fed più un conduttore di ritorno (contrappeso, picchetto di terra o spezzone di coassiale). "Wire length" e "Counterpoise length" significano esattamente quello che dicono, tutti i controlli del contrappeso nella scheda Intervallo di ricerca si applicano, e il dispositivo di adattamento è un **UnUn** il cui rapporto viene cercato automaticamente dall'ottimizzatore.
  - **`ocfd`** — un **dipolo alimentato fuori centro** (Windom). Entrambi i bracci irradiano e il dipolo è il proprio percorso di ritorno, quindi **"Wire length" e "Counterpoise length" diventano il braccio lungo e il braccio corto**; `--no-counterpoise` viene rifiutato, la sezione "percorso di ritorno senza contrappeso" smette di applicarsi, e il dispositivo di adattamento diventa un **balun** limitato a rapporti realizzabili.
  - **`carolina-windom`** — un OCFD più una **sezione verticale radiante** fra il balun e un isolatore di linea. Al nodo di alimentazione confluiscono tre conduttori, quindi l'alimentazione *straddle* è geometricamente impossibile e il modello di alimentazione viene **forzato a `junction`** (il programma lo dichiara all'avvio e raccomanda `--converge`). Attendersi una convergenza più lenta e un'incertezza pubblicata maggiore su X.
- **Offset** — braccio corto ÷ lunghezza totale, solo per i tipi dipolo. Predefinito `0.3333` (il classico terzo del Windom); intervallo valido `0.10`–`0.49`. A `0.50` sarebbe un normale dipolo alimentato al centro; sotto `0.10` è di fatto un'alimentazione d'estremità. CLI: `--offset`. Disabilitato per `long-wire`.
- **Balun kind** — `guanella` (predefinito) o `ruthroff`: la topologia del balun a linea di trasmissione. Guanella è un balun di corrente ed è la scelta corretta per un'alimentazione bilanciata su tutta l'HF. CLI: `--balun-kind`. Solo tipi dipolo.
- **Lunghezza verticale (m)** — solo Carolina Windom: lunghezza della sezione verticale radiante fra il balun e l'isolatore di linea. Predefinito `3.0` m, minimo `0.5` m. CLI: `--cw-vert-len`.
- **Z dell'isolatore (R,X)** — solo Carolina Windom: modella l'isolatore di linea come impedenza serie **finita** (es. `1000,2000`) invece che come circuito aperto ideale. Lasciare vuoto per il caso ideale; compilarlo per studiare che cosa fa davvero all'antenna un choke insufficiente. CLI: `--cw-isolator-z`.

I controlli che il tipo selezionato non può usare vengono disabilitati automaticamente. Da riga di comando le combinazioni equivalenti sono **rifiutate con un errore esplicito** invece di essere ignorate in silenzio, così un'esecuzione non può mai riportare un'antenna diversa da quella descritta dai flag — per esempio `--antenna-type ocfd --no-counterpoise` si ferma con un errore invece di modellare in sordina qualcos'altro.

> La CLI ha diverse altre opzioni di tipo antenna senza un controllo dedicato nella GUI: `--total-len`, `--offset-min` / `--offset-max` / `--offset-step`, `--balun-ratio`, `--balun-core`, `--balun-turns`, `--feed-choke` e `--match-model`. Vedere la [sezione 14](#14-interfaccia-a-riga-di-comando-cli--riferimento-completo).

### 6.2 Campo "Band(s)"

- **Che cos'è:** un elenco di nomi di banda separati da virgole, es. `40m,20m,15m`.
- **Predefinito:** `40m,20m,15m`.
- **Obbligatorio:** sì — l'ottimizzatore non può girare senza almeno una banda.
- I nomi possono essere **bande amatoriali note** (vedere l'[appendice, sezione 18](#18-appendice--bande-radioamatoriali-conosciute)) oppure nomi personalizzati a piacere (es. `miaBandaSpeciale`).
- Sotto il campo, una riga di suggerimento elenca tutti i nomi riconosciuti.

### 6.3 Campo "Frequencies (MHz)"

- **Che cos'è:** un elenco di frequenze centrali in MHz separate da virgole, una per banda, nello *stesso ordine* del campo Band(s), es. `7.1,14.2,21.2`.
- **Quando è facoltativo:** se ogni nome digitato in "Band(s)" è una banda *riconosciuta*, si può lasciare vuoto — il programma sostituisce automaticamente la frequenza centrale standard di ciascuna.
- **Quando è obbligatorio:** se si usa un nome di banda personalizzato/non riconosciuto **bisogna** fornire qui la frequenza corrispondente, altrimenti il programma si ferma con un errore (nell'uso interattivo da riga di comando può chiederla; la GUI passa quello che è stato digitato, quindi va compilato).
- Una riga di suggerimento sotto il campo ricorda questa regola.

### 6.4 Campo "Wire length (m)"

- **Che cos'è:** la lunghezza iniziale, in metri, del filo radiante — il centro attorno a cui viene costruita la finestra di ricerca.
- **Predefinito:** `21.0`.
- **Obbligatorio:** sì.
- Un suggerimento colorato a destra del campo ne ricorda brevemente il ruolo.

### 6.5 Campo "Counterpoise length (m)"

- **Che cos'è:** la lunghezza iniziale, in metri, del filo di contrappeso — anch'essa centro della finestra di ricerca.
- **Predefinito:** `5.0`.
- **Obbligatorio:** sì, **a meno che** non si sia tolta la spunta a "Use counterpoise" nella scheda Intervallo di ricerca (vedere [7.3](#73-casella-use-counterpoise)), nel qual caso il campo è disabilitato perché non c'è alcun contrappeso da dimensionare.

### 6.6 Sezione "Active Bands"

- **Scopo:** far *valutare* una geometria su tutte le bande elencate in 6.2, ma far *pesare sul punteggio* solo un sottoinsieme.
- **Campo:** elenco di nomi di banda separati da virgole, che deve essere un sottoinsieme di "Band(s)".
- **Predefinito:** vuoto, cioè **tutte** le bande elencate sono attive e usate per il punteggio.
- **Esempio d'uso:** si vuole vedere nel report come si comporta il progetto sui 10 m per curiosità, ma si opera davvero solo su 40 m e 20 m — Band(s) = `40m,20m,10m`, Active Bands = `40m,20m`.

### 6.7 "Optimizer language" (lingua del report)

- **Scopo:** sceglie in quale lingua sono scritti l'*output di console dell'ottimizzatore e il report/PDF generati*, indipendentemente dalla lingua di visualizzazione della GUI (vedere [12.3](#123-lingua)).
- **Opzioni:** `auto` (rileva dalle impostazioni locali), `en`, `es`, `it`.
- **Predefinito:** `auto`.

---

## 7. Scheda 2 — Intervallo di ricerca

Questa scheda controlla **quanto ampia e quanto fine** è la ricerca, più la topologia del contrappeso (presente o assente) e, quando assente, come viene modellato il percorso di ritorno RF. Contiene anche la geometria dell'antenna (altezza, inclinazione) e le opzioni di dimensione del report.

### 7.1 Campo "Search margin"

- **Che cos'è:** se non si impostano limiti minimi/massimi espliciti (7.2, 7.6), l'ottimizzatore cerca ± questo numero di metri attorno alle lunghezze iniziali di filo e contrappeso.
- **Predefinito:** `2.0` m.
- **Sovrascritto da:** valori espliciti di wire-min/wire-max o cp-min/cp-max, descritti sotto.

### 7.2 Sezione "Wire search range"

Tre campi, tutti facoltativi:

| Campo | Significato | Comportamento se lasciato vuoto |
|---|---|---|
| `wire-min` | Lunghezza minima del filo da provare (m) | Calcolata come lunghezza iniziale − margine |
| `wire-max` | Lunghezza massima del filo da provare (m) | Calcolata come lunghezza iniziale + margine |
| `wire-step` | Incremento tra le lunghezze provate (m) | `0.25` m |

Una nota sotto i campi ricorda che lasciandoli vuoti si ricade sulla finestra automatica basata sul margine. I limiti sono comunque portati a un minimo di `1.0` m: un radiatore di lunghezza nulla non è una geometria valida.

### 7.3 Casella "Use counterpoise"

- **Predefinito:** spuntata (contrappeso presente).
- **Quando è spuntata:** l'antenna è modellata come radiatore **più** filo di contrappeso, entrambi dallo stesso punto di alimentazione. Tutti i campi relativi al contrappeso sono abilitati.
- **Quando non è spuntata:** l'antenna è modellata **senza** contrappeso. Ogni campo relativo al contrappeso è disabilitato ma *conserva in memoria il valore digitato* — rimettendo la spunta si ritrova esattamente quello che c'era. Togliere la spunta aggiunge `--no-counterpoise` al comando e attiva la sezione **"No-counterpoise return path"**, che in quel caso diventa obbligatoria.

### 7.4 Sezione "No-counterpoise return path"

Questa sezione conta — ed è abilitata — solo quando "Use counterpoise" ([7.3](#73-casella-use-counterpoise)) **non** è spuntata. Sceglie come viene modellato il percorso di ritorno RF in assenza di un filo di contrappeso, dato che una qualche via di ritorno deve esistere perché la simulazione sia fisicamente sensata. Tre scelte mutuamente esclusive:

- **`ground-rod`** (predefinito) — modella il ritorno come collegamento diretto a terra / picchetto di terra.
- **`coax-stub`** — modella il ritorno come uno spezzone di calza coassiale di lunghezza data. Sceglierlo abilita il campo **"CP stub length"** sottostante (predefinito `2.0` m).
- **`reject`** — rifiuta di sintetizzare qualunque percorso di ritorno implicito; da usare se si intende modellare il ritorno in altro modo, o se si vuole che il programma segnali le configurazioni prive di ritorno definito.

Una riga di suggerimento colorata sopra i pulsanti spiega il compromesso. In modalità NEC2 `reject` respinge esplicitamente la configurazione; `ground-rod` è modellato con **terreno perfetto (GN 1)** — cioè quella scelta forza il modello di terreno per quella esecuzione, con tanto di avviso a log, indipendentemente da `--ground-model` — mentre `coax-stub` mantiene il modello di terreno selezionato. In modalità empirica queste scelte non fanno parte del modello.

### 7.5 Sezione "Radiation / take-off angle"

Controlla se e quanto il punteggio premia il guadagno a basso angolo, quello che conta di più per il DX:

| Campo | Significato | Predefinito |
|---|---|---|
| Target take-off angle | Angolo di elevazione (gradi sopra l'orizzonte) a cui viene valutato il bonus/penalità di guadagno | `25.0°` |
| Gain weight | Quanto pesa quel guadagno nel punteggio aggregato, in unità di punteggio per dB. All'incirca, 5 dB di differenza ≈ 1.0 unità di punteggio | `0.20` per dB |
| Re-rank top N | Quanti dei migliori candidati per solo ROS ricevono una risimulazione completa del diagramma di radiazione (necessaria per misurare davvero il guadagno all'angolo obiettivo) prima di applicare il bonus | `6` |

Un suggerimento sotto spiega il compromesso: ri-classificare più candidati costa più tempo di calcolo ma offre alla ri-classificazione basata sul guadagno un bacino più ampio di candidati quasi ottimali.

### 7.6 Sezione "Counterpoise search range"

Rispecchia la sezione 7.2, ma per la lunghezza del contrappeso. Significativa (e presente nel comando) solo quando "Use counterpoise" è spuntata:

| Campo | Significato | Comportamento se lasciato vuoto |
|---|---|---|
| `cp-min` | Lunghezza minima del contrappeso da provare (m) | Lunghezza iniziale − margine |
| `cp-max` | Lunghezza massima del contrappeso da provare (m) | Lunghezza iniziale + margine |
| `cp-step` | Incremento tra le lunghezze provate (m) | `0.25` m |

### 7.7 Sezione "Antenna geometry"

Un'unica **altezza del punto di alimentazione** per tutta l'antenna, più controlli opzionali di inclinazione:

| Campo | Significato | Predefinito |
|---|---|---|
| **Height** | Altezza del punto di alimentazione da terra (metri). Condivisa da radiatore e contrappeso, dato che entrambi partono dallo stesso punto. | `8.0` m |
| **Wire slope end height** | Altezza da terra (metri) dell'estremità *lontana* del radiatore. `0.0` significa che il filo scende fino a toccare il suolo (filo completamente diagonale). Lasciare vuoto per mantenere il filo orizzontale all'altezza di alimentazione. **Impostare questo valore forza la modalità NEC2** — le formule empiriche non modellano una geometria inclinata. | vuoto (filo orizzontale) |
| **Counterpoise end height** | Stessa idea, per l'estremità lontana del contrappeso. Lasciare vuoto per tenerlo alla stessa quota del punto di alimentazione. | vuoto (quota dell'antenna) |

### 7.8 Sezione "Maximum retries"

- **Che cos'è:** se il candidato vincente cade esattamente sul *bordo* della finestra di ricerca (per esempio la lunghezza migliore coincide con `wire-max`), è un indizio che l'ottimo vero possa stare fuori dalla finestra esplorata. Questa impostazione dice al programma di rieseguire automaticamente la ricerca, fino a N volte aggiuntive.
- **Controllo:** spinbox da `0` a `10`.
- **Predefinito:** `0` (disattivato — nessun tentativo automatico).

Cosa faccia esattamente un tentativo — spostare la finestra o affinarla — dipende dalla casella descritta in [7.10](#710-casella-test-all--test-window-e-refine-top-n).

### 7.9 Sezione "Report options"

- **Top N** — quanti tra i migliori candidati elencare nel report finale ordinato.
- **Controllo:** spinbox da `5` a `200`.
- **Predefinito:** `20`.

### 7.10 Casella "Test All / Test Window" e "Refine top N"

Nella finestra questo controllo si trova subito sotto il campo **Search margin** (7.1); è descritto per ultimo qui solo per non alterare la numerazione delle altre sezioni rispetto alle revisioni precedenti del manuale.

Decide **che cosa fa un tentativo** (7.8), e quindi non ha alcun effetto se **Maximum retries** vale `0`.

- **Spuntata — "Test All"** (predefinito) — un tentativo **sposta** la finestra di ricerca verso l'esterno, con i passi di griglia originali, quando il vincitore cade su un bordo. È il comportamento descritto in 7.8 e non aggiunge alcun flag alla riga di comando.
- **Non spuntata — "Test Window"** — il tentativo **affina** invece di spostare: la passata successiva copre solo il rettangolo che racchiude gli `N` migliori candidati della passata precedente (con un passo corrente di margine, limitato alla finestra già esplorata) e **dimezza entrambi i passi di griglia**. Si ripete fino a esaurire i tentativi o finché entrambi i passi raggiungono il limite di `0.01` m, sotto il quale dimezzare ancora non ha senso rispetto alla precisione reale di taglio. Togliere la spunta aggiunge `--test-window` al comando.
- **Spinbox "Refine top N"** — quanti candidati definiscono quel rettangolo. Intervallo `1`–`50`, predefinito `5`. Usato solo in modalità Test Window; emette `--refine-top N`.

Usare Test Window quando si sa già all'incirca dove sta l'ottimo e si vuole una risoluzione più fine del passo di griglia; usare Test All quando non si è ancora certi che l'ottimo sia dentro la finestra.

---

## 8. Scheda 3 — Fisica

Questa scheda controlla il **motore di simulazione**, il **modello di terreno**, il **modello di alimentazione**, le proprietà del **conduttore** e l'**accuratezza numerica** (segmentazione) della simulazione NEC2.

### 8.1 Sezione "Evaluation mode"

Tre pulsanti di opzione mutuamente esclusivi:

- **`auto`** (predefinito) — usa la simulazione NEC2 se si trova un binario `nec2c` funzionante; altrimenti ripiega sulle formule empiriche.
- **`nec2`** — usa sempre la simulazione NEC2 completa. Fallisce con un errore se non è disponibile alcun binario.
- **`empirical`** — usa sempre le formule approssimate, anche se `nec2c` è disponibile. Utile per una prima passata rapida e grossolana.

### 8.2 Riga "NEC2 binary"

- **Campo di testo:** il percorso esplicito dell'eseguibile `nec2c`. Lasciare vuoto per affidarsi alla ricerca automatica (vedere [3.4](#34-individuazione-del-binario-nec2c)).
- **Pulsante Browse:** apre un selettore di file.
- **Pulsante Auto-detect:** esegue subito la stessa ricerca che l'ottimizzatore fa all'avvio (`$NEC2C`, `PATH`, percorsi comuni) e compila il campo se trova qualcosa.
- Una riga di suggerimento sotto spiega l'ordine di ricerca.

### 8.3 Sezione "Ground"

Controlla le proprietà elettriche del terreno sotto l'antenna, usate dal modello di terreno Sommerfeld-Norton:

| Campo | Significato | Predefinito |
|---|---|---|
| **Conductivity** | Conducibilità del terreno, in siemens per metro (S/m) | `0.005` S/m |
| **Permittivity** | Permittività relativa del terreno (adimensionale) | `13.0` |

**Preset rapidi** — cinque pulsanti riempiono immediatamente entrambi i campi con valori di riferimento d'uso comune:

| Preset | Conducibilità (S/m) | Permittività |
|---|---|---|
| Terreno scarso | `0.001` | `5` |
| Terreno medio | `0.005` | `13` |
| Terreno buono | `0.010` | `20` |
| Terreno eccellente | `0.030` | `25` |
| Acqua salata | `5.000` | `80` |

### 8.4 Sezione "Ground model"

Due pulsanti di opzione mutuamente esclusivi:

- **`sommerfeld`** (predefinito) — usa il modello di terreno Sommerfeld-Norton di NEC2, che tiene conto correttamente dei valori finiti di conducibilità e permittività qui sopra. Fisicamente realistico, consigliato per installazioni reali.
- **`perfect`** — assume un terreno perfettamente conduttore (un'idealizzazione). È più veloce ma ottimistico e irrealistico per la maggior parte dei siti reali; utile soprattutto per confronti o verifiche di sanità.

Un suggerimento sotto spiega il compromesso.

### 8.5 Sezione "Feed model" (modello di alimentazione)

Nella finestra questa sezione sta tra **Ground model** (8.4) e **Wire / conductor** (8.6). Sceglie **dove viene posta la carta di eccitazione (`EX`) di NEC-2 rispetto alla giunzione tra radiatore e contrappeso** — una scelta puramente numerica che non cambia l'antenna modellata, ma solo la rapidità con cui il modello converge vicino al punto di alimentazione.

Due pulsanti di opzione mutuamente esclusivi:

- **`straddle`** (predefinito) — quando il conduttore di ritorno è collineare e opposto al radiatore (il caso usuale di radiatore orizzontale + contrappeso orizzontale), entrambi i fili sono scritti come **un'unica carta `GW` continua** e la sorgente è posta sul segmento che *contiene* il nodo di alimentazione. Sotto la sorgente non resta così alcuna giunzione. Stessa struttura fisica — stessi estremi, stesso raggio, stessa lunghezza totale — ma la resistenza al punto di alimentazione si assesta già a ~180 segmenti per mezza onda, invece di continuare a muoversi ben oltre il migliaio, e sparisce lo scostamento di mezzo segmento che il modello a giunzione deve altrimenti giustificare nel report.
- **`junction`** — il modello storico: due carte `GW` che si incontrano nel nodo di alimentazione, con la sorgente sul segmento 1 del filo 1. La singolarità della sorgente e la condizione di continuità di carica della giunzione cadono così sullo *stesso* segmento, una configurazione notoriamente a convergenza lenta in NEC-2. Utile soprattutto per confrontarsi con risultati vecchi o con altri strumenti.

Le geometrie il cui conduttore di ritorno **non** è collineare — contrappeso pendente, picchetto di terra, spezzone coassiale, radiatore inclinato con contrappeso orizzontale — non possono essere fuse in un unico filo senza cambiare la forma vicino all'alimentazione, quindi ricadono automaticamente sul modello a giunzione, qualunque sia questa impostazione.

Se non si stanno riproducendo risultati vecchi, lasciare `straddle`. Da riga di comando è `--feed-model {straddle,junction}`; la GUI aggiunge il flag solo quando si sceglie il valore non predefinito.

### 8.6 Sezione "Wire / conductor"

Controlla il filo fisico usato nel modello:

- **Wire diameter (mm)** — diametro del conduttore. Il valore predefinito corrisponde a un filo di 2 mm di diametro (1 mm di raggio), all'incirca rame AWG 12.
- **Wire material** — menu a discesa di materiali conduttori, ciascuno con una conducibilità fissa:

  | Materiale (chiave inglese) | Conducibilità (S/m) |
  |---|---|
  | Copper (predefinito) | 5.80 × 10⁷ |
  | Aluminium / Aluminum | 3.54 × 10⁷ |
  | Brass | 1.56 × 10⁷ |
  | Silver | 6.30 × 10⁷ |
  | Steel (zincato) | 6.99 × 10⁶ |
  | Perfect (senza perdite, solo per confronto) | — (nessuna carta di perdita scritta) |

  L'etichetta del menu è mostrata nella lingua corrente della GUI (es. "rame" in italiano), ma internamente il programma invia sempre il nome canonico inglese allo script sottostante, quindi cambiare lingua non altera mai questa impostazione.

- **Wire conductivity override (S/m)** — campo facoltativo per indicare a mano una conducibilità che non corrisponde a nessuno dei materiali standard. Lasciare vuoto per usare il valore implicito del materiale scelto.

> **Perché conta:** senza un'impostazione di conducibilità/perdita, NEC2 assume che ogni filo sia un conduttore *perfetto*, il che sovrastima il guadagno — proprio nelle geometrie che questo strumento tende a preferire (contrappesi corti, impedenze elevate), dove le perdite I²R in un filo da 1 mm non sono trascurabili. Impostare un materiale reale dà cifre di guadagno realistiche e leggermente più conservative.

### 8.7 Sezione "Accuracy / Segmentation"

NEC2 suddivide ogni filo in brevi "segmenti" di calcolo; il numero di segmenti per mezza lunghezza d'onda influisce fortemente sull'accuratezza, soprattutto sull'impedenza al punto di alimentazione (più che sulla sola forma del diagramma) — la densità di segmentazione può cambiare sia R sia X. **Più segmenti non garantiscono di per sé l'accuratezza fisica**: la convergenza va verificata, e NEC2 resta comunque un modello numerico di una geometria idealizzata.

Tre pulsanti di opzione mutuamente esclusivi:

- **`fine`** (predefinito) — 180 segmenti per mezza lunghezza d'onda. È la densità usata per ogni cifra che viene effettivamente pubblicata (le cifre finali del candidato vincente, il file `.nec` esportato, il report, il CSV). **Non è una garanzia di convergenza** — consigliata per qualunque cosa si intenda costruire, ma da abbinare a "Re-check convergence" per un progetto definitivo.
- **`fast`** — 21 segmenti per mezza lunghezza d'onda. È deliberatamente grossolana: il modello di errore di segmentazione del programma colloca l'incertezza risultante su R intorno al **28–31 % (misurata per difetto)**, e può anche produrre **errori di segno sulla reattanza**.[^nota-fast] È pensata per sweep rapidi e per il solo lavoro sui diagrammi — le sue impedenze non vanno mai usate per dimensionare una rete di adattamento o per decidere una costruzione.
- **`custom`** — si digita il proprio valore di segmenti per mezza onda nel campo adiacente. Il valore interno predefinito per lo *sweep* di ricerca (a differenza delle cifre finali pubblicate) è 45 segmenti per mezza onda — una via di mezzo scelta perché la classifica relativa dei candidati è poco sensibile a questa densità, anche se i valori assoluti non lo sono. Se questa opzione non sovrascrive entrambi, lo sweep normale usa 45 segmenti per mezza onda e l'esecuzione finale 180. Il valore è comunque limitato all'intervallo `5`–`400`.

[^nota-fast]: Il messaggio di console/report che accompagna `--fast` calcola questa percentuale dal vivo usando il modello di errore calibrato del programma (`estimated_imp_uncertainty_pct()`, adattato come errore% ≈ 420 / spw^0.86 rispetto a un riferimento estrapolato con Richardson), che a 21 segmenti per mezza onda dà ~30,6% — è la cifra citata sopra. Una stringa di aiuto statica della GUI, altrove nel codice sorgente, mostra ancora una vecchia cifra non aggiornata di "~14%" rimasta da prima che quel modello venisse ricalibrato; considerare corretto il valore calcolato dinamicamente (e la cifra di questo manuale).

**Casella "Re-check convergence"** — quando è attiva (CLI: `--converge`), la geometria vincente viene risimulata a **0.5× e 2× la densità di segmentazione di lavoro**, e il report indica di quanto si siano ancora mossi R e X tra quelle esecuzioni. I fattori *circondano* la densità di lavoro invece di limitarsi a raffinarla: con la densità di pubblicazione già a 180 segmenti per mezza onda, un braccio a 4× verrebbe tagliato dal limite di sicurezza di 400 segmenti per mezza onda e produrrebbe due righe quasi identiche — cioè un controllo di convergenza incapace di vedere qualsiasi deriva. La deriva di ogni riga è misurata rispetto alla più fine, quindi il verdetto non dipende da quale densità si consideri "di base".

La soglia di circa 3 % riguarda la deriva di R; X ha una tolleranza propria. Se R si muove di più di circa il 3 %, il report lo segnala — segno che conviene aumentare ancora la densità fine prima di costruire; se la convergenza non è soddisfacente, non usare X per dimensionare una rete di adattamento.

Vale la pena conoscere due condizioni e un'interazione:

- Il controllo gira solo in **modalità NEC2 con un binario `nec2c` funzionante**. In modalità empirica viene saltato silenziosamente, perché non c'è segmentazione da variare.
- Con **Fast** attivo (`--fast-run`, vedere [10.1](#101-sezione-opzioni)) resta solo il **braccio a 0.5×**. Il braccio a 2× raddoppia il numero di segmenti e il costo di NEC-2 cresce all'incirca come N³, quindi quella singola esecuzione può pesare più di tutto il resto del programma. Il controllo continua a misurare la deriva, su un intervallo di densità di 2:1 invece di 4:1, e l'intestazione del report indica quali fattori sono stati usati.

> **Importante:** le cifre NEC2 sono risultati di un modello, non misure dell'antenna reale. Altezza, geometria, conduttore, terreno, perdite, oggetti vicini e l'installazione effettiva possono cambiare il risultato. Per una costruzione definitiva, verificare il sistema reale con una misura (per esempio un VNA) prima di tagliare o installare in modo permanente.

---

## 9. Scheda 4 — File di output

Questa scheda controlla **dove** vengono scritti i risultati e **come si chiamano**.

### 9.1 Sezione "Working directory"

- **Campo:** la cartella in cui verranno scritti tutti i file di output.
- **Predefinito:** la propria cartella home.
- **Pulsante Browse:** apre un selettore di cartelle.
- Una riga di suggerimento spiega che la cartella viene creata automaticamente se non esiste.

### 9.2 Sezione "Output files"

Sette nomi di file modificabili singolarmente, tutti scritti dentro la cartella di lavoro. Alcuni output dipendono dai pacchetti opzionali installati e dalla modalità di valutazione scelta:

| Campo | Nome predefinito | Contenuto |
|---|---|---|
| `out-txt` | `optimizer_report.txt` | Report ordinato con i migliori N candidati, l'insieme Pareto-ottimale e un'interpretazione in linguaggio semplice del vincitore |
| `out-png` | `optimizer_plot.png` | Mappa di calore/grafico a dispersione dello spazio di ricerca più i grafici a barre del ROS per banda |
| `out-csv` | `optimizer_best.csv` | Cifre per banda (frequenza/R/X) del candidato vincente, leggibili da programma — è il file che la scheda UnUn/Transmatch legge automaticamente |
| `out-nec` | `best_antenna.nec` | File di ingresso NEC2 della geometria vincente, con carte RP per le bande attive; caricabile in strumenti NEC2 compatibili, con i limiti della loro implementazione |
| `out-radiation` | `radiation_diagrams.png` | Diagrammi di radiazione per ogni banda attiva; generati solo con valutazione NEC2 |
| `out-construction` | `antenna_construction.png` | Disegno costruttivo quotato da cui si può costruire |
| `out-pdf` | `antenna_brochure.pdf` | Riepilogo PDF di una pagina ("opuscolo") con le cifre chiave, i grafici e il disegno costruttivo |

Non conviene lasciare vuoto nessuno di questi campi: l'output corrispondente semplicemente non verrebbe prodotto con un nome prevedibile. I valori predefiniti vanno bene in quasi tutti i casi.

---

## 10. Scheda 5 — Esecuzione

Qui si lancia l'ottimizzatore, si segue l'avanzamento e si salta direttamente ai file generati.

### 10.1 Sezione "Opzioni"

Tre caselle di spunta e un campo numerico:

- **Fast** — aggiunge `--fast-run`, l'intera politica di accelerazione del programma. **Predefinito nella GUI: non spuntata**, così un flusso di lavoro esistente conserva esattamente il comportamento — e le cifre — che aveva prima che questa casella esistesse. Quando è attiva: risolve in parallelo i file `nec2c` indipendenti (nello sweep, nella passata di raffinamento fine e nella ri-classificazione per diagramma di radiazione); esegue lo sweep con la segmentazione grossolana, come `--fast`; ricalcola meno candidati alla densità di pubblicazione (il vincitore e il fronte di Pareto lo sono sempre, ma la coda della tabella TOP-N conserva la propria etichetta di densità di sweep, che il report stampa riga per riga); accorcia a 3 la rosa della ri-classificazione per radiazione; e mantiene solo il braccio a 0.5× del controllo di convergenza. Tutti questi compromessi restano visibili nel report — le impedenze pubblicate del vincitore **non** sono toccate, perché la densità finale non cambia. Attenzione: `--fast-run` **non** è `--fast`, che imposta solo la segmentazione dello sweep ed è collegato ai pulsanti Segmentation della scheda Fisica ([8.7](#87-sezione-accuracy--segmentation)).
- **Quiet** — aggiunge `--quiet`, sopprimendo i messaggi di avanzamento dettagliati e mantenendo risultati e avvisi importanti. **Predefinito nella GUI: spuntata.** Toglierla per il massimo dettaglio diagnostico.
- **No interactive prompts** — aggiunge `--no-interactive`, dicendo all'ottimizzatore di fallire subito se manca un dato obbligatorio invece di fare una domanda sul terminale. **Predefinito nella GUI: spuntata.**

- **Jobs** — un campo numerico, **vuoto per impostazione predefinita**, che aggiunge `--jobs N`: quanti processi `nec2c` vengono risolti in parallelo. Lasciandolo vuoto la GUI non emette alcun flag, il che significa seriale in modalità normale e un worker per core (con tetto di 16) sotto **Fast** — esattamente ciò che fa già qualunque riga di comando salvata in precedenza.

> **`--jobs` e `--fast-run` sono ortogonali, e `--jobs` funziona da solo.** `--jobs N` dà *la stessa risposta, prima*: i risultati sono memorizzati per indice di griglia e riassemblati nell'ordine della griglia, quindi l'elenco dei candidati, la classifica, il fronte di Pareto e tutte le impedenze pubblicate sono identici bit per bit a un'esecuzione seriale — cambia solo il tempo di calcolo. `--fast-run` compra velocità calcolando una risposta *diversa e più economica*. Perciò `--jobs` è onorato in **entrambe** le modalità; le versioni precedenti lo forzavano a 1 se non veniva dato anche `--fast-run`, e quella restrizione è stata rimossa (costava di più proprio in modalità normale, dove sta il lavoro pesante). Valori predefiniti: `1` (seriale) senza `--fast-run`, e un worker per core con tetto di 16 con `--fast-run` e senza `--jobs`. Il programma stampa una nota se `N` supera il numero di core rilevati, e un'altra se il motore è a sua volta una build MPI (`nec2c-mpich`), dove N worker × M rank sovraccaricano pesantemente la macchina.

### 10.2 Riquadro "Command preview"

Un riquadro di testo in sola lettura che mostra la **riga di comando esatta** che la GUI sta per eseguire, costruita dal vivo da ogni impostazione di ogni scheda. Si aggiorna da solo, senza premere alcun pulsante, ogni volta che si modifica un campo qualsiasi del programma (con un breve ritardo, così una raffica di tasti non lo fa lampeggiare). Per rieseguire l'ottimizzatore a mano dal terminale con le stesse identiche impostazioni, basta copiare questo testo.

### 10.3 Comandi Run / Stop e stato

- **Pulsante Run** — avvia l'ottimizzatore come processo in background. Prima di partire la GUI:
  1. Verifica che tutti i campi possano essere assemblati in un comando valido (in caso contrario una finestra di errore spiega cosa non va).
  2. Conferma che il file dello script esista sul disco.
  3. Crea la cartella di lavoro se non esiste.

  Durante l'esecuzione il pulsante Run è disabilitato, Stop diventa attivo e una barra di avanzamento si anima.

- **Pulsante Stop** — termina immediatamente il processo in corso. Attivo solo durante un'esecuzione.

- **Pulsante "Show report"** — apre il report di testo generato nel visualizzatore predefinito del sistema. Attivo solo dopo un'esecuzione conclusa con successo **e** se il file esiste.

- **Pulsante "Show radiation pattern"** — apre il PNG dei diagrammi di radiazione nel visualizzatore di immagini predefinito. Stessa condizione di attivazione.

- **Pulsante "Show PDF"** — apre l'opuscolo PDF nel visualizzatore PDF predefinito. Stessa condizione di attivazione.

- **Etichetta di stato** — mostra a parole lo stato corrente: inattivo, in esecuzione, concluso con successo, concluso con errore/codice di uscita, o interrotto dall'utente.

### 10.4 Console e pannello Riepilogo

La parte inferiore della scheda Esecuzione è divisa in due pannelli da un separatore trascinabile: la **Console** a sinistra e il **Riepilogo** a destra. Trascinare il separatore per dare a ciascun lato la larghezza desiderata.

#### 10.4.1 Console (pannello sinistro)

Un'area di testo scorrevole, in sola lettura, che riproduce byte per byte tutto ciò che il processo dell'ottimizzatore stampa sulla propria console, in tempo reale, con una semplice codifica a colori:

- **Rosso** — righe che contengono parole chiave di errore (error, failed, traceback).
- **Giallo** — righe che contengono parole chiave di avviso.
- **Verde** — righe che indicano successo (saved, done, best, segni di spunta).
- **Colore di intestazione** — righe separatrici di sezione.

Un pulsante **Clear** svuota la vista della console (non tocca i file già scritti).

#### 10.4.2 Riepilogo (pannello destro)

Lo stesso flusso di output, digerito in una pagina di stato dal vivo: che cosa sta girando adesso, su quali dati, con quali variabili e come è finita la passata precedente. Nulla viene filtrato via dalla console; il Riepilogo ne è una rappresentazione aggiuntiva. Si ridisegna a intervalli limitati (e batte una volta al secondo perché il cronometro continui a scorrere tra una riga e l'altra), quindi non costa nulla di misurabile nemmeno durante uno sweep NEC2 lungo. Contiene quattro blocchi:

1. **Che cosa sta girando adesso** — la fase corrente a parole (avvio, sweep in modalità NEC2 o empirica, raffinamento, espansione della finestra, ricerca dell'UnUn, ri-classificazione per radiazione, ricalcolo alla densità di pubblicazione, controllo di convergenza, scrittura degli output, diagrammi di radiazione, PDF, concluso, fallito) con una riga che spiega che cosa fa quella fase; lo stato finale a esecuzione terminata; l'avanzamento come *fatti/totale* con percentuale; il candidato in valutazione (filo, contrappeso, banda); la velocità in candidati al secondo e una stima del tempo rimanente — entrambe nascoste per i primi secondi, dato che una velocità misurata su una frazione di secondo è rumore — e il tempo trascorso.
2. **Variabili in gioco** — il tipo di passata, le finestre di filo e contrappeso con i passi correnti, la dimensione della griglia come *n_filo × n_cp = coppie*, il motore di valutazione, la densità di segmentazione in uso, il rapporto dell'UnUn (compresa la transizione seme→attuale e in quale passata è cambiato), il contatore dei tentativi e il miglior candidato finora con il suo punteggio.
3. **Risultato dell'ultima passata** — numero e tipo di passata, motore, finestre coperte, quanti candidati ha valutato, quanti sono risultati Pareto-ottimali, la sua geometria e il suo punteggio migliori, un verdetto (migliore / invariato) e quanto è durata.
4. **Eventi** — conteggi cumulativi di avvisi ed errori, il più recente di ciascun tipo per esteso, e l'elenco dei file di output già scritti.

Il Riepilogo viene ricostruito nella lingua corrente della GUI come ogni altra etichetta, e conserva la posizione di scorrimento tra un ridisegno e l'altro.

### 10.5 Caricamento automatico a fine esecuzione

Quando un'esecuzione si conclude con successo, la GUI tenta automaticamente di caricare in background il `optimizer_best.csv` appena prodotto nella scheda **UnUn / Transmatch** (sezione 11), così i calcolatori di adattamento sono già popolati con le impedenze dell'antenna nel momento in cui l'ottimizzazione finisce — non serve cambiare scheda e ricaricare a mano (ma lo si può comunque fare, con il pulsante Reload descritto in 11.1).

---

## 11. Scheda 6 — UnUn / Transmatch

Questa scheda è **indipendente dall'esecuzione dell'ottimizzatore**: si può usare in qualsiasi momento, con qualsiasi dato di impedenza, anche senza aver mai lanciato un'ottimizzazione. Contiene due sotto-schede.

### 11.1 Sotto-scheda: UnUn Toroid

Progetta un autotrasformatore a banda larga (UnUn) avvolto su un nucleo toroidale di ferrite o polvere di ferro — o, a scelta, in aria — per trasformare l'impedenza al punto di alimentazione dell'antenna verso un'impedenza coassiale standard (tipicamente 50 Ω).

#### 11.1.1 Sezione "Antenna"

- **Selettore di banda (menu a discesa)** — una volta caricati i dati d'antenna (vedere sotto), permette di scegliere con quale banda lavorare; selezionandone una, i campi sottostanti si compilano con frequenza, R e X di quella banda.
- **Pulsante Reload** — rilegge il file `optimizer_best.csv` dalla posizione di output configurata, aggiornando il menu delle bande e i dati.
- **Pulsante Export** — scrive il contenuto di **entrambe** le sotto-schede in un file di testo (si apre una finestra Salva con nome sulla cartella di lavoro, con `unun_transmatch.txt` proposto): il pannello dei risultati dell'UnUn, la tabella multibanda, i risultati delle prese del Transmatch e il testo di costruzione della bobina. Se `matplotlib` è disponibile, salva accanto anche il disegno della bobina del Transmatch, come `<nome>_transmatch.png`. Quando una delle impedenze caricate proviene dal modello empirico invece che da NEC2, quell'avvertenza viene scritta anche nel file esportato, così la provenienza viaggia insieme ai numeri.
- **Riga di stato** — indica se i dati d'antenna sono stati caricati e da dove.
- Campi modificabili a mano (compilati dal selettore di banda, ma liberamente editabili per esplorare ipotesi senza rieseguire l'ottimizzatore):
  - **Frequency (MHz)** — predefinito `7.100`.
  - **R_out, X_out (Ω)** — l'impedenza lato antenna (uscita) *da cui* l'UnUn deve trasformare. Predefiniti `450`, `150`.
  - **R_in, X_in (Ω)** — l'impedenza lato coassiale (ingresso) *verso cui* l'UnUn deve trasformare. Predefiniti `50`, `0`.

#### 11.1.2 Sezione "Core" (nucleo)

- **Casella del tipo di nucleo** — **spuntata (predefinito) = "Core"**: il trasformatore è avvolto su un **toroide** di ferrite o polvere di ferro, il menu dei nuclei è attivo e vengono mostrati i risultati magnetici (saturazione, perdite del nucleo, potenza ammissibile). **Non spuntata = "Air"**: il trasformatore è realizzato come **solenoide monostrato in aria**; il menu dei toroidi è disabilitato, al suo posto si attivano i due campi del supporto, e i risultati propri del toroide sono nascosti. L'etichetta accanto alla casella indica sempre in quale modalità ci si trova.
- **Menu a discesa Core** — sceglie il codice del toroide dal database interno (vedere la [sezione 19](#19-appendice--database-dei-nuclei-toroidali) per l'elenco completo). Predefinito: `FT-240-31`. Attivo solo in modalità Core.
- **Riga informativa** — mostra le specifiche principali del nucleo scelto (materiale, A_L, diametro esterno/interno, altezza, area efficace).
- **Diametro del supporto (mm)** — predefinito `50`. Attivo solo in modalità Air.
- **Spazio tra le spire (mm)** — predefinito `1.0`. Attivo solo in modalità Air.
- **Casella della modalità di rapporto** — **spuntata (predefinito) = "Compensate"**: il rapporto spire è calcolato automaticamente da R_out / R_in. **Non spuntata = "Ratio"**: l'UnUn è costruito per un rapporto **fisso** digitato nel campo Ratio (es. 9, 49, 64); R_out / R_in non fissano più il rapporto spire, ma continuano ad alimentare la compensazione di reattanza e la sezione multibanda.
- **Campo Ratio** — il rapporto fisso usato quando la casella precedente non è spuntata. Predefinito `9`.
- **Numero di spire primarie (Np)** — predefinito `15`.
- **Diametro del filo (mm)** — predefinito `2.0`.
- A destra di questi campi viene disegnato un **diagramma costruttivo** — del toroide avvolto, o del solenoide in modalità Air. Il pulsante **AGGIORNA DISEGNO** lo ridisegna dalle impostazioni correnti, il pulsante **Salva PNG…** lo scrive dove si vuole (`unun_toroid.png` o `unun_solenoid.png` come nomi predefiniti) e un clic sull'immagine la apre ingrandita. Il disegno richiede `matplotlib`; senza quella libreria il pannello mostra un segnaposto.

#### 11.1.3 Pannello "Results" (risultati)

Un pannello di testo scorrevole, a spaziatura fissa e con codifica a colori, che riporta il progetto dell'UnUn calcolato: rapporto spire, impedenza trasformata, qualità di adattamento attesa, stima di perdita/riscaldamento del nucleo ed eventuali avvisi (per esempio spire insufficienti, o nucleo vicino alla saturazione o alla sovratemperatura).

#### 11.1.4 Sezione "Multi-band"

Poiché un unico progetto di UnUn viene usato su tutte le bande coperte dall'antenna, questa sezione valuta quanto bene **un UnUn scelto** si comporti su **tutte** le bande caricate dal CSV dell'ottimizzatore contemporaneamente — non solo sulla singola banda selezionata sopra.

- **Casella Auto** (spuntata per impostazione predefinita) — quando è attiva, il programma cerca automaticamente il miglior valore di componente e il miglior rapporto spire su tutte le bande; quando non lo è, i valori si inseriscono a mano.
- **Menu Type** — `L`, `C` o `none`: se la rete di compensazione multibanda è induttiva, capacitiva o assente. Predefinito `C`.
- **Campo Value** — il valore del componente scelto a mano (usato solo con Auto non spuntata). L'unità mostrata accanto (µH o pF) segue la scelta L/C.
- **Campo Ratio** — il rapporto spire scelto a mano (usato solo con Auto non spuntata).
- **Campo Z0** — l'impedenza di riferimento della valutazione multibanda. Predefinito `50` Ω.
- **Tabella dei risultati** — una riga per banda, con: nome della banda, frequenza, R, X, reattanza di compensazione, impedenza d'ingresso risultante, ROS senza e con compensazione, e la differenza tra i due.

### 11.2 Sotto-scheda: Transmatch

Progetta una rete di adattamento a bobina con prese (stile autotrasformatore) — il classico "Transmatch" o ATU — come alternativa o complemento all'UnUn.

#### 11.2.1 Sezione "Global" (globale)

| Campo | Significato | Predefinito |
|---|---|---|
| Z0 | Impedenza di riferimento/obiettivo | `50` Ω |
| Wire diameter | Diametro del filo della bobina | `1.0` mm |
| Coil former diameter | Diametro del supporto della bobina | `50` mm |
| Space between turns | Spaziatura tra le spire | `1.0` mm |
| Turns at the Z₀ tap | Numero di spire usate come presa di riferimento Z0 | vuoto |
| **Casella auto** | Quando è spuntata, l'avvolgimento di riferimento è calcolato automaticamente invece che inserito a mano | spuntata |

> **Nota ingegneristica incorporata nello strumento:** una bobina con prese si comporta da autotrasformatore ideale solo *al di sotto* della propria frequenza di autorisonanza (SRF). Sopra la SRF l'avvolgimento diventa dominato dalla capacità e il semplice modello del rapporto spire non vale più — eppure progetti ingenui potevano riportare in silenzio un ROS plausibile (ma sbagliato) per una banda che in realtà sta sopra la SRF dell'avvolgimento. Questo strumento controlla la SRF e accorcia/aggiusta l'avvolgimento di riferimento automatico finché la SRF non supera la banda più alta richiesta con un margine di sicurezza (1,5×), e segnala le righe in cui la reattanza dell'avvolgimento non è comodamente maggiore dell'impedenza d'antenna (segno che la presa è "caricata" dalla bobina invece di trasformare attraverso di essa).

#### 11.2.2 Tabella "Taps" (prese)

Una tabella modificabile di massimo **11 righe**, ciascuna corrispondente a una banda che il Transmatch deve coprire, con le colonne: **Tap #**, **Band**, **Frequency (MHz)**, **R (Ω)**, **X (Ω)** e una casella **Active** per includere o escludere la riga dal calcolo. Tre righe sono precompilate con i valori di esempio del foglio di lavoro (40 m / 20 m / 10 m), così la pagina è utilizzabile anche prima di aver mai eseguito l'ottimizzatore:

| # | Banda | Freq (MHz) | R (Ω) | X (Ω) |
|---|---|---|---|---|
| 1 | 40m | 7.150 | 75 | −12 |
| 2 | 20m | 14.170 | 67 | 23 |
| 3 | 10m | 28.000 | 45 | 10 |

Accanto alla tabella viene disegnato un **diagramma costruttivo** della bobina e delle sue prese, con gli stessi pulsanti di aggiornamento e salvataggio della sotto-scheda UnUn (`transmatch_coil.png` come nome predefinito).

#### 11.2.3 Tabella dei risultati "Winding" (avvolgimento)

Per ogni riga di presa attiva: banda, frequenza, R, R realizzata (dopo la quantizzazione della presa), errore risultante, spire rispetto al riferimento, spire totali/differenziali, lunghezza del filo, resistenza in continua, lunghezza cumulativa, impedenza e fase risultanti, ROS, perdita di ritorno, perdita di disadattamento e frazione di potenza riflessa.

#### 11.2.4 Tabella dei risultati "Compensation" (compensazione)

Per ogni riga di presa attiva, tredici colonne: banda, frequenza, R, X, la reattanza trasformata **X′** vista alla presa, il **ROS senza compensazione**, i valori equivalenti di induttore e condensatore in **serie**, i valori equivalenti di induttore e condensatore in **derivazione**, la **resistenza vista dopo il ramo in derivazione**, il **ROS della soluzione in derivazione (reale)** e, infine, il **ROS della soluzione serie ammettendo un residuo del 5 %** — quest'ultima colonna è una tolleranza del *5 per cento* sulla reattanza residua, non di 5 Ω.

Serie e derivazione sono due risposte diverse allo stesso problema, e la tabella le mostra deliberatamente entrambe. Una singola reattanza *in derivazione* cancella la suscettanza del carico trasformato, il che lascia la porta a vedere (R′² + X′²)/R′ invece di R′ — un buon adattamento solo finché X′ resta piccola. Sopra un ROS residuo di circa 1,5 il ramo in derivazione va letto come cancellazione di reattanza e non come alternativa al ramo serie, le cui cifre sono quelle pubblicate dalla tabella delle prese.

#### 11.2.5 Pannello di testo "Coil construction" (costruzione della bobina)

Un riepilogo a spaziatura fissa e con codifica a colori di come avvolgere fisicamente la bobina: spire totali, posizione di ogni presa, lunghezza di filo necessaria ed eventuali avvisi (spire insufficienti, spaziatura delle prese non realistica, ecc.).

#### 11.2.6 Nota guida per la costruzione

Un breve promemoria in fondo alla sotto-scheda con indicazioni pratiche di costruzione.

---

## 12. Barra dell'intestazione e controlli globali

### 12.1 Percorso dello script

In cima alla finestra, sotto l'intestazione, una riga permette di indicare **quale file di script** la GUI deve eseguire davvero quando si preme "Run".

- **Campo:** percorso del file `Long_Wire_Antenna.py`.
- **Predefinito:** il percorso dello script usato per avviare la GUI stessa.
- **Pulsante Browse:** apre un selettore di file.

Serve solo se si tengono più versioni dello script e si vuole cambiare quale viene pilotata, senza riavviare la GUI da una copia diversa.

### 12.2 Dimensione del carattere

Due piccoli pulsanti (`−` e `+`) accanto a un'etichetta numerica permettono di rimpicciolire o ingrandire al volo il carattere della GUI, utile su schermi ad alta risoluzione o per comodità visiva. La dimensione corrente è mostrata tra i due pulsanti.

### 12.3 Lingua

Un pulsante nell'intestazione commuta la **lingua di visualizzazione della GUI** tra inglese, spagnolo e italiano. È cosa distinta da:

- L'impostazione "Optimizer language" della scheda Banda / Sorgente (sezione 6.7), che controlla la lingua dell'**output di console e del report/PDF generati dall'ottimizzatore**, non quella delle etichette della GUI.
- Il flag `--lang` della CLI, che riguarda solo le esecuzioni da riga di comando senza GUI.

Cambiando lingua vengono rietichettati sul posto ogni scheda, campo, menu e suggerimento, senza perdere nulla di ciò che è stato digitato — compreso il menu del materiale del filo, che internamente è sempre tracciato con il suo valore canonico inglese, così la riga di comando non ne risente mai.

---

## 13. Comprendere i file di output

### 13.1 Il report di testo (`optimizer_report.txt`)

Contiene, nell'ordine generale:

1. Un riepilogo dell'esecuzione: bande valutate, bande attive, modalità di valutazione, geometria, terreno, conduttore e segmentazione.
2. Una tabella ordinata dei migliori N candidati (secondo l'impostazione "Top N"), ognuno con lunghezza del filo, lunghezza del contrappeso, R/X/ROS per banda e punteggio aggregato.
3. L'insieme Pareto-ottimale: i candidati per i quali nessun altro è almeno altrettanto buono su *tutte* le bande contemporaneamente — l'insieme dei compromessi reali, utile quando si è disposti a sacrificare prestazioni su una banda per guadagnarne su un'altra.
4. Un'interpretazione in linguaggio semplice del candidato vincente, con eventuali avvisi (es. "la lunghezza del filo potrebbe dover essere maggiore — è finita sul bordo della finestra di ricerca").
5. Quando sono disponibili i dati di diagramma, una tabella del **guadagno massimo e del guadagno all'angolo di elevazione obiettivo (TOA)** per ogni banda attiva, più gli avvisi di TOA elevato.
6. Una tabella per banda con l'impedenza lato antenna (`R_ant`, `X_ant`) e lato trasmettitore (`R_tx`, `X_tx`), il ROS e l'origine del dato.
7. Se è stato usato `--converge` (la casella "Re-check convergence"), una breve sezione che riporta di quanto si siano ancora mossi R e X a 0.5× e 2× la densità di segmentazione di lavoro (solo il braccio a 0.5× con `--fast-run`). L'intestazione di quella sezione indica sempre quali fattori sono stati effettivamente eseguiti.
8. L'analisi dell'UnUn: rapporto scelto, scansione dei rapporti standard, ottimo continuo e miglior rapporto per banda.

Il report può contenere anche avvisi di bordo di ricerca, di geometria, di convergenza e di qualità dei risultati.

### 13.2 Il grafico (`optimizer_plot.png`)

Una rappresentazione a mappa di calore/dispersione dell'intera griglia di ricerca (lunghezza filo × lunghezza contrappeso), colorata secondo il punteggio aggregato, più i grafici a barre del ROS ottenuto su ciascuna banda attiva dal candidato vincente.

### 13.3 Il CSV (`optimizer_best.csv`)

Risultati per banda leggibili da programma, solo per il candidato *vincente*, una riga per banda. Un'esecuzione `long-wire` scrive queste venti colonne:

| Colonna | Significato |
|---|---|
| `band` | Nome della banda come dato sulla riga di comando |
| `freq_mhz` | Frequenza centrale usata per quella banda |
| `active` | `YES` / `NO` — se la banda ha contribuito al punteggio |
| `lambda_half_m`, `lambda_qtr_m` | Mezza e quarto di lunghezza d'onda a quella frequenza, in metri |
| `wire_len_m` | Lunghezza del radiatore vincente |
| `L_over_lhalf` | Lunghezza del radiatore espressa in mezze lunghezze d'onda |
| `R_wire_ohm`, `X_wire_ohm` | **Impedenza lato antenna** — i numeri con cui si dimensiona una rete di adattamento |
| `R_wire_source` | `nec2` o `empirical` — da dove provengono davvero le due colonne precedenti, banda per banda |
| `vswr_no_cp` | ROS lato antenna riferito a 50 Ω, senza UnUn |
| `vswr_no_cp_source` | Sempre `empirical` — indicato riga per riga perché una riga a provenienza mista si descriva da sé |
| `vswr_with_cp` | ROS lato trasmettitore dopo l'UnUn (vuoto per le bande inattive) |
| `Z_eff_ohm` | Modulo dell'impedenza al punto di alimentazione |
| `unun_ratio` | Il rapporto di UnUn usato nella valutazione |
| `avoidance_score`, `quality_rating` | Quanto comodamente la geometria si tiene lontana da una classe di risonanza scomoda, e il relativo giudizio a stelle |
| `cp_len_m`, `cp_height_m`, `num_radials` | Lunghezza del contrappeso vincente, altezza dell'antenna, numero di radiali |

Per un'esecuzione con **dipolo alimentato fuori centro o Carolina Windom** (`--antenna-type ocfd|carolina-windom`) il file porta **sei colonne aggiuntive** dopo quelle venti, così chi lo legge può distinguere i due schemi senza indovinare dai numeri: `antenna_type`, `total_len_m`, `offset_frac`, `short_arm_m`, `long_arm_m` e `vert_len_m` (l'ultima diversa da zero solo per un Carolina Windom). In quello schema `wire_len_m` e `cp_len_m` sono i **bracci lungo e corto** del dipolo, non un radiatore e un contrappeso — leggere `antenna_type` prima di interpretarli.

Vale la pena guardare due volte `R_wire_source` prima di avvolgere qualsiasi cosa: è derivata dalla provenienza che stampano il report e il PDF, non dalla semplice esistenza di un numero, quindi un'esecuzione fatta senza `nec2c` non può mai dichiarare `nec2` qui. **Questo è il file che la scheda UnUn/Transmatch legge automaticamente** per precompilare il menu delle bande e la tabella delle prese — e quella scheda usa proprio questa colonna per avvisare quando si sta per dimensionare un adattamento partendo da stime empiriche.

### 13.4 Il file NEC2 (`best_antenna.nec`)

Un file di ingresso NEC2 che descrive la geometria vincente alla densità di segmentazione finale, comprese le carte RP per le bande attive. È pensato per essere caricato in un'implementazione NEC2 compatibile; il comportamento esatto in esecuzione può variare tra i diversi motori.

### 13.5 Diagrammi di radiazione (`radiation_diagrams.png`)

Grafici del diagramma di elevazione e/o azimut per l'antenna vincente, uno per banda attiva. Sono generati **solo quando la valutazione finale usa NEC2 ed è disponibile un binario NEC2**. In modalità empirica il file non viene prodotto, perché il modello empirico non calcola un diagramma di radiazione.

### 13.6 Disegno costruttivo (`antenna_construction.png`)

Un disegno quotato pensato per essere usato direttamente come riferimento di costruzione: lunghezze dei fili, altezza del punto di alimentazione, angoli di inclinazione, ecc.

### 13.7 Opuscolo PDF (`antenna_brochure.pdf`)

Il programma tenta di generare questo riepilogo di una pagina dopo un'esecuzione riuscita con un candidato valido. Richiede **`reportlab`**, non `matplotlib`. Il PDF può includere il disegno costruttivo e, quando disponibili, i diagrammi di radiazione NEC2. Se `reportlab` non è installato, il programma segnala il problema e salta il PDF; l'esecuzione e gli altri output non dipendono da `reportlab`.

L'inserimento delle immagini costruttive/di radiazione nel PDF usa inoltre il pacchetto **Pillow (`PIL`)** se installato; se Pillow manca, l'opuscolo viene comunque generato, ma la sezione immagine è sostituita da un segnaposto "(disegno costruttivo non disponibile)" invece di fallire.

### 13.8 Limiti importanti degli output e della modellazione

- `matplotlib` è necessario per il grafico dello spazio di ricerca, il disegno costruttivo e i diagrammi di radiazione.
- I diagrammi di radiazione sono esclusivi di NEC2. La modalità empirica può produrre numeri di ottimizzazione, ma non un diagramma fisicamente simulato.
- Il file NEC2 esportato è un modello, non una garanzia di costruzione. Verificare l'antenna reale con analizzatore/VNA e tenere conto delle correnti di modo comune del cavo, dei sostegni, dei conduttori vicini, del terreno reale e della geometria effettiva di installazione.
- Il percorso di ritorno `ground-rod` in NEC2 è realizzato come collegamento galvanico a **terra perfetta (GN 1)**. Non è un modello dell'impedenza di un picchetto reale. Per quel caso il programma commuta il modello di terreno su perfetto e registra un avviso — cosa che sovrascrive, per quella esecuzione, qualsiasi valore impostato in `--ground-model`.
- I calcolatori di adattamento (UnUn e Transmatch) usano modelli ingegneristici e componenti idealizzati. I loro valori sono punti di partenza per costruire e mettere a punto, non valori misurati, e non sostituiscono la verifica finale in RF.

---

## 14. Interfaccia a riga di comando (CLI) — riferimento completo

Ogni flag corrisponde a un controllo della GUI descritto sopra; questa tabella è il riferimento autorevole per nomi, tipi e valori predefiniti, utile per eseguire lo strumento da script, da cron o da terminale invece che dalla GUI.

| Flag | Tipo | Predefinito | Significato |
|---|---|---|---|
| `--bands NAMES` | stringa (elenco con virgole) | *(nessuno — obbligatorio)* | Nomi di banda separati da virgole. |
| `--freqs MHZ` | stringa (elenco con virgole) | *(nessuno)* | Frequenze centrali in MHz, una per banda. Facoltativo per le bande riconosciute, obbligatorio per i nomi personalizzati. |
| `--wire-len M` | float | *(nessuno — obbligatorio)* | Lunghezza iniziale del filo in metri (centro della finestra di ricerca). |
| `--cp-len M` | float | *(nessuno — obbligatorio salvo `--no-counterpoise`)* | Lunghezza iniziale del contrappeso in metri. |
| `--active-bands BANDS` | stringa (elenco con virgole) | tutte le bande | Quali bande pesano sul punteggio; omettere per usarle tutte. |
| `--mode {empirical,nec2,auto}` | scelta | `auto` | Motore di valutazione. |
| `--nec2c PATH` | percorso | *(ricerca automatica)* | Percorso esplicito del binario `nec2c`. |
| `--margin M` | float | `2.0` | Raggio di ricerca (metri) attorno alle lunghezze iniziali. |
| `--wire-min M` | float | iniziale − margine | Lunghezza minima del filo da esplorare. |
| `--wire-max M` | float | iniziale + margine | Lunghezza massima del filo da esplorare. |
| `--wire-step M` | float | `0.25` | Incremento della lunghezza del filo. |
| `--cp-min M` | float | iniziale − margine | Lunghezza minima del contrappeso. |
| `--cp-max M` | float | iniziale + margine | Lunghezza massima del contrappeso. |
| `--cp-step M` | float | `0.25` | Incremento della lunghezza del contrappeso. |
| `--height M` / `--antenna-height M` | float | `8.0` | Altezza del punto di alimentazione da terra (condivisa da radiatore e contrappeso). |
| `--wire-slope-end-height M` | float | *(non impostato = orizzontale)* | Altezza dell'estremità lontana del radiatore. `0.0` = tocca terra. Forza la modalità NEC2. |
| `--cp-end-height M` | float | *(non impostato = quota dell'antenna)* | Altezza dell'estremità lontana del contrappeso. |
| `--no-counterpoise` | flag | disattivo | Modella l'antenna senza contrappeso. |
| `--no-cp-return {ground-rod,coax-stub,reject}` | scelta | `ground-rod` | Modello del percorso di ritorno RF in assenza di contrappeso. |
| `--cp-stub-len M` | float | `2.0` | Lunghezza dello spezzone di calza coassiale, usata solo con `--no-cp-return coax-stub`. |
| `--ground-model {sommerfeld,perfect}` | scelta | `sommerfeld` | Modello elettromagnetico del terreno. |
| `--ground-cond S/M` | float | `0.005` | Conducibilità del terreno, S/m. |
| `--ground-diel EPS` | float | `13.0` | Permittività relativa del terreno. |
| `--feed-model {straddle,junction}` | scelta | `straddle` | Dove sta la carta sorgente di NEC-2 rispetto alla giunzione radiatore/contrappeso. Vedere [8.5](#85-sezione-feed-model-modello-di-alimentazione). Forzato a `junction` per `carolina-windom`. |
| `--antenna-type {long-wire,ocfd,carolina-windom}` | scelta | `long-wire` | Topologia dell'antenna. I tipi dipolo trasformano `--wire-len` / `--cp-len` nei **bracci lungo e corto** di un dipolo. Vedere [6.1](#61-sezione-antenna-type). |
| `--total-len M` | float | *(non impostato)* | Solo tipi dipolo: lunghezza totale di **entrambi** i bracci. Con `--offset` ricava `--wire-len` e `--cp-len` — il modo abituale di specificare un OCFD. |
| `--offset F` | float | `0.3333` | Solo tipi dipolo: braccio corto ÷ lunghezza totale. Intervallo valido `0.10`–`0.49`. |
| `--offset-min F` | float | `0.20` | Solo tipi dipolo: estremo inferiore della scansione dell'offset. |
| `--offset-max F` | float | `0.45` | Solo tipi dipolo: estremo superiore della scansione dell'offset. |
| `--offset-step F` | float | `0.01` | Solo tipi dipolo: passo della scansione dell'offset. |
| `--balun-ratio N` | `auto` o scelta | `auto` | Solo tipi dipolo: `auto`, oppure uno fra `2` / `4` / `6` / `9`. Un rapporto di balun è una scelta hardware, quindi la ricerca è limitata ai valori realizzabili. Rifiutato per `long-wire`, il cui rapporto di UnUn viene cercato automaticamente. |
| `--balun-kind {guanella,ruthroff}` | scelta | `guanella` | Topologia del balun a linea di trasmissione. Guanella è un balun di corrente, corretto per l'alimentazione bilanciata su tutta l'HF. |
| `--cw-vert-len M` | float | `3.0` | Solo Carolina Windom: lunghezza del radiatore verticale fra il balun e l'isolatore di linea (minimo `0.5` m). |
| `--cw-isolator-z R,X` | due float | *(non impostato = aperto ideale)* | Solo Carolina Windom: modella l'isolatore di linea come impedenza serie finita, es. `1000,2000`. |
| `--balun-core CORE` | scelta | `FT-240-31` | Nucleo toroidale usato per il balun **e** per l'isolatore di linea, dal database della [sezione 19](#19-appendice--database-dei-nuclei-toroidali). |
| `--balun-turns N` | intero | `10` | Spire per linea di trasmissione sul balun. |
| `--feed-choke` | flag | off | Progetta anche un choke di modo comune per la linea di alimentazione. Sempre progettato per `carolina-windom`, dove *è* l'isolatore di linea. |
| `--match-model {ideal,real}` | scelta | `ideal` | VSWR attraverso il dispositivo di adattamento: `ideal` divide R e X per il rapporto; `real` applica anche la reattanza magnetizzante finita del progetto del balun. |
| `--wire-diameter MM` | float | `2.0` mm | Diametro del conduttore in millimetri. |
| `--wire-material {...}` | scelta | `copper` | Uno tra: `copper`, `aluminium`, `aluminum`, `brass`, `silver`, `steel`, `perfect`. |
| `--wire-conductivity S/M` | float | *(dal materiale)* | Sovrascrittura manuale della conducibilità del conduttore. |
| `--segs-per-half-wave N` | intero | *(45 sweep / 180 fine)* | Sovrascrive sia la densità dello sweep sia quella dell'esecuzione finale. Limitato a `5`–`400`. |
| `--fast` | flag | disattivo | Sweep a densità grossolana (21 seg/mezza onda); il vincitore viene comunque ricalcolato fine. Imposta solo la segmentazione — non è `--fast-run`. |
| `--fast-run` | flag | disattivo | L'intera politica di accelerazione: soluzioni `nec2c` concorrenti, sweep grossolano, coda TOP-N raffinata più corta (≤ 5), rosa di ri-classificazione più corta (≤ 3) e solo il braccio a 0.5× di `--converge`. Le impedenze pubblicate restano alla densità fine. Vedere [10.1](#101-sezione-opzioni). |
| `--jobs N` / `-j N` | intero | `1` (seriale); uno per core con tetto 16 sotto `--fast-run` | Thread di lavoro per deck `nec2c` indipendenti (scansione, rifinitura fine, riclassificazione per diagramma di radiazione). Onorato in **entrambe** le modalità, normale e `--fast-run` — il parallelismo da solo non cambia alcun numero pubblicato. |
| `--converge` | flag | disattivo | Riesegue il vincitore a 0.5× e 2× la segmentazione di lavoro (solo 0.5× con `--fast-run`) e riporta quanto si muovono ancora R/X. Solo in modalità NEC2. |
| `--target-toa DEG` | float | `25.0` | Angolo di elevazione (gradi) a cui viene valutato il bonus di guadagno. |
| `--gain-weight W` | float | `0.20` | Peso nel punteggio per dB di guadagno all'angolo obiettivo. |
| `--rerank-top N` | intero | `6` | Quanti candidati migliori vengono risimulati con diagramma completo per la ri-classificazione. |
| `--top-n N` | intero | `20` | Quanti candidati compaiono nel report. |
| `--out-txt FILE` | percorso | `optimizer_report.txt` | Nome del file del report di testo. |
| `--out-png FILE` | percorso | `optimizer_plot.png` | Nome del file del grafico. |
| `--out-csv FILE` | percorso | `optimizer_best.csv` | Nome del file CSV del miglior candidato. |
| `--out-nec FILE` | percorso | `best_antenna.nec` | Nome del file NEC2 esportato. |
| `--out-radiation FILE` | percorso | `radiation_diagrams.png` | Nome del PNG dei diagrammi di radiazione. |
| `--out-construction FILE` | percorso | `antenna_construction.png` | Nome del PNG del disegno costruttivo. |
| `--out-pdf FILE` | percorso | `antenna_brochure.pdf` | Nome del file dell'opuscolo PDF. |
| `--retry N` | intero | `0` | Riesegue automaticamente lo sweep fino a N volte in più — spostando la finestra verso l'esterno se il vincitore cade su un bordo, oppure affinandola se si passa `--test-window`. |
| `--test-window` | flag | disattivo | Trasforma ogni tentativo in un *raffinamento* (rettangolo dei migliori candidati, entrambi i passi di griglia dimezzati, limite `0.01` m) invece di uno spostamento. Non fa nulla senza `--retry N` > 0. Vedere [7.10](#710-casella-test-all--test-window-e-refine-top-n). |
| `--refine-top N` | intero | `5` | Quanti candidati migliori definiscono la finestra raffinata. Deve essere ≥ 1; usato solo con `--test-window`. |
| `--no-interactive` | flag | disattivo | Fallisce sui dati mancanti invece di chiederli interattivamente. |
| `--quiet` / `-q` | flag | disattivo | Sopprime l'output di console dettagliato. |
| `--lang {en,es,it}` | scelta | rilevata dalle impostazioni locali | Lingua dell'interfaccia e del report. |
| `--gui` | flag | disattivo | Avvia l'interfaccia grafica invece dell'esecuzione da riga di comando. |

### 14.1 Esempi

**Esecuzione più semplice possibile** (bande note, resto ai valori predefiniti):
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
```

**Bande personalizzate/non riconosciute** (frequenze obbligatorie):
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \
    --wire-len 21.0 --cp-len 5.0
```

**Valutare tre bande ma darne il punteggio solo a due:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \
    --active-bands 40m,20m --wire-len 21.0 --cp-len 5.0
```

**Antenna senza contrappeso, con spezzone coassiale come ritorno:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m --wire-len 21.0 \
    --no-counterpoise --no-cp-return coax-stub --cp-stub-len 3.0
```

**Uno sweep NEC2 ampio su una macchina multicore, accelerato:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0 \
    --mode nec2 --fast-run --jobs 8
```

**Un dipolo alimentato fuori centro (Windom), specificato come d'abitudine — lunghezza totale più offset:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,10m --antenna-type ocfd \
    --total-len 41.0 --offset 0.3333 --balun-ratio 4
```

**Un Carolina Windom con un isolatore di linea volutamente imperfetto, per vedere quanto costa:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,10m --antenna-type carolina-windom \
    --total-len 41.0 --cw-vert-len 3.0 --cw-isolator-z 1000,2000 --converge
```

**Affinare su una regione promettente invece di allargare la ricerca:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m --wire-len 20.5 --cp-len 5.0 \
    --wire-min 19.5 --wire-max 21.5 --cp-min 4.0 --cp-max 6.0 \
    --retry 3 --test-window --refine-top 5
```

**Forzare la simulazione NEC2 completa con percorso esplicito del binario e controllo di convergenza:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0 \
    --mode nec2 --nec2c /usr/local/bin/nec2c --converge
```

---

## 15. Flussi di lavoro tipici, passo per passo

### 15.1 Primo progetto con la GUI

1. Avviare: `python src/Long_Wire_Antenna.py --gui`.
2. In **Banda / Sorgente**: digitare le bande (es. `40m,20m,15m`), lasciare vuote le frequenze (sono bande riconosciute), impostare lunghezza del filo e del contrappeso con la propria stima migliore.
3. In **Fisica**: lasciare la modalità su `auto`. Se `nec2c` è installato, premere **Auto-detect** per confermarlo.
4. In **Intervallo di ricerca**: lasciare il margine al valore predefinito `2.0` m per la prima passata.
5. In **File di output**: confermare o cambiare la cartella di lavoro.
6. In **Esecuzione**: rivedere l'anteprima del comando, premere **Run** e seguire la console.
7. A fine esecuzione premere **Show report** per i risultati ordinati e **Show radiation pattern** per i diagrammi.

### 15.2 Vincitore sul bordo della finestra

Se il report avvisa che la lunghezza del filo (o del contrappeso) "potrebbe dover essere maggiore/minore" perché il vincitore è finito sul bordo della finestra:

- Allargare a mano `wire-min`/`wire-max` (o `cp-min`/`cp-max`) nella scheda **Intervallo di ricerca** e rieseguire, **oppure**
- Impostare **Maximum retries** (sezione 7.8) a un numero piccolo (es. `2`) prima della prima esecuzione e lasciare che il programma sposti la finestra da solo.

Se invece il problema non è la posizione della finestra ma la sua risoluzione, togliere la spunta a **Test All** (sezione 7.10) e lasciare che i tentativi affinino la griglia.

### 15.3 Un progetto affidabile, pronto da costruire

1. Eseguire una prima volta in modalità `auto`/`empirical` con segmentazione `fast` per una panoramica rapida del panorama.
2. Individuata una regione promettente, passare la modalità a `nec2` e la segmentazione a `fine` (il valore predefinito) e rieseguire con una finestra di ricerca *più stretta* centrata su quella regione — così si ottengono risultati ad alta densità senza pagare il costo di uno sweep NEC2 fine sull'intero intervallo iniziale.
3. Attivare **Re-check convergence** e verificare che il report mostri una deriva di R ben sotto la soglia di allarme del ~3 % tra le densità di segmentazione.
4. Usare il file `best_antenna.nec` esportato e il PNG del disegno costruttivo come riferimenti effettivi di costruzione.

### 15.4 Progettare la rete di adattamento

1. Dopo un'esecuzione riuscita, passare alla scheda **UnUn / Transmatch**: sarà già precaricata con le impedenze per banda dell'antenna vincente.
2. Nella sotto-scheda **UnUn Toroid**, scegliere una banda dal menu per esaminare un adattamento su banda singola, oppure usare la sezione **Multi-band** (con **Auto** spuntata) perché il programma cerchi il miglior progetto di UnUn su tutte le bande insieme.
3. In alternativa (o in aggiunta), usare la sotto-scheda **Transmatch** per progettare una bobina con prese al posto dell'UnUn o insieme a esso.

---

## 16. Risoluzione dei problemi

| Sintomo | Causa probabile | Cosa fare |
|---|---|---|
| La GUI non parte; messaggio su `tkinter` | Tkinter non installato | `sudo apt install python3-tk` (o l'equivalente della propria distribuzione), poi riprovare. |
| Errore su un valore `--freqs` mancante | È stato usato un nome di banda personalizzato senza frequenza corrispondente | Compilare il campo Frequencies con un valore in MHz per banda, nello stesso ordine di Band(s). |
| I risultati sembrano sospettosamente buoni / il segno della reattanza sembra sbagliato | Si sta usando la segmentazione `fast` (21 seg/mezza onda) | Passare a `fine` (predefinito) prima di fidarsi di qualsiasi numero per una costruzione reale; `fast` serve solo per i diagrammi. |
| "NEC2 mode requested but no binary found" (o simile) | `nec2c` non è installato, o non è individuabile automaticamente | Installare `nec2c`, oppure digitare il percorso completo nel campo **NEC2 binary** della scheda Fisica e/o premere **Auto-detect**. |
| Su Windows `nec2c` non viene trovato benché l'installer sia andato a buon fine, e lo script è stato lanciato a mano invece che dal collegamento sul Desktop | Il fallback cablato `Program Files\OpenNEC` cerca un file chiamato `onec.exe`, mentre l'installer vi copia il motore come `nec2c.exe` — discrepanza nota, vedere [3.4](#34-individuazione-del-binario-nec2c) | Usare il collegamento sul Desktop (`run_gui.bat`), che imposta direttamente `$NEC2C`; oppure passare `--nec2c "C:\Program Files\OpenNEC\nec2c.exe"`; oppure impostare `$NEC2C` a mano. |
| I campi del contrappeso sono disattivati | "Use counterpoise" non è spuntata | Rimettere la spunta a "Use counterpoise" nella scheda Intervallo di ricerca, se un contrappeso serve. |
| La sezione "No-counterpoise return path" è disattivata | "Use counterpoise" è spuntata | Quella sezione vale solo in assenza di contrappeso; si attiva togliendo la spunta a "Use counterpoise". |
| La lunghezza vincente di filo/contrappeso coincide con il minimo o il massimo della finestra | L'ottimo vero può stare fuori dall'intervallo esplorato | Allargare `wire-min`/`wire-max` (o `cp-min`/`cp-max`), oppure impostare **Maximum retries** > 0 e rieseguire. |
| `--jobs` sembra ignorato e l'esecuzione resta seriale | O si sta usando una versione precedente a quella descritta in questo manuale (dove `--jobs` era forzato a 1 senza `--fast-run`), oppure il campo **Jobs** della GUI è vuoto — vuoto significa seriale in modalità normale | Inserire un numero di worker in **Jobs** nella scheda Esecuzione, oppure passare `--jobs N` esplicitamente. Nelle versioni attuali il flag funziona con o senza `--fast-run`. |
| `--offset`, `--total-len` o `--balun-ratio` viene rifiutato con un errore | Quelle opzioni si applicano solo ai tipi alimentati fuori centro | Aggiungere `--antenna-type ocfd` (o `carolina-windom`). Il programma rifiuta la combinazione di proposito, invece di ignorare il flag e riportare un'antenna diversa. |
| Il report dice che il modello di alimentazione è stato forzato a `junction` | È stato scelto `carolina-windom`, che ha tre conduttori al nodo di alimentazione, quindi l'alimentazione *straddle* è geometricamente impossibile | È il comportamento atteso, non un errore. Aggiungere `--converge` per quell'esecuzione e verificare quanto si muovono ancora R e X prima di dimensionare qualsiasi cosa. |
| `--test-window` sembra non fare nulla | Il raffinamento avviene *su un tentativo*, e il budget dei tentativi vale zero per impostazione predefinita | Portare **Maximum retries** (`--retry N`) ad almeno 1. Il raffinamento si ferma comunque quando entrambi i passi di griglia raggiungono il limite di `0.01` m. |
| La scheda UnUn/Transmatch mostra "nessun dato caricato" | Nessuna esecuzione ha ancora prodotto un CSV, oppure si trova in un'altra cartella | Eseguire prima l'ottimizzatore, oppure premere **Reload** dopo aver puntato la cartella di lavoro su quella che contiene `optimizer_best.csv`. |
| Una banda del Transmatch mostra un ROS sospetto che non segue la reattanza reale dell'antenna | L'avvolgimento potrebbe lavorare sopra la propria frequenza di autorisonanza (SRF) | Controllare l'avviso di SRF nella tabella Winding; con **auto** spuntata lo strumento accorcia già l'avvolgimento di riferimento per tenere la SRF sopra la banda più alta, ma un riferimento inserito a mano può restare troppo lungo. |
| Nessun PNG viene prodotto | `matplotlib` (o, per i soli diagrammi di radiazione, `numpy`) non è installato | `pip install matplotlib numpy`, poi rieseguire. |
| Il PDF è generato ma una sezione dice "(non disponibile)" | `Pillow` (`PIL`) non è installato | `pip install pillow`, poi rieseguire — non serve rifare la ricerca, perché riguarda solo l'inserimento delle immagini nel PDF. |
| L'anteprima del comando mostra qualcosa di inatteso | Un campo è rimasto con testo obsoleto, o lo stato di una casella non è quello voluto | Quello che si vede nell'anteprima è esattamente ciò che verrà eseguito: ispezionarlo prima di avviare e correggere il campo corrispondente. |

---

## 17. Glossario

- **ROS (rapporto d'onda stazionaria, VSWR):** misura del disadattamento del carico rispetto all'impedenza caratteristica della linea. Il valore minimo possibile è **1.0** (adattamento perfetto); valori superiori indicano disadattamento crescente. Non può essere inferiore a 1.0.
- **Impedenza al punto di alimentazione (R + jX):** resistenza (R) e reattanza (X), in ohm, che l'antenna presenta alla linea nel punto in cui è alimentata.
- **Contrappeso:** un filo (o un insieme di fili) che fa da "altra metà" del circuito d'antenna in una configurazione end-fed/sbilanciata, al posto di un piano di terra completo o di un sistema di radiali.
- **NEC2 / `nec2c`:** il Numerical Electromagnetics Code versione 2, uno standard diffuso di simulazione d'antenna a metodo dei momenti; `nec2c` è una comune implementazione open source in C.
- **Segmentazione (seg/mezza onda):** quanto finemente un modello NEC2 suddivide ogni filo per il calcolo; più segmenti significano in genere più accuratezza (fino a un certo punto) a costo di tempo di calcolo.
- **Modello di terreno Sommerfeld-Norton:** modello di terreno fisicamente realistico di NEC2 che tiene conto di conducibilità e permittività finite, invece di assumere un conduttore perfetto.
- **Insieme Pareto-ottimale:** il sottoinsieme di candidati per i quali nessun altro candidato è almeno altrettanto buono su ogni metrica considerata (qui, ogni banda attiva) — l'insieme reale dei compromessi disponibili.
- **UnUn:** trasformatore "unbalanced-to-unbalanced", tipicamente avvolto su un toroide di ferrite o polvere di ferro, usato per trasformare l'impedenza d'antenna verso l'impedenza caratteristica del cavo coassiale.
- **Transmatch:** rete di adattamento regolabile (spesso una bobina con prese e condensatori), inserita tra linea e antenna (o apparato) per presentare al trasmettitore un buon adattamento.
- **Nucleo toroidale:** nucleo magnetico ad anello (ferrite o polvere di ferro) usato per avvolgere trasformatori e choke RF; mix e dimensioni diverse comportano compromessi tra banda di frequenza, perdite e potenza gestibile.
- **Angolo di elevazione (TOA):** in questo programma, l'angolo sopra l'orizzonte al quale **viene valutato il guadagno**. Non è necessariamente l'angolo di massima radiazione dell'antenna. Per la ri-classificazione, il programma prende il guadagno massimo in azimut a quella elevazione fissa. Angoli bassi possono essere utili per certi collegamenti a lunga distanza, ma il TOA appropriato dipende dalla propagazione e dall'obiettivo del collegamento.

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

*Fine del manuale.*
