<p align="center">
  <img src="https://github.com/hiperiondev/Long_Wire_Antenna/raw/main/images/logo.png" width="150">
</p>

<div align="center">

# Ottimizzatore di Lunghezza Antenna NEC2

**Trova la lunghezza del filo (e del contrappeso) che offre il ROS più basso su tutte le bande radioamatoriali che ti interessano — basato su simulazioni reali con il metodo dei momenti NEC-2, non su supposizioni.**

Autore: **LU3VEA** · Licenza: **CC0 1.0** (dominio pubblico, applicabile solo allo script e alla documentazione — vedi [Nota sulle licenze di terze parti](#nota-sulle-licenze-di-terze-parti)) · Piattaforma: installer per Windows, AppImage per Linux, o script Python multipiattaforma

</div>

---

## Cosa fa

Se stai costruendo un'antenna filare multibanda alimentata all'estremità o inclinata, la domanda eterna è: *quanto deve essere lungo il filo?* Questo strumento risponde a questa domanda in modo empirico anziché a intuito.

Esegue una scansione su una griglia di combinazioni candidate di **lunghezza del radiatore** e **lunghezza del contrappeso** *(il contrappeso è il filo secondario, o il riferimento di terra, che fornisce il percorso di ritorno RF in un'antenna alimentata all'estremità — vedi [Glossario](#glossario))*, e per ogni combinazione:

1. Genera un file di input NEC-2 `.nec` (radiatore inclinato + contrappeso inclinato, con modellazione del terreno e del materiale del filo).
2. Esegue [`nec2c`](https://www.nec2.org/) per simulare l'antenna alla frequenza centrale di ciascuna delle bande target.
3. Analizza i risultati di impedenza e calcola un **punteggio di ROS aggregato** su tutte le bande attive, con penalità per le bande che si discostano dall'angolo di radiazione o dal guadagno desiderati.
4. Tiene traccia dei candidati **Pareto-ottimali** (i migliori compromessi tra le bande, anziché una singola banda che vince a scapito delle altre).

Alla fine ottieni un report classificato, un grafico a dispersione dell'intero spazio di ricerca, un CSV con i migliori candidati, un file `.nec` pronto per la simulazione del vincitore, diagrammi del pattern di radiazione, uno schema costruttivo e, facoltativamente, un PDF di una pagina tipo "opuscolo dell'antenna" che riassume la costruzione.

Può inoltre consigliare il miglior **rapporto di trasformazione UnUn** standard (es. 9:1, 4:1, 1:1 — un UnUn è un trasformatore di adattamento d'impedenza "sbilanciato-sbilanciato"; vedi [Glossario](#glossario)) per la tua linea di alimentazione, e avvisarti quando nessun rapporto elimina il disadattamento di impedenza in modo pulito su una determinata banda.

---

## Caratteristiche principali

- 🎯 **Ottimizzazione multibanda** — ottimizza per qualsiasi combinazione di bande contemporaneamente (es. `40m,20m,17m,15m,10m`), non solo una.
- 📡 **Fisica NEC-2 reale** — utilizza la simulazione a metodo dei momenti (`nec2c`) anziché formule approssimate in forma chiusa, compresi modelli di terreno realistici (Sommerfeld/Norton o terreno perfetto).
- ⚡ **Modalità empirica veloce** — una modalità di riserva `--mode empirical` con formule in forma chiusa quando non hai `nec2c` installato o vuoi solo una stima rapida; `--mode auto` sceglie automaticamente l'opzione migliore disponibile.
- 🌍 **CLI multilingue** — interfaccia completa in inglese, spagnolo e italiano, rilevata automaticamente dalle impostazioni internazionali del sistema (oppure forzabile con `--lang`).
- 🖥️ **Modalità GUI** — un'interfaccia grafica Tkinter (`--gui`) per chi preferisce non usare il terminale.
- 🔧 **Modellazione fisicamente realistica** — diametro e materiale del filo configurabili (rame, alluminio, ottone, argento, acciaio, oppure "perfetto" senza perdite), geometria del filo inclinata o orizzontale, altezza e parametri del terreno realistici.
- 🔌 **Consulente per il rapporto UnUn** — valuta i rapporti di trasformazione standard rispetto all'impedenza grezza dell'antenna e indica quale ti avvicina di più a un adattamento pulito su ogni banda.
- 📊 **Output ricco** — report testuale classificato, grafico a dispersione (PNG), CSV dei migliori candidati, file `.nec` del miglior candidato, diagrammi del pattern di radiazione, schema costruttivo e opuscolo in PDF.
- 🪟 **Installer per Windows con un clic** — include Python, `nec2c` e tutte le dipendenze, così anche i radioamatori meno esperti possono iniziare senza toccare un gestore di pacchetti.
- 🐧 **AppImage per Linux con un clic** — la stessa idea per Linux, senza bisogno di `pip install` né di un gestore di pacchetti.

Attualmente **non esiste un installer confezionato per macOS**. Gli utenti macOS devono usare l'[Opzione C](#opzione-c--eseguire-direttamente-lo-script-python-windowsmacoslinux) più sotto.

---

## Contenuto del repository

| File / cartella                                               | Descrizione                                                                                                                                                       |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/Long_Wire_Antenna.py`                                     | L'ottimizzatore vero e proprio — uno script Python autonomo (CLI + GUI opzionale). È il file che esegui direttamente per l'[Opzione C](#opzione-c--eseguire-direttamente-lo-script-python-windowsmacoslinux). |
| `Setup_Long_Wire_Antenna.exe`                                  | Installer Windows precompilato e autonomo (include `Long_Wire_Antenna.py`, `nec2c.exe`, il launcher e lo script di post-installazione — non serve nessun altro file accanto). |
| `Long_Wire_Antenna-x86_64.AppImage`                             | AppImage Linux precompilato — l'equivalente in un clic dell'installer Windows, per Linux x86\_64.                                                                 |
| `documentation/Long_Wire_Antenna_Manual_EN.md`                  | Manuale utente esteso in inglese.                                                                                                                                 |
| `documentation/Long_Wire_Antenna_Manual_ES.md`                  | Manuale utente esteso in spagnolo.                                                                                                                                |
| `documentation/Long_Wire_Antenna_Manual_IT.md`                  | Manuale utente esteso in italiano.                                                                                                                                |
| `images/logo.png`, `images/icon.png`                            | Logo del progetto (quello in alto in questo README) e icona dell'applicazione (usata dall'installer/collegamenti Windows e dall'AppImage Linux).                  |
| `others/build_windows_installer.sh`                             | Script di build che compila `Setup_Long_Wire_Antenna.exe` a partire dai sorgenti in `others/windows_installer/` usando NSIS (`makensis`). Va eseguito su Fedora/RHEL o Debian/Ubuntu; installa automaticamente `nsis` e `imagemagick` se mancanti. |
| `others/windows_installer/long_wire_antenna_installer.nsi`      | Script [NSIS](https://nsis.sourceforge.io/) che definisce l'installer Windows, compilato da `build_windows_installer.sh`.                                        |
| `others/windows_installer/nec2c.exe`                            | Binario Windows precompilato del [motore a metodo dei momenti NEC-2](https://www.nec2.org/), incorporato in `Setup_Long_Wire_Antenna.exe`. Binario di terze parti — vedi [nota sulle licenze](#nota-sulle-licenze-di-terze-parti). Non pensato per un uso a sé stante — vedi l'[Opzione C](#opzione-c--eseguire-direttamente-lo-script-python-windowsmacoslinux) se ti serve un binario `nec2c` per un'installazione manuale/non-Windows. |
| `others/windows_installer/payload/run_gui.bat`                  | File `.bat` di avvio installato insieme allo script; è quello che il collegamento sul Desktop esegue davvero. Imposta la codifica UTF-8 di console/Python, punta la variabile d'ambiente `NEC2C` al motore incluso, e poi esegue `Long_Wire_Antenna.py --gui`. |
| `others/windows_installer/payload/post_install_setup.py`        | Viene eseguito una sola volta, automaticamente, al termine dell'installazione (con l'interprete Python appena installato) per installare con `pip` i pacchetti necessari e completare la configurazione del motore NEC2. Vedi la nota sull'[installer Windows](#opzione-a--windows-la-più-semplice) più sotto. |
| `others/build_appimage.sh`                                      | Script di build che produce l'AppImage Linux portatile e autonomo (Python + Tk inclusi, con `nec2c` compilato staticamente, senza dipendenze dal sistema host).  |
| `LICENSE`                                                        | CC0 1.0 Universal (dedica al dominio pubblico) — si applica al codice e alla documentazione propri del progetto, non ai binari di terze parti inclusi.            |

> **Nota sui file binari in questo repository:** l'installer Windows (`Setup_Long_Wire_Antenna.exe`), il `nec2c.exe` incluso al suo interno, e l'AppImage Linux (`Long_Wire_Antenna-x86_64.AppImage`) sono inclusi direttamente in questo repository git anziché pubblicati come GitHub Release separate. Questo è comodo per il download diretto, ma significa che la cronologia del repository contiene blob binari. Attualmente non sono pubblicati checksum SHA-256 di questi file in questo README; se devi verificarne l'integrità, calcola tu stesso l'hash dopo il download (`sha256sum <file>` su Linux/macOS, `certutil -hashfile <file> SHA256` su Windows) e confrontalo con un checksum ottenuto da un canale affidabile, dato che qui non ne viene ancora pubblicato nessuno.

---

## Installazione

### Opzione A — Windows (la più semplice)

Scarica ed esegui **`Setup_Long_Wire_Antenna.exe`**. È completamente autonomo — non serve nessun altro file accanto. L'installer:

1. Verifica la presenza di un interprete Python 3 e, se assente, installa silenziosamente Python 3.12.7 (64-bit) da python.org (con pip, il launcher `py` e PATH configurati).
2. Installa `Long_Wire_Antenna.py`, il launcher `run_gui.bat`, `post_install_setup.py`, l'icona dell'app e il testo della licenza nella cartella di installazione scelta (`C:\Program Files\LongWireAntenna` per impostazione predefinita).
3. Installa il `nec2c.exe` incluso in `%INSTDIR%\nec2c\`, e ne copia anche una copia in `C:\Program Files\OpenNEC\` e in `C:\Program Files (x86)\OpenNEC\`.
4. Esegue `post_install_setup.py`, che installa con `pip` i pacchetti Python (`numpy`, `matplotlib`, `tabulate`, `colorama`, `reportlab`) e poi ricontrolla il motore NEC2 — vedi la nota sotto.
5. Crea un collegamento sul Desktop che esegue `run_gui.bat`, il quale a sua volta avvia `Long_Wire_Antenna.py --gui`.
6. Registra un disinstallatore Windows standard.

> ⚠️ **Nota su una dipendenza extra:** il passo 4 installa con `pip` anche un quinto pacchetto, **`tabulate`**, oltre ai quattro che lo script usa davvero. `Long_Wire_Antenna.py` **non** importa né usa `tabulate` da nessuna parte — è un residuo inutilizzato nell'elenco delle dipendenze dell'installer, non un requisito reale. Costa solo qualche secondo extra di installazione e un po' di spazio su disco, e non serve se configuri lo script a mano ([Opzione C](#opzione-c--eseguire-direttamente-lo-script-python-windowsmacoslinux)).

> ⚠️ **Particolarità nota dell'installer (passo di auto-aggiornamento del motore):** come parte del passo 4, `post_install_setup.py` prova opzionalmente a scaricare una build più recente del motore NEC2 da un progetto GitHub esterno e, se la trova, verifica che si avvii correttamente prima di usarla — tornando al "motore incluso" se il download fallisce o la build scaricata non si avvia. Tuttavia, la sua logica di ripiego cerca un file incluso chiamato `onec.exe` / `onec_bundled.exe`, mentre l'installer include soltanto un file chiamato `nec2c.exe`. In pratica questo significa solo che il passo opzionale di aggiornamento online non trova quel file di base a cui tornare, quindi non fa nulla a meno che il download di rete vada a buon fine. Questo **non** compromette un'installazione normale: `run_gui.bat` cerca autonomamente (e trova) `nec2c\nec2c.exe` e punta la variabile d'ambiente `NEC2C` direttamente ad esso, quindi il motore incluso viene comunque usato correttamente. Utile saperlo se stai analizzando log di installazione che menzionano `onec.exe`.

### Opzione B — Linux (AppImage, la più semplice per la maggior parte delle distro)

Scarica **`Long_Wire_Antenna-x86_64.AppImage`**, rendilo eseguibile ed eseguilo:

```
chmod +x Long_Wire_Antenna-x86_64.AppImage
./Long_Wire_Antenna-x86_64.AppImage
```

L'AppImage include il proprio interprete Python 3.11 (con Tkinter), `numpy`, `matplotlib`, `colorama`, `reportlab`, `pillow` e un binario `nec2c` compilato staticamente — non serve installare nient'altro sul sistema host, né eseguire alcun `pip install`.

> ⚠️ **L'AppImage avvia sempre direttamente la GUI**, indipendentemente dagli argomenti a riga di comando che gli passi — la modalità GUI viene forzata incondizionatamente. Questo corrisponde a come si comporta `--gui` quando passato direttamente allo script Python (vedi l'[avviso su `--gui` in Utilizzo](#avviare-la-gui) più sotto): la GUI si apre con i propri valori predefiniti, e attualmente **non c'è modo di precompilarla da riga di comando**. Per usare la CLI, usa invece l'[Opzione C](#opzione-c--eseguire-direttamente-lo-script-python-windowsmacoslinux).

Puoi ricompilarlo tu stesso dal sorgente con `others/build_appimage.sh` (è consigliabile eseguirlo su una base datata come Ubuntu 20.04, o l'immagine Docker ufficiale per la creazione di AppImage, per mantenere basso il requisito di glibc).

### Opzione C — Eseguire direttamente lo script Python (Windows/macOS/Linux)

Questa è anche l'**unica via supportata per macOS**, dato che non esiste un installer confezionato per quel sistema.

**Requisiti:**

- Python 3.8 o superiore
- [`nec2c`](https://www.nec2.org/) nel `PATH` (oppure indicane il percorso con `--nec2c`) — facoltativo se prevedi di usare solo `--mode empirical`
- Pacchetti Python:

```
pip install numpy matplotlib colorama reportlab
```

`colorama`, `matplotlib`, `numpy` e `reportlab` sono tutti facoltativi — lo script si adatta senza problemi (niente colori, niente grafico/PDF) se non sono installati. `numpy` serve solo per i diagrammi del pattern di radiazione e viene normalmente installato in automatico come dipendenza di `matplotlib`, quindi raramente occorre installarlo a parte.

**Ordine di ricerca del binario NEC2C:**

1. `--nec2c /percorso/a/nec2c` (flag esplicito)
2. Variabile d'ambiente `$NEC2C`
3. `PATH` (`nec2c`, `nec2c-mpich`, `onec`)
4. Percorsi di installazione comuni (`/usr/bin`, `/usr/local/bin`, `/opt/nec2c/bin`, ecc.)
5. Richiesta interattiva (a meno che non sia impostato `--no-interactive`)

Se `nec2c` non viene trovato tramite nessuno di questi metodi e `--no-interactive` è impostato (o rifiuti la richiesta), lo script ripiega su `--mode empirical` se era impostato `--mode auto`, oppure termina con un errore se avevi richiesto esplicitamente `--mode nec2`.

---

## Utilizzo

### Di base — bande note

```
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
```

Le frequenze centrali delle bande note vengono risolte automaticamente, quindi `--freqs` è facoltativo in questo caso.

### Bande personalizzate / sconosciute

```
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \
    --wire-len 21.0 --cp-len 5.0
```

### Limitare quali bande determinano effettivamente il punteggio

```
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \
    --active-bands 40m,20m --wire-len 21.0 --cp-len 5.0
```

### Avviare la GUI

```
python src/Long_Wire_Antenna.py --gui
```

> ⚠️ **`--gui` ha priorità assoluta su tutto il resto.** Viene controllato *prima* che venga analizzato il resto della riga di comando, quindi se lo combini con altri flag (es. `python src/Long_Wire_Antenna.py --gui --bands 40m,20m`), **quegli altri flag vengono ignorati silenziosamente** — non viene mostrato alcun avviso o errore, e la GUI si apre semplicemente con i propri valori predefiniti. Attualmente non esiste un modo per precompilare i campi della GUI dagli argomenti della CLI. Una volta aperta, usa i suoi stessi campi per impostare tutto.

### Guida completa

```
python src/Long_Wire_Antenna.py --help
```

Le bande predefinite supportate coprono da LF a UHF: `2200m, 630m, 160m, 80m, 60m, 40m, 30m, 20m, 17m, 15m, 12m, 10m, 6m, 4m, 2m, 70cm, 23cm`.

---

## Opzioni principali

| Flag                                                                                                     | Scopo                                                                                                                                                                                                    |
| ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--bands` / `--freqs`                                                                                    | Bande da modellare e relative frequenze (MHz) se non presenti nella tabella delle bande note.                                                                                                            |
| `--active-bands`                                                                                         | Sottoinsieme di `--bands` che contribuisce effettivamente al punteggio di ottimizzazione.                                                                                                                |
| `--wire-len`, `--cp-len`                                                                                 | Lunghezza iniziale/centrale del radiatore e del contrappeso (m).                                                                                                                                         |
| `--wire-min/max/step`, `--cp-min/max/step`                                                               | Definiscono la griglia di ricerca attorno alle lunghezze iniziali.                                                                                                                                       |
| `--mode {empirical,nec2,auto}`                                                                           | Usa formule in forma chiusa, simulazione NEC-2 completa, o selezione automatica.                                                                                                                         |
| `--height`                                                                                               | Altezza dell'antenna dal suolo (m).                                                                                                                                                                      |
| `--wire-slope-end-height`, `--cp-end-height`                                                             | Modellano un filo/contrappeso inclinato impostando l'altezza dell'estremità lontana (0 = estremità a livello del suolo).                                                                                 |
| `--no-counterpoise`                                                                                      | Modella un'antenna alimentata all'estremità senza contrappeso. In modalità NEC2 il percorso di ritorno RF usa `ground-rod` per impostazione predefinita; usa `--no-cp-return` per scegliere `coax-stub`, oppure per `reject` (rifiutare) la configurazione. |
| `--no-cp-return {ground-rod,coax-stub,reject}`                                                           | Come viene modellato il percorso di ritorno RF quando manca il contrappeso.                                                                                                                              |
| `--ground-model {sommerfeld,perfect}`                                                                    | Modello di terreno usato da NEC-2.                                                                                                                                                                       |
| `--ground-cond`, `--ground-diel`                                                                         | Conducibilità del terreno (S/m) e costante dielettrica.                                                                                                                                                  |
| `--wire-diameter`, `--wire-material`                                                                     | Diametro fisico del filo (mm) e materiale (`copper`, `aluminium`/`aluminum`, `brass`, `silver`, `steel`, `perfect`).                                                                                     |
| `--target-toa`                                                                                           | Angolo di radiazione (take-off) target (gradi) usato nel punteggio.                                                                                                                                      |
| `--gain-weight`                                                                                          | Peso del guadagno rispetto al ROS nel punteggio aggregato.                                                                                                                                               |
| `--top-n`                                                                                                | Numero di candidati classificati da riportare.                                                                                                                                                           |
| `--out-txt`, `--out-png`, `--out-csv`, `--out-nec`, `--out-radiation`, `--out-construction`, `--out-pdf` | Percorsi di output per ciascun file del report.                                                                                                                                                          |
| `--lang {en,es,it}`                                                                                      | Forza la lingua dell'interfaccia (altrimenti rilevata automaticamente dalle impostazioni internazionali).                                                                                                |
| `--gui`                                                                                                  | Avvia la GUI Tkinter invece della CLI. **Ignora silenziosamente tutti gli altri flag** — vedi l'[avviso sopra](#avviare-la-gui).                                                                         |
| `--quiet` / `-q`                                                                                         | Sopprime l'output non essenziale sulla console.                                                                                                                                                          |

Esegui `--help` per l'elenco completo e aggiornato — lo script offre molte altre opzioni di ottimizzazione fine (segmenti per mezza onda, modalità rapida/convergenza, numero di tentativi, ecc.).

---

## Output

Un'esecuzione tipica produce:

- **`optimizer_report.txt`** — report testuale classificato dei migliori candidati e del loro ROS per banda.
- **`optimizer_plot.png`** — grafico a dispersione dell'intero spazio di ricerca con il fronte di Pareto evidenziato.
- **`optimizer_best.csv`** — migliori candidati in formato CSV, pronti da importare altrove.
- **`best_antenna.nec`** — il file NEC-2 della geometria vincente, pronto per essere ri-simulato o modificato.
- **`radiation_diagrams.png`** — grafici del pattern di radiazione dell'antenna vincente.
- **`antenna_construction.png`** — uno schema costruttivo/di montaggio.
- **`antenna_brochure.pdf`** — un riepilogo in PDF di una pagina (richiede `reportlab`).

---

## Come funziona il punteggio

Per ogni candidato `(wire_len, cp_len)`, lo script calcola un ROS per banda a partire dall'impedenza del punto di alimentazione simulata (o stimata empiricamente), quindi aggrega questi valori in un unico punteggio penalizzato che tiene conto anche di:

- Scostamento dall'angolo di radiazione desiderato (ponderato tramite `--gain-weight`).
- Quanto la lunghezza del contrappeso si discosta da un rapporto "ideale" di un quarto d'onda per ciascuna banda.
- I candidati non dominati nel senso di Pareto vengono segnalati, così puoi vedere compromessi multibanda reali anziché un unico numero migliore in assoluto.

Lo strumento verifica poi separatamente i rapporti standard del trasformatore UnUn (1:1, 4:1, 9:1, ecc.) rispetto all'impedenza grezza dell'antenna vincente e indica quale rapporto avvicina di più il ROS a 1:1 su ciascuna banda — segnalando inoltre le bande in cui nessun rapporto standard risolve il disadattamento, poiché a volte è fisicamente impossibile che un'unica linea di alimentazione copra bene molte bande tra loro non correlate.

---

## Glossario

- **Contrappeso (counterpoise)** — un filo (o un insieme di fili) collegato al lato di ritorno RF/terra del punto di alimentazione di un'antenna alimentata all'estremità, usato al posto di (o in aggiunta a) una vera terra per fornire il percorso di ritorno della corrente RF.
- **ROS (Rapporto di Onde Stazionarie, VSWR in inglese)** — una misura di quanto bene l'impedenza dell'antenna sia adattata alla linea di alimentazione; 1:1 è un adattamento perfetto, valori più alti indicano più potenza riflessa.
- **UnUn (trasformatore sbilanciato-sbilanciato)** — un trasformatore RF che cambia l'impedenza (es. 9:1, 4:1) tra una linea di alimentazione sbilanciata (coassiale) e un'antenna sbilanciata come un filo alimentato all'estremità, usato per avvicinare l'impedenza grezza dell'antenna all'impedenza caratteristica della linea (tipicamente 50 Ω).
- **Angolo di radiazione (take-off angle, TOA)** — l'angolo verticale sopra l'orizzonte al quale un'antenna irradia il suo segnale di campo lontano massimo; angoli più bassi generalmente favoriscono la propagazione a lunga distanza (DX).
- **Candidato Pareto-ottimale** — una coppia candidata `(wire_len, cp_len)` per cui nessun altro candidato è simultaneamente almeno altrettanto buono su tutte le bande attive e strettamente migliore su almeno una; cioè un compromesso multibanda autentico anziché un'opzione dominata (strettamente peggiore).

---

## Risoluzione dei problemi

<!-- TODO(manutentore): Questa sezione è un segnaposto. Il README/i manuali originali non
     includevano una sezione di risoluzione dei problemi o FAQ, e non è stato possibile
     reperire i messaggi di errore reali dello script né il suo comportamento sui codici di
     uscita al momento della correzione di questo documento. Sostituire i punti seguenti con
     indicazioni verificate e fedeli allo script, ad esempio:
     - Cosa succede se nec2c non viene trovato ed è impostato --no-interactive?
     - Cosa significa in pratica l'avviso "nessun rapporto standard risolve il disadattamento",
       e cosa dovrebbe fare l'utente al riguardo?
     - Cause comuni di fallimenti di convergenza/tentativi di NEC-2 e come li gestisce --mode auto.
     - Cosa fare se mancano matplotlib/reportlab ma è stato richiesto un grafico o un PDF. -->

## Nota sulle licenze di terze parti

Il codice sorgente proprio di questo progetto (`src/Long_Wire_Antenna.py`), gli script di build e la documentazione sono rilasciati sotto **CC0 1.0 Universal** (dominio pubblico) — vedi [`LICENSE`](https://github.com/hiperiondev/Long_Wire_Antenna/blob/main/LICENSE).

Il `nec2c.exe` incluso (Windows) e il binario `nec2c` compilato staticamente all'interno dell'AppImage Linux sono **software di terze parti** — la traduzione in C di NEC-2 [`nec2c`](https://www.nec2.org/) realizzata da Neoklis Kyriazis (5B4AZ), a sua volta derivata dal codice originale NEC-2 sviluppato presso il Lawrence Livermore National Laboratory. Questi binari **non** sono coperti dalla dedica CC0 di questo progetto; mantengono i propri termini di licenza originali.

<!-- TODO(manutentore): Indicare la licenza esatta di provenienza (es. variante BSD specifica o
     stato di dominio pubblico) applicabile al binario nec2c incluso, e confermare che i termini
     di ridistribuzione siano rispettati distribuendo il binario compilato in questo repository. -->

Se ridistribuisci questo progetto (incluso l'installer, l'AppImage, o `nec2c.exe`), assicurati che la tua ridistribuzione rispetti anche i termini di licenza propri di `nec2c`, non solo la dedica CC0 di questo progetto.

---

## Licenza

Il codice e la documentazione propri di questo progetto sono rilasciati sotto **CC0 1.0 Universal** — dominio pubblico. Fanne ciò che vuoi, non è richiesta alcuna attribuzione. Vedi [`LICENSE`](https://github.com/hiperiondev/Long_Wire_Antenna/blob/main/LICENSE) per il testo legale completo. I binari di terze parti inclusi sono esclusi — vedi [Nota sulle licenze di terze parti](#nota-sulle-licenze-di-terze-parti) sopra.

## Ringraziamenti

- [NEC-2](https://www.nec2.org/) (Numerical Electromagnetics Code) — il motore di simulazione delle antenne sottostante.
- Sviluppato da **LU3VEA** per la comunità dei radioamatori.

---

*73! Se questo strumento ti ha aiutato a costruire un'antenna migliore, considera di condividere i tuoi risultati con la comunità.*
