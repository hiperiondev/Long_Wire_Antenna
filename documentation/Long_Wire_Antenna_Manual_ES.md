# NEC2 Antenna Length Optimizer — Manual de Usuario Completo

**Autor del software:** LU3VEA (publicado bajo CC0 v1.0)
**Versión del manual:** 1.3 (auditado contra el código)
**Alcance de este manual:** instalación, conceptos, la Interfaz Gráfica de Usuario (GUI) en detalle completo, la interfaz de línea de comandos (CLI), los archivos de salida generados, y solución de problemas.

---

## Tabla de contenidos

1. [Qué hace este software](#1-qué-hace-este-software)
2. [Cómo funciona, en términos simples](#2-cómo-funciona-en-términos-simples)
3. [Requisitos e instalación](#3-requisitos-e-instalación)
4. [Iniciar el programa](#4-iniciar-el-programa)
5. [La Interfaz Gráfica de Usuario (GUI) — resumen](#5-la-interfaz-gráfica-de-usuario-gui--resumen)
6. [Pestaña 1 — Banda / Fuente](#6-pestaña-1--banda--fuente)
7. [Pestaña 2 — Rango de búsqueda](#7-pestaña-2--rango-de-búsqueda)
8. [Pestaña 3 — Física](#8-pestaña-3--física)
9. [Pestaña 4 — Archivos de salida](#9-pestaña-4--archivos-de-salida)
10. [Pestaña 5 — Ejecutar](#10-pestaña-5--ejecutar)
11. [Pestaña 6 — UnUn / Transmatch](#11-pestaña-6--ununtransmatch)
12. [Barra de encabezado y controles globales](#12-barra-de-encabezado-y-controles-globales)
13. [Entendiendo los archivos de salida](#13-entendiendo-los-archivos-de-salida)
14. [La interfaz de línea de comandos (CLI) — referencia completa](#14-la-interfaz-de-línea-de-comandos-cli--referencia-completa)
15. [Flujos de trabajo típicos, paso a paso](#15-flujos-de-trabajo-típicos-paso-a-paso)
16. [Solución de problemas](#16-solución-de-problemas)
17. [Glosario](#17-glosario)
18. [Apéndice: bandas de radioaficionado conocidas](#18-apéndice-bandas-de-radioaficionado-conocidas)
19. [Apéndice: base de datos de núcleos toroidales (pestaña UnUn)](#19-apéndice-base-de-datos-de-núcleos-toroidales-pestaña-unun)

---

> **Nota de alcance:** este programa es una herramienta de modelado y optimización. No sustituye la verificación de la antena real instalada. Los resultados dependen de las hipótesis geométricas, el modelo de tierra, las pérdidas, la segmentación y los objetos próximos.

## 1. Qué hace este software

El **NEC2 Antenna Length Optimizer** es una herramienta de diseño para antenas de hilo (un radiador inclinado con un contrapeso inclinado opcional) alimentadas contra un único punto de alimentación — la clásica configuración "random wire" / alimentada por un extremo, usada por muchos radioaficionados.

Dado:

- una o más **bandas** de radio (de radioaficionado o personalizadas) en las que se desea operar, y
- una **longitud de hilo inicial** y una **longitud de contrapeso**,

el programa busca combinaciones cercanas de longitud de hilo y longitud de contrapeso, evalúa el desempeño eléctrico de cada una (impedancia y ROE) en cada banda solicitada, y reporta la combinación que ofrece el mejor **desempeño agregado en todas las bandas simultáneamente** — no solo una banda a costa de las demás.

Puede evaluar los candidatos de dos maneras:

- **Modo empírico** — aproximación matemática muy rápida para cribar geometrías. No modela la tierra ni la geometría real del contrapeso y sus valores de reactancia no deben utilizarse para diseñar una adaptación.
- **Modo NEC2** — ejecuta el motor de simulación de antenas por método de momentos `nec2c` para cada geometría candidata. Es un cálculo electromagnético numérico más detallado que el modelo empírico, pero su exactitud respecto de la antena real depende de la calidad del modelo, la segmentación, el suelo y las condiciones de instalación.

Además de la geometría de la antena en sí, el software incluye dos calculadoras de redes de adaptación accesibles desde la misma ventana:

- Un **diseñador de autotransformador UnUn (no balanceado a no balanceado)** basado en núcleos toroidales de ferrita/polvo de hierro.
- Un **diseñador de Transmatch (red de adaptación L/C con bobina derivada)**.

Ambas herramientas de red de adaptación pueden leer automáticamente las impedancias de antena encontradas por el optimizador y proponer una solución de adaptación para ellas.

---

## 2. Cómo funciona, en términos simples

1. **Usted describe el problema de la antena**: qué bandas, aproximadamente cuánto deben medir el hilo y el contrapeso, y qué tan amplio debe ser el rango de búsqueda alrededor de esas longitudes.
2. El programa construye una **cuadrícula de geometrías candidatas** (cada combinación de longitud de hilo × longitud de contrapeso dentro de la ventana de búsqueda, espaciadas según los tamaños de paso que usted elija).
3. **Cada candidato se evalúa** en cada banda solicitada:
   - En *modo NEC2*, el programa escribe un archivo de entrada `.nec` que describe la geometría (radio del hilo, material, tipo de tierra, segmentación, frecuencia) e invoca al simulador externo `nec2c`, luego lee la resistencia (R) y reactancia (X) en el punto de alimentación y calcula la Relación de Onda Estacionaria de Voltaje (ROE/VSWR).
   - En *modo empírico*, R y X se estiman mediante aproximaciones de forma cerrada en lugar de una simulación completa (mucho más rápido, menos preciso cerca de la resonancia).
4. Cada candidato recibe una **puntuación agregada** que combina la penalización por ROE en cada banda activa (peor ROE = peor puntuación), una penalización de "evasión" para candidatos que quedan incómodamente cerca del borde de una banda, y — opcionalmente — una bonificación/penalización relacionada con la ganancia radiada a bajo ángulo en un ángulo de despegue objetivo.
5. El programa también rastrea el **conjunto óptimo de Pareto**: candidatos para los cuales ningún otro candidato es simultáneamente al menos igual de bueno en todas las bandas. Esto muestra las verdaderas compensaciones disponibles, no solo un único "ganador".
6. El mejor candidato (y, opcionalmente, sus vecinos) se **vuelve a simular con alta precisión** (segmentación "fina") para que las cifras con las que realmente va a construir sean confiables, aun cuando la búsqueda amplia haya usado una configuración más gruesa y rápida.
7. Finalmente el programa **escribe los resultados**: un reporte de texto clasificado, un gráfico de dispersión/mapa de calor, un CSV con las cifras por banda de la geometría ganadora, un archivo NEC2 listo para usar, diagramas de patrón de radiación, un plano de construcción, y un "folleto" PDF de una página que resume el diseño, si `reportlab` está instalado.

---

## 3. Requisitos e instalación

### 3.1 Python

La herramienta está implementada en un único script de Python 3. Requiere:

- **Python 3** (cualquier versión razonablemente actual).
- El kit de herramientas gráfico **Tkinter**, si se desea usar la interfaz gráfica. Tkinter viene incluido con la mayoría de las instalaciones de escritorio de Python; en algunas distribuciones de Linux debe instalarse por separado:
  ```bash
  sudo apt install python3-tk
  ```
  Si falta Tkinter, la GUI se negará a iniciar e imprimirá esta instrucción exacta.

### 3.2 Paquetes de Python opcionales pero recomendados

| Paquete | Propósito | Qué ocurre si falta |
|---|---|---|
| `colorama` | Salida de consola coloreada en la terminal | Se usa texto plano, sin colores. No hay pérdida funcional. |
| `matplotlib` | Gráfico del espacio de búsqueda, diagramas de radiación y planos de construcción, incluidos los dibujos de las calculadoras de adaptación | Esas salidas gráficas no pueden generarse sin él. |
| `numpy` | Usado internamente por el generador de diagramas de radiación | Los diagramas de radiación no pueden generarse sin él. En la práctica casi siempre está presente, porque se instala automáticamente como dependencia de `matplotlib`. |
| `reportlab` | Generación del folleto PDF | El PDF se omite si `reportlab` no está instalado. |
| `Pillow` (`PIL`) | Incrusta los PNG de construcción/radiación dentro del folleto PDF | El PDF igual se genera, pero la sección de imagen afectada se reemplaza por un aviso de "no disponible" en lugar de la imagen. |

Instalación habitual:

```bash
pip install colorama matplotlib numpy reportlab pillow
```

`matplotlib`, `reportlab` y `Pillow` son independientes entre sí: `matplotlib` genera las imágenes, `reportlab` genera la estructura del PDF, y `Pillow` incrusta las imágenes dentro de ese PDF. La ausencia de uno no implica necesariamente la ausencia de los otros.

> **Nota sobre el instalador de Windows:** `Setup_Long_Wire_Antenna.exe` también instala con `pip` un paquete llamado `tabulate`, además de los anteriores. En realidad, el script no importa ni usa `tabulate` en ningún lugar de su código — es un resabio sin usar en la lista de dependencias del instalador, no un requisito real de la herramienta. No necesita instalarlo si está configurando el script manualmente.
>
> El instalador también ejecuta un paso posterior a la instalación (`post_install_setup.py`) que intenta opcionalmente descargar una versión más nueva del motor NEC2 desde un proyecto externo de GitHub, como mejora sobre el `nec2c.exe` incluido, volviendo al binario incluido si eso falla. Su lógica de respaldo busca un archivo llamado `onec.exe`/`onec_bundled.exe`, que este instalador en realidad no incluye (solo incluye `nec2c.exe`), por lo que ese camino de respaldo en particular actualmente no hace nada — sin consecuencias, ya que el lanzador instalado (`run_gui.bat`) encuentra y usa `nec2c\nec2c.exe` por su cuenta, sin importar el resultado de este paso. Podés ignorar tranquilamente cualquier mención a `onec.exe` en los registros del instalador.

### 3.3 Motor de simulación NEC2 (`nec2c`)

Para usar el **modo NEC2** (recomendado para cifras finales confiables) necesita tener instalado en su sistema el binario `nec2c` — una implementación compilada del simulador de antenas por método de momentos NEC-2. Fuentes típicas:

- El gestor de paquetes de su distribución Linux (el nombre del paquete varía, p. ej. `nec2c`).
- Compilarlo desde el proyecto de código fuente público `nec2c`.

**El modo empírico no necesita `nec2c` en absoluto**. Puede utilizarse sin un motor NEC2 externo, pero sigue siendo una aproximación.

> **Alternativa de un clic para Linux:** en lugar de instalar `nec2c` y los paquetes de Python anteriores manualmente, puede usar el `Long_Wire_Antenna-x86_64.AppImage` precompilado (o compilar el suyo con `others/build_appimage.sh`), que incluye su propio intérprete de Python, todos los paquetes opcionales y un binario `nec2c` compilado estáticamente, todo en un único archivo portátil. Vea el `README` del proyecto para más detalles. El AppImage siempre abre directamente la GUI.

### 3.4 Localización del binario `nec2c`

El programa busca `nec2c` automáticamente, en este orden:

1. Una ruta explícita indicada con `--nec2c /ruta/a/nec2c` (CLI) o escrita en el campo **Binario NEC2** (GUI).
2. La variable de entorno `$NEC2C`.
3. El `PATH` de su sistema (busca los nombres de ejecutable `nec2c`, `nec2c-mpich` y `onec` — esta es la lista actual y correcta; notas anteriores que mencionaban `xnec2c` eran incorrectas y han sido reemplazadas).
4. Una lista de ubicaciones de instalación comunes (`/usr/bin`, `/usr/local/bin`, `/opt/nec2c/bin`, `/opt/homebrew/bin`, etc.), incluyendo rutas específicas de `onec` como `C:\Program Files\OpenNEC\onec.exe` en Windows.
5. Como último recurso, únicamente en la línea de comandos, le pedirá interactivamente que escriba la ruta (a menos que esté activado `--no-interactive`).

En la GUI, use el botón **Auto-detectar** en la pestaña Física para activar esta búsqueda a demanda.

`onec` es el nombre del ejecutable usado por la compilación del proyecto OpenNEC de este motor; `nec2c` y `nec2c-mpich` son las compilaciones clásicas más comunes. Los tres son admitidos indistintamente por el descubrimiento automático basado en nombre.

---

## 4. Iniciar el programa

### 4.1 Iniciar la GUI

```bash
python src/Long_Wire_Antenna.py --gui
```

Esto abre la ventana interactiva descrita en el resto de este manual. No se necesitan otros parámetros para abrir la GUI — cada configuración se introduce luego a través de la propia interfaz.

`--gui` se detecta en una pasada de pre-análisis antes de leer el resto de la línea de comandos, así que cualquier otro flag que se le agregue (p. ej. `python src/Long_Wire_Antenna.py --gui --bands 40m`) se ignora silenciosamente — la GUI se abre con sus propios valores por defecto de todos modos. Use los campos de la propia GUI, no flags de CLI adicionales, para configurar una ejecución en modo GUI.

### 4.2 Ejecutar desde la línea de comandos (sin GUI)

```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
```

Vea la [Sección 14](#14-la-interfaz-de-línea-de-comandos-cli--referencia-completa) para la lista completa de parámetros. La GUI es, de hecho, un frontend que arma exactamente este tipo de línea de comandos y la ejecuta — cada opción que se ve en la GUI corresponde a uno de estos parámetros, y **la vista previa del comando en la pestaña Ejecutar muestra el comando ensamblado a partir de la configuración actual de la GUI** en tiempo real.

### 4.3 Obtener ayuda de línea de comandos

```bash
python src/Long_Wire_Antenna.py --help
```

### 4.4 Idioma de la interfaz

El texto del programa (tanto los mensajes de la CLI como la GUI) está disponible en **inglés, español e italiano**. Vea la [Sección 12.3](#123-cambio-de-idioma) para saber cómo cambiarlo en la GUI, y `--lang` para la CLI.

---

## 5. La Interfaz Gráfica de Usuario (GUI) — resumen

Al iniciarse con `--gui`, el programa abre una única ventana que contiene:

- Una **barra de encabezado** (título, cambio de idioma, controles de tamaño de fuente).
- Una fila con la **ruta del script del optimizador** (qué archivo de script de Python ejecutará realmente la GUI — vea [12.1](#121-ruta-del-script-del-optimizador)).
- Un **cuaderno de seis pestañas**, cada una agrupando ajustes relacionados:
  1. **Banda / Fuente** — para qué bandas diseñar, y la geometría inicial.
  2. **Rango de búsqueda** — qué tan amplio y con qué finura buscar, además de opciones de contrapeso/retorno a tierra.
  3. **Física** — motor de simulación, modelo de tierra, conductor del hilo, y ajustes de precisión.
  4. **Archivos de salida** — dónde se escriben los resultados y cómo se nombran.
  5. **Ejecutar** — la vista previa del comando, los controles de Ejecutar/Detener, y una consola en vivo.
  6. **UnUn / Transmatch** — dos calculadoras de redes de adaptación independientes (subpestañas).

La GUI **no ejecuta el cálculo principal de optimización dentro de la propia ventana** — construye una línea de comandos a partir de sus ajustes y lanza el script del optimizador como un proceso separado, exactamente como si usted hubiera escrito esa línea de comandos usted mismo. Esto significa:

- La **vista previa del comando** en la pestaña Ejecutar refleja la configuración actual de la GUI y puede copiarse y ejecutarse manualmente si se prefiere.
- Las búsquedas largas se ejecutan en segundo plano; la ventana permanece responsiva y se puede ver el progreso en la consola.
- En principio, se podría apuntar el campo "script del optimizador" a una copia o versión *diferente* del script, y la GUI controlaría esa en su lugar.

Cada campo de texto, casilla de verificación, botón de opción y menú desplegable en las seis pestañas se describe exhaustivamente a continuación, pestaña por pestaña.

---

## 6. Pestaña 1 — Banda / Fuente

Esta pestaña define **para qué** está diseñando: las bandas de operación, las frecuencias (si son necesarias), y la estimación inicial de la longitud de hilo y contrapeso.

### 6.1 Campo "Banda(s)"

- **Qué es:** una lista de nombres de banda separados por comas, p. ej. `40m,20m,15m`.
- **Valor por defecto:** `40m,20m,15m`.
- **Obligatorio:** sí — el optimizador no puede ejecutarse sin al menos una banda.
- Los nombres de banda pueden ser una de las **bandas de radioaficionado conocidas** (vea el [Apéndice, Sección 18](#18-apéndice-bandas-de-radioaficionado-conocidas)) o un nombre personalizado arbitrario de su elección (p. ej. `miBandaEspecial`).
- Justo debajo del campo, una línea de ayuda lista todos los nombres de banda reconocidos, como referencia.

### 6.2 Campo "Frecuencias (MHz)"

- **Qué es:** una lista de frecuencias centrales en MHz separadas por comas, una por banda, en el *mismo orden* que el campo Bandas, p. ej. `7.1,14.2,21.2`.
- **Cuándo es opcional:** si todos los nombres escritos en "Banda(s)" son bandas *reconocidas* (vea la lista bajo el campo, o la [Sección 18](#18-apéndice-bandas-de-radioaficionado-conocidas)), puede dejar este campo vacío — el programa sustituye automáticamente la frecuencia central estándar para cada banda reconocida.
- **Cuándo es obligatorio:** si usa cualquier nombre de banda personalizado/no reconocido, **debe** proporcionar aquí una frecuencia correspondiente, o el programa se detendrá con un error (en uso interactivo por línea de comandos puede pedírsela; la GUI pasará lo que se haya escrito, así que complételo).
- Una línea de ayuda bajo el campo le recuerda esta regla.

### 6.3 Campo "Longitud de hilo (m)"

- **Qué es:** la longitud inicial, en metros, del hilo radiador inclinado — el punto central alrededor del cual se construye la ventana de búsqueda.
- **Valor por defecto:** `21.0`.
- **Obligatorio:** sí.
- Una pista coloreada a la derecha del campo da un breve recordatorio de su función.

### 6.4 Campo "Longitud de contrapeso (m)"

- **Qué es:** la longitud inicial, en metros, del hilo de contrapeso — nuevamente, el centro de la ventana de búsqueda.
- **Valor por defecto:** `5.0`.
- **Obligatorio:** sí, **a menos que** haya desmarcado "Usar contrapeso" en la pestaña Rango de búsqueda (vea [7.3](#73-casilla-usar-contrapeso)), en cuyo caso este campo está deshabilitado (en gris) porque no hay contrapeso que dimensionar.

### 6.5 Sección "Bandas activas"

- **Propósito:** permite indicarle al optimizador que *evalúe* una geometría en todas las bandas listadas en 6.1, pero que solo *puntúe* (clasifique candidatos según) un subconjunto de esas bandas.
- **Campo:** una lista de nombres de banda separados por comas, que debe ser un subconjunto de los nombres en "Banda(s)".
- **Valor por defecto:** vacío, lo que significa que **todas** las bandas listadas en "Banda(s)" se tratan como activas y se usan para la puntuación.
- **Ejemplo de uso:** quiere que el reporte también le muestre cómo se desempeña un diseño en 10 m por curiosidad, pero solo opera realmente en 40 m y 20 m — configure Banda(s) como `40m,20m,10m` y Bandas activas como `40m,20m`.

### 6.6 "Idioma del optimizador" (idioma del reporte)

- **Propósito:** elige en qué idioma se escriben la *salida de consola propia del optimizador y el reporte/PDF generado* — independiente del idioma de visualización propio de la GUI (vea [12.3](#123-cambio-de-idioma)).
- **Opciones:** `auto` (detectar desde la configuración regional del sistema), `en`, `es`, `it`.
- **Valor por defecto:** `auto`.

---

## 7. Pestaña 2 — Rango de búsqueda

Esta pestaña controla **qué tan amplia y fina** es la búsqueda, además de la topología del contrapeso (presente o ausente) y, cuando está ausente, cómo se modela la trayectoria de retorno de RF. También contiene la geometría de la antena (altura, inclinación) y opciones de tamaño del reporte.

### 7.1 Campo "Margen de búsqueda"

- **Qué es:** si *no* se establecen límites mínimo/máximo explícitos (7.2, 7.6), el optimizador busca ± esta cantidad de metros alrededor de la Longitud de hilo y Longitud de contrapeso iniciales.
- **Valor por defecto:** `2.0` m.
- **Anulado por:** valores explícitos de Wire-min/Wire-max o CP-min/CP-max, descritos a continuación.

### 7.2 Sección "Rango de búsqueda del hilo"

Tres campos, todos opcionales:

| Campo | Significado | Comportamiento por defecto si se deja vacío |
|---|---|---|
| `wire-min` | Longitud mínima de hilo a probar (m) | Calculada como longitud inicial − margen |
| `wire-max` | Longitud máxima de hilo a probar (m) | Calculada como longitud inicial + margen |
| `wire-step` | Incremento entre longitudes probadas (m) | `0.25` m |

Una nota bajo los campos recuerda que dejarlos en blanco recurre a la ventana automática basada en el margen.

### 7.3 Casilla "Usar contrapeso"

- **Valor por defecto:** marcada (contrapeso presente).
- **Cuando está marcada:** la antena se modela como un radiador inclinado **más** un hilo de contrapeso inclinado, ambos desde el mismo punto de alimentación. Todos los campos relacionados con el contrapeso en el resto de la GUI (Longitud de contrapeso en la pestaña Banda/Fuente, los campos de rango de contrapeso abajo, y el campo de altura del extremo del contrapeso) están habilitados.
- **Cuando está desmarcada:** la antena se modela **sin** contrapeso alguno. Todos los campos de contrapeso quedan deshabilitados (en gris) pero *conservan en memoria* el valor escrito — volver a marcar la casilla restaura exactamente lo que se tenía. Desmarcar esto agrega `--no-counterpoise` al comando, y activa la sección **"Trayectoria de retorno sin contrapeso"** de abajo, que se vuelve obligatoria en este caso.

### 7.4 Sección "Trayectoria de retorno sin contrapeso"

Esta sección solo importa — y solo está habilitada — cuando "Usar contrapeso" (7.3) está **desmarcada**. Selecciona cómo se modela la trayectoria de retorno de RF en ausencia de un hilo de contrapeso, ya que debe existir algún tipo de trayectoria de retorno para que la simulación tenga sentido físico. Tres opciones mutuamente excluyentes:

- **`ground-rod`** (por defecto) — modela la trayectoria de retorno como una conexión directa a tierra/jabalina.
- **`coax-stub`** — modela la trayectoria de retorno como un cabo de trenza coaxial de una longitud especificada. Seleccionar esto habilita el campo **"Longitud del cabo CP"** debajo (valor por defecto: tomado de la longitud de cabo por defecto del programa; edítelo según sea necesario).
- **`reject`** — se niega a sintetizar cualquier trayectoria de retorno implícita; use esto si planea modelar la trayectoria de retorno usted mismo de otra manera, o si desea que el programa marque configuraciones donde no se defina ninguna trayectoria de retorno.

Una línea de ayuda coloreada arriba de los botones explica esta compensación. En modo NEC2, `reject` rechaza explícitamente la configuración; `ground-rod` se modela con tierra perfecta (GN 1) y `coax-stub` mantiene el modelo de tierra seleccionado. En modo empírico estas opciones de retorno no forman parte del modelo empírico.

### 7.5 Sección "Radiación / ángulo de despegue"

Controla cómo (y si) la puntuación premia la ganancia radiada a bajo ángulo, lo cual importa más para el trabajo DX (larga distancia):

| Campo | Significado | Valor por defecto |
|---|---|---|
| Ángulo de despegue objetivo | El ángulo de elevación (grados sobre el horizonte) en el que se evalúa la bonificación/penalización de ganancia | `25.0°` |
| Peso de ganancia | Con qué fuerza influye la ganancia en ese ángulo en la puntuación agregada, en unidades de puntuación por dB. Aproximadamente, 5 dB de diferencia de ganancia ≈ 1.0 unidad de puntuación | `0.20` por dB |
| Reclasificar los N mejores | Cuántos de los mejores candidatos según ROE reciben una resimulación completa de patrón de radiación (necesaria para medir realmente la ganancia en el ángulo objetivo) antes de aplicar la bonificación de ganancia | `6` |

Una pista debajo explica la compensación: reclasificar más candidatos (N más alto) cuesta más tiempo de cómputo, pero da a la reclasificación basada en ganancia un grupo más amplio de candidatos casi óptimos entre los cuales elegir.

### 7.6 Sección "Rango de búsqueda del contrapeso"

Refleja la sección de rango de búsqueda del hilo (7.2), pero para la longitud del contrapeso. Solo tiene sentido (y solo afecta al comando) cuando "Usar contrapeso" está marcada:

| Campo | Significado | Comportamiento por defecto si se deja vacío |
|---|---|---|
| `cp-min` | Longitud mínima de contrapeso a probar (m) | Calculada como longitud inicial − margen |
| `cp-max` | Longitud máxima de contrapeso a probar (m) | Calculada como longitud inicial + margen |
| `cp-step` | Incremento entre longitudes probadas (m) | `0.25` m |

### 7.7 Sección "Geometría de la antena"

Una **altura de punto de alimentación** compartida para toda la antena, más controles de inclinación opcionales:

| Campo | Significado | Valor por defecto |
|---|---|---|
| **Altura** | Altura del punto de alimentación sobre el suelo (metros). Compartida tanto por el radiador como por el contrapeso, ya que ambos cuelgan del mismo punto de alimentación. | `8.0` m |
| **Altura del extremo de inclinación del hilo** | Altura sobre el suelo (metros) del *extremo lejano* del hilo radiador (el extremo alejado del punto de alimentación). `0.0` significa que el hilo se inclina hasta tocar el suelo (un hilo totalmente diagonal). Déjelo vacío para mantener el hilo perfectamente horizontal a la altura del punto de alimentación. **Establecer este valor fuerza el modo NEC2** — las fórmulas empíricas no modelan geometría inclinada. | vacío (hilo horizontal) |
| **Altura del extremo del contrapeso** | La misma idea, pero para el extremo lejano del hilo de contrapeso. Déjelo vacío para mantener el contrapeso al nivel de la altura del punto de alimentación de la antena. | vacío (al nivel de la altura de la antena) |

### 7.8 Sección "Reintentos máximos"

- **Qué es:** si el candidato ganador queda justo en el *borde* de la ventana de búsqueda (p. ej., la mejor longitud de hilo encontrada es igual a `wire-max`), eso es una señal de que el verdadero óptimo puede estar fuera de la ventana buscada. Este ajuste le indica al programa que vuelva a ejecutar automáticamente la búsqueda, desplazando la ventana en la dirección sugerida por esa advertencia, hasta N veces adicionales.
- **Control:** un spinbox de `0` a `10`.
- **Valor por defecto:** `0` (deshabilitado — sin reintento automático).

### 7.9 Sección "Opciones de reporte"

- **Top N** — cuántos de los mejores candidatos listar en el reporte final clasificado.
- **Control:** un spinbox de `5` a `200`.
- **Valor por defecto:** `20`.

---

## 8. Pestaña 3 — Física

Esta pestaña controla el **motor de simulación**, el **modelo de tierra**, las propiedades del **conductor del hilo**, y la **precisión numérica** (segmentación) de la simulación NEC2.

### 8.1 Sección "Modo de evaluación"

Tres botones de opción mutuamente excluyentes:

- **`auto`** (por defecto) — usa simulación NEC2 si se puede encontrar un binario `nec2c` funcional; de lo contrario recurre a las fórmulas empíricas.
- **`nec2`** — siempre usa simulación NEC2 completa. Falla con un error si no hay ningún binario `nec2c` disponible.
- **`empirical`** — siempre usa las fórmulas aproximadas rápidas, incluso si `nec2c` está disponible. Útil para primeros pases rápidos y gruesos.

### 8.2 Fila "Binario NEC2"

- **Campo de texto:** la ruta explícita del sistema de archivos al ejecutable `nec2c`. Déjelo vacío para depender del descubrimiento automático (vea la [Sección 3.4](#34-localización-del-binario-nec2c)).
- **Botón Examinar:** abre un cuadro de diálogo selector de archivos para elegir el binario desde el disco.
- **Botón Auto-detectar:** ejecuta inmediatamente la misma búsqueda de descubrimiento que realiza el optimizador al iniciarse (verifica `$NEC2C`, `PATH`, directorios de instalación comunes) y completa el campo si se encuentra algo.
- Una línea de ayuda debajo explica el orden de descubrimiento.

### 8.3 Sección "Tierra"

Controla las propiedades eléctricas de la tierra bajo la antena, usadas por el modelo de tierra de Sommerfeld-Norton de NEC2:

| Campo | Significado | Valor por defecto |
|---|---|---|
| **Conductividad** | Conductividad del suelo, en Siemens por metro (S/m) | `0.005` S/m |
| **Permitividad** | Permitividad relativa del suelo (adimensional) | `13.0` |

**Ajustes rápidos predefinidos** — cinco botones que llenan instantáneamente ambos campos con valores de referencia de uso común:

| Preset | Conductividad (S/m) | Permitividad |
|---|---|---|
| Suelo pobre | `0.001` | `5` |
| Suelo promedio | `0.005` | `13` |
| Suelo bueno | `0.010` | `20` |
| Suelo excelente | `0.030` | `25` |
| Agua salada | `5.000` | `80` |

### 8.4 Sección "Modelo de tierra"

Dos botones de opción mutuamente excluyentes:

- **`sommerfeld`** (por defecto) — usa el modelo de tierra de Sommerfeld-Norton de NEC2, que tiene en cuenta correctamente los valores finitos de conductividad/permitividad anteriores. Físicamente realista, recomendado para instalaciones reales.
- **`perfect`** — asume una tierra perfectamente conductora (una idealización). Se ejecuta más rápido pero es optimista/irreal para la mayoría de los sitios reales; útil principalmente para comparación o verificación de coherencia.

Una pista debajo explica esta compensación.

### 8.5 Sección "Hilo / conductor"

Controla el hilo físico usado para construir el modelo de la antena:

- **Diámetro del hilo (mm)** — el diámetro del conductor. El valor por defecto corresponde a un hilo de 2 mm de diámetro (1 mm de radio), aproximadamente hilo de cobre AWG 12.
- **Material del hilo** — un menú desplegable (combobox) de materiales conductores, cada uno con un valor de conductividad fijo incorporado:

  | Material (clave en inglés) | Conductividad (S/m) |
  |---|---|
  | Cobre (por defecto) | 5.80 × 10⁷ |
  | Aluminio | 3.54 × 10⁷ |
  | Latón | 1.56 × 10⁷ |
  | Plata | 6.30 × 10⁷ |
  | Acero (galvanizado) | 6.99 × 10⁶ |
  | Perfecto (sin pérdidas, solo para comparación) | — (no se escribe ninguna tarjeta de pérdidas) |

  La etiqueta del menú desplegable se muestra en el idioma que la GUI esté mostrando en ese momento (p. ej. "cobre" en español), pero internamente el programa siempre envía el nombre canónico en inglés al script subyacente, por lo que cambiar el idioma de visualización de la GUI nunca rompe este ajuste.

- **Anulación de conductividad del hilo (S/m)** — un campo opcional para especificar manualmente un valor de conductividad que no coincida con ninguno de los materiales estándar anteriores. Déjelo vacío para usar el valor implícito del menú desplegable de Material. Una pista debajo explica cuándo querría hacer esto (p. ej., una aleación específica o el valor de la hoja de datos de un fabricante).

> **Por qué esto importa:** sin un ajuste de conductividad/pérdidas, NEC2 asume que cada hilo es un conductor *perfecto* (sin pérdidas), lo que sobreestima la ganancia — especialmente para el hilo delgado y los contrapesos cortos que esta herramienta tiende a favorecer, donde las pérdidas resistivas (I²R) no son despreciables. Configurar un material real da cifras de ganancia realistas, ligeramente más conservadoras.

### 8.6 Sección "Precisión / Segmentación"

NEC2 subdivide cada hilo en "segmentos" cortos para el cálculo; cuántos segmentos por media longitud de onda afecta fuertemente la precisión, especialmente para la impedancia en el punto de alimentación (a diferencia de solo la forma del patrón de radiación) — la densidad de segmentación puede cambiar tanto R como X. **Más segmentos no garantizan por sí solos una solución físicamente más exacta**: hay que comprobar la convergencia y recordar que NEC2 sigue siendo un modelo numérico de una geometría idealizada.

Tres botones de opción mutuamente excluyentes:

- **`fine`** (por defecto) — 90 segmentos por media longitud de onda. Se usa para cada cifra que realmente se publica (las cifras finales del candidato ganador, el archivo `.nec` exportado, el reporte, el CSV). **No debe interpretarse como una garantía de convergencia** — recomendado para cualquier cosa que se pretenda construir, combinado con "Reverificar convergencia" más abajo para un diseño final.
- **`fast`** — 21 segmentos por media longitud de onda. Es una densidad deliberadamente gruesa: el propio programa advierte que puede producir aproximadamente un **14 % de error en R (medida baja)** y **errores de signo en X** en determinados casos. Se utiliza para barridos rápidos y trabajo de patrones únicamente — sus impedancias no deben emplearse jamás para dimensionar una adaptación ni para una decisión de construcción.
- **`custom`** — escriba su propio valor de segmentos por media longitud de onda en el campo adyacente. El valor por defecto interno del programa para el *barrido* de búsqueda en sí (a diferencia de las cifras finales publicadas) es de 45 segmentos por media longitud de onda — un término medio elegido porque la clasificación de candidatos entre sí es bastante insensible a esta densidad, aunque las cifras absolutas no lo sean. Salvo que esta opción sobrescriba ambas, el barrido normal utiliza 45 segmentos por media onda y la ejecución final 90.

**Casilla "Reverificar convergencia"** — cuando está habilitada, la geometría ganadora se vuelve a simular automáticamente una segunda y una tercera vez, a 2× y 4× la densidad de trabajo, y el reporte mide cuánto se movieron todavía R y X entre esas ejecuciones. El umbral de aproximadamente 3 % se aplica a la deriva de R; X tiene una tolerancia independiente. Si R se mueve más de aproximadamente un 3 %, el reporte lo marca — una señal de que quizás quiera aumentar más el ajuste de densidad fina antes de construir; si la convergencia no es satisfactoria, no se debe dimensionar una red de adaptación a partir de X.

> **Importante:** las cifras NEC2 son resultados del modelo, no mediciones de la antena real. La altura, geometría, conductor, suelo, pérdidas, proximidad de objetos y la propia instalación pueden cambiar el resultado. Para una construcción final, verifique el sistema real con medición (por ejemplo, VNA) antes de cortar o fijar definitivamente el hilo.

Una pista coloreada al final de la sección resume todo esto.

---

## 9. Pestaña 4 — Archivos de salida

Esta pestaña controla **dónde** se escriben los resultados y **cómo se nombran**.

### 9.1 Sección "Directorio de trabajo"

- **Campo:** la carpeta donde se escribirán todos los archivos de salida.
- **Valor por defecto:** su directorio de inicio (home).
- **Botón Examinar:** abre un cuadro de diálogo selector de carpeta.
- Una línea de ayuda explica que esta carpeta se crea automáticamente si aún no existe.

### 9.2 Sección "Archivos de salida"

Siete nombres de archivo editables de forma independiente, cada uno escrito dentro del directorio de trabajo mencionado arriba:

| Campo | Nombre de archivo por defecto | Contenido |
|---|---|---|
| `out-txt` | `optimizer_report.txt` | Reporte clasificado que contiene los candidatos Top-N, el conjunto óptimo de Pareto y una interpretación en lenguaje simple del ganador |
| `out-png` | `optimizer_plot.png` | Un gráfico de dispersión/mapa de calor del espacio de búsqueda más gráficos de barras de ROE por banda |
| `out-csv` | `optimizer_best.csv` | Las cifras de frecuencia/R/X por banda del candidato ganador, legibles por máquina — esto es lo que la pestaña UnUn/Transmatch lee automáticamente |
| `out-nec` | `best_antenna.nec` | El archivo de entrada NEC2 terminado para la geometría ganadora, incluyendo tarjetas completas de patrón de radiación (RP) para cada banda activa — listo para cargarse en cualquier herramienta basada en NEC2 |
| `out-radiation` | `radiation_diagrams.png` | Diagramas de patrón de radiación para cada banda activa; se generan solo con evaluación NEC2 |
| `out-construction` | `antenna_construction.png` | Un plano de construcción acotado a partir del cual se puede construir |
| `out-pdf` | `antenna_brochure.pdf` | Un resumen en PDF de una página ("folleto") que combina las cifras clave, gráficos y el plano de construcción |

No se recomienda dejar en blanco ninguno de estos campos, ya que la salida correspondiente simplemente no se producirá con un nombre predecible; los valores por defecto son adecuados para casi todos los usos.

---

## 10. Pestaña 5 — Ejecutar

Aquí es donde se lanza el optimizador, se observa su progreso, y se salta directamente a los archivos generados.

### 10.1 Sección "Varios"

Dos casillas de verificación, ambas **marcadas por defecto**:

- **Silencioso** — agrega `--quiet` al comando, suprimiendo los mensajes detallados de progreso mientras conserva los resultados y advertencias importantes. **Predeterminado en la GUI: marcado.** Desmárquela para obtener el máximo detalle de diagnóstico.
- **Sin preguntas interactivas** — agrega `--no-interactive`, indicándole al optimizador que falle inmediatamente con un mensaje de error si falta una entrada requerida, en lugar de pausar para hacer una pregunta en la terminal (que de todos modos nunca sería visible desde dentro de la GUI — por lo que normalmente esto debería permanecer marcado al ejecutarse desde la GUI).

### 10.2 Cuadro "Vista previa del comando"

Un cuadro de texto de solo lectura que muestra la **línea de comandos exacta** que la GUI está por ejecutar, construida en vivo a partir de cada ajuste en cada pestaña. Este cuadro se actualiza automáticamente, sin ningún botón que presionar, cada vez que se cambia cualquier campo en cualquier lugar del programa (con un breve retraso para que escribir rápidamente no cause parpadeo constante). Si alguna vez desea ejecutar el optimizador manualmente desde una terminal con exactamente los mismos ajustes, puede copiar este texto directamente.

### 10.3 Controles de Ejecutar / Detener y estado

- **Botón Ejecutar** — inicia el optimizador como un proceso en segundo plano. Antes de comenzar, la GUI:
  1. Valida que todos los campos puedan ensamblarse en un comando válido (si no, un cuadro de diálogo de error explica qué está mal).
  2. Confirma que el archivo del script del optimizador realmente existe en el disco.
  3. Crea el directorio de trabajo si aún no existe.

  Mientras se ejecuta, el botón Ejecutar está deshabilitado, el botón Detener se activa, y una barra de progreso se anima.

- **Botón Detener** — termina inmediatamente el proceso del optimizador en ejecución. Solo habilitado mientras una ejecución está en curso.

- **Botón "Mostrar reporte"** — abre el archivo de reporte de texto generado en el visor de texto por defecto del sistema. Solo habilitado una vez que una ejecución ha finalizado con éxito **y** el archivo de reporte existe en el disco.

- **Botón "Mostrar patrón de radiación"** — abre el PNG del diagrama de radiación en el visor de imágenes por defecto del sistema. Misma condición de habilitación que arriba.

- **Botón "Mostrar PDF"** — abre el folleto PDF generado en el visor de PDF por defecto del sistema. Misma condición de habilitación que arriba.

- **Etiqueta de estado** — muestra el estado actual en palabras: inactivo, en ejecución, finalizado con éxito, finalizado con un error/código de salida, o detenido por el usuario.

### 10.4 Consola

Un área de texto desplazable, de solo lectura, que refleja todo lo que el proceso del optimizador imprime en su consola, en tiempo real, con un código de colores simple:

- **Rojo** — líneas que contienen palabras clave de tipo error (error, failed, traceback).
- **Amarillo** — líneas que contienen palabras clave de tipo advertencia.
- **Verde** — líneas que indican éxito (saved, done, best, marcas de verificación).
- **Color de encabezado** — líneas separadoras de sección.

Un botón **Limpiar** vacía la vista de la consola (esto no afecta a ningún archivo ya escrito).

### 10.5 Qué ocurre automáticamente cuando una ejecución finaliza con éxito

La GUI intenta automáticamente cargar el `optimizer_best.csv` recién producido en la **pestaña UnUn / Transmatch** (Sección 11) en segundo plano, de modo que las calculadoras de red de adaptación queden pre-pobladas con las propias impedancias de la antena en el momento en que finaliza la optimización — no necesita cambiar de pestaña y recargar manualmente (aunque aún puede hacerlo, mediante el botón Recargar descrito en 11.1).

---

## 11. Pestaña 6 — UnUn / Transmatch

Esta pestaña es **independiente de la ejecución del optimizador** — se puede usar en cualquier momento, con cualquier dato de impedancia, se haya ejecutado o no alguna vez una optimización. Contiene dos subpestañas.

### 11.1 Subpestaña: UnUn Toroide

Diseña un autotransformador de banda ancha (UnUn) devanado sobre un núcleo toroidal de ferrita o polvo de hierro para transformar la impedancia del punto de alimentación de la antena hacia una impedancia coaxial estándar (típicamente 50 Ω).

#### 11.1.1 Sección "Antena"

- **Selector de banda (desplegable)** — una vez que se han cargado los datos de la antena (ver abajo), permite elegir con la impedancia de qué banda trabajar; seleccionar una banda autocompleta los campos de abajo con la frecuencia, R y X de esa banda.
- **Botón Recargar** — vuelve a leer el archivo `optimizer_best.csv` desde la ubicación de salida configurada, actualizando el menú desplegable de banda y los datos.
- **Botón Exportar** — exporta los resultados actuales del cálculo del UnUn.
- **Línea de estado** — indica si los datos de la antena se cargaron con éxito, y desde dónde.
- Campos editables manualmente (autocompletados por el selector de banda, pero libremente editables para explorar cifras hipotéticas sin volver a ejecutar el optimizador):
  - **Frecuencia (MHz)** — por defecto `7.100`.
  - **R_out, X_out (Ω)** — la impedancia del lado de la antena (salida) que el UnUn debe transformar *desde*. Por defecto `450`, `150`.
  - **R_in, X_in (Ω)** — la impedancia del lado coaxial (entrada) que el UnUn debe transformar *hacia*. Por defecto `50`, `0`.

#### 11.1.2 Sección "Núcleo"

- **Menú desplegable de núcleo** — elija el número de parte del toroide de la base de datos incorporada (vea la [Sección 19](#19-apéndice-base-de-datos-de-núcleos-toroidales-pestaña-unun) para la lista completa y especificaciones). Por defecto: `FT-240-31`.
- **Línea de información** — muestra las especificaciones clave del núcleo seleccionado (material, dimensiones, etc.).
- **Número de vueltas primarias (Np)** — por defecto `15`.
- **Diámetro del hilo (mm)** — por defecto `2.0`.
- A la derecha se muestra un **diagrama constructivo** del toroide devanado. Pulse **ACTUALIZAR GRÁFICO** para generarlo o volver a dibujarlo después de cambiar núcleo/vueltas/hilo; el programa marca el dibujo como desactualizado cuando cambian los datos. Haga clic sobre el dibujo para verlo a tamaño completo.

#### 11.1.3 Panel de "Resultados"

Un panel de texto desplazable, monoespaciado y con código de colores que reporta el diseño de UnUn calculado: relación de vueltas, impedancia transformada, calidad de adaptación esperada, estimación de pérdidas/calentamiento del núcleo, y cualquier advertencia (p. ej., vueltas insuficientes, núcleo cerca de saturación o sobretemperatura, o la advertencia de autorresonancia descrita en 11.1.4).

#### 11.1.4 Sección "Multibanda"

Dado que un único diseño de UnUn se usa en todas las bandas que cubre la antena, esta sección evalúa qué tan bien se desempeña **un UnUn elegido** en **todas** las bandas cargadas desde el CSV del optimizador simultáneamente — no solo la banda única seleccionada arriba.

- **Casilla Auto** (marcada por defecto) — cuando está habilitada, el programa busca automáticamente el mejor valor de componente de red de adaptación y relación de vueltas en todas las bandas; cuando está desmarcada, usted proporciona los valores manualmente.
- **Menú desplegable Tipo** — `L`, `C`, o `none`: si la red de compensación multibanda es inductiva, capacitiva o está ausente.
- **Campo Valor** — el valor de componente elegido manualmente (solo se usa cuando Auto está desmarcado).
- **Campo Relación** — la relación de vueltas del UnUn elegida manualmente (solo se usa cuando Auto está desmarcado).
- **Campo Z0** — la impedancia de referencia/objetivo para la evaluación multibanda. Por defecto `50` Ω.
- **Tabla de resultados** — una fila por banda, mostrando: nombre de banda, frecuencia, R, X, reactancia compensadora, impedancia de entrada resultante, ROE sin y con compensación, y la diferencia entre ambas.

> **Nota técnica importante incorporada en esta herramienta:** un transformador toroidal derivado/devanado solo se comporta como un autotransformador ideal *por debajo* de su propia frecuencia de autorresonancia (SRF). Por encima de la SRF, el devanado pasa a ser dominado capacitivamente y el modelo simple de relación de vueltas ya no aplica — sin embargo, diseños anteriores e ingenuos podían reportar silenciosamente una ROE de apariencia plausible (pero incorrecta) para una banda que en realidad está por encima de la SRF del devanado. Esta herramienta verifica la SRF del devanado y acortará/ajustará el devanado de referencia automático hasta que la SRF supere la banda solicitada más alta con un margen de seguridad (1.5×), y marca las filas donde la propia reactancia del devanado no es cómodamente mayor que la impedancia de la antena (una señal de que la derivación está siendo "cargada" por la bobina en lugar de transformar limpiamente a través de ella).

### 11.2 Subpestaña: Transmatch

Diseña una red de adaptación de bobina derivada (estilo autotransformador) — un clásico "Transmatch" o "ATU" — como alternativa o complemento al UnUn.

#### 11.2.1 Sección "Global"

| Campo | Significado | Valor por defecto |
|---|---|---|
| Z0 | Impedancia de referencia/objetivo | `50` Ω |
| Diámetro del hilo | Diámetro del hilo de la bobina | `1.0` mm |
| Diámetro del núcleo / forma | Diámetro del cuerpo de la bobina | `50` mm |
| Espaciado del devanado | Espaciado entre vueltas | `1.0` mm |
| Devanado de referencia (vueltas) | Número de vueltas usado como la derivación de referencia Z0 | vacío (en blanco) |
| Casilla **Referencia automática** | Cuando está marcada, la longitud del devanado de referencia anterior se calcula automáticamente en lugar de introducirse manualmente | marcada por defecto |

#### 11.2.2 Tabla de "Derivaciones"

Una tabla editable de hasta **11 filas**, cada una representando una banda que desea que el Transmatch cubra, con columnas: **Derivación N°**, **Banda**, **Frecuencia (MHz)**, **R (Ω)**, **X (Ω)**, y una casilla **Activa** para incluir/excluir esa fila del cálculo. Tres filas están precargadas con valores de ejemplo por defecto (40 m / 20 m / 10 m) de modo que la página sea usable incluso antes de haber ejecutado alguna vez el optimizador:

| N° | Banda | Frec (MHz) | R (Ω) | X (Ω) |
|---|---|---|---|---|
| 1 | 40m | 7.150 | 75 | −12 |
| 2 | 20m | 14.170 | 67 | 23 |
| 3 | 10m | 28.000 | 45 | 10 |

Junto a la tabla se muestra un **diagrama constructivo** de la bobina y sus derivaciones. Pulse **ACTUALIZAR GRÁFICO** para generarlo o volver a dibujarlo después de cambiar los datos; el dibujo se marca como desactualizado cuando la configuración cambia.

#### 11.2.3 Tabla de resultados "Devanado"

Para cada fila de derivación activa: banda, frecuencia, R, R realizada (después de la cuantización de la derivación), el error resultante, vueltas desde la referencia, vueltas totales/delta, longitud de hilo, resistencia en DC, longitud acumulada, impedancia y fase resultantes, ROE, pérdida de retorno, pérdida por desadaptación, y fracción de potencia reflejada.

#### 11.2.4 Tabla de resultados "Compensación"

Para cada fila de derivación activa: banda, frecuencia, R, X, la reactancia compensadora necesaria, y los valores equivalentes de inductor/capacitor serie o inductor/capacitor en derivación que reducirían más la ROE (útil si la bobina derivada por sí sola no cancela completamente la reactancia), más la ROE resultante en una cifra de referencia (con tolerancia de 5 Ω).

#### 11.2.5 Panel de texto "Construcción de la bobina"

Un resumen monoespaciado, con código de colores, de exactamente cómo devanar físicamente la bobina: vueltas totales, dónde colocar cada derivación, longitud de hilo requerida, y cualquier advertencia (vueltas insuficientes, espaciado de derivación poco realista, etc.).

#### 11.2.6 Nota de guía de construcción

Un breve recordatorio/etiqueta al pie de la subpestaña con orientación práctica de construcción.

---

## 12. Barra de encabezado y controles globales

### 12.1 Ruta del script del optimizador

En la parte superior de la ventana, debajo del encabezado, una fila permite especificar **qué archivo de script** debe ejecutar realmente la GUI al presionar "Ejecutar" en la pestaña Ejecutar.

- **Campo:** ruta del sistema de archivos al script `Long_Wire_Antenna.py`.
- **Valor por defecto:** la ruta del script que se usó para iniciar la propia GUI.
- **Botón Examinar:** abre un cuadro de diálogo selector de archivos.

Solo necesitaría cambiar esto si mantiene varias versiones del script y desea cambiar cuál controla la GUI, sin reiniciar la GUI desde una copia diferente.

### 12.2 Controles de tamaño de fuente

Dos pequeños botones (`−` y `+`) junto a una etiqueta numérica permiten reducir o aumentar el tamaño de fuente de la GUI sobre la marcha, útil para pantallas de alta resolución o comodidad visual. El tamaño actual se muestra entre los dos botones.

### 12.3 Cambio de idioma

Un botón en el encabezado alterna el **idioma de visualización propio de la GUI** entre inglés, español e italiano. Esto es independiente de:

- El ajuste "Idioma del optimizador" en la pestaña Banda/Fuente (Sección 6.6), que controla el idioma de la **salida de consola propia del optimizador y del reporte/PDF generado**, no de los menús y etiquetas de la GUI.
- El parámetro CLI `--lang`, que solo afecta a las ejecuciones del script por línea de comandos sin la GUI.

Cambiar de idioma reetiqueta cada pestaña, campo, menú desplegable y texto de ayuda en su lugar, sin perder nada de lo que se haya escrito — incluyendo el menú desplegable de Material del hilo, que se rastrea internamente por su valor canónico (en inglés) sin importar qué etiqueta se muestre en ese momento, de modo que la línea de comandos subyacente nunca se ve afectada por un cambio de idioma.

---

## 13. Entendiendo los archivos de salida

### 13.1 El reporte de texto (`optimizer_report.txt`)

Contiene, en orden general:

1. Un resumen de la ejecución: bandas evaluadas, bandas activas, modo utilizado, geometría, suelo, conductor y segmentación.
2. Una tabla clasificada de los mejores N candidatos (según el ajuste "Top N"), cada uno con su longitud de hilo, longitud de contrapeso, R/X/ROE por banda, y su puntuación agregada.
3. El conjunto óptimo de Pareto: candidatos para los cuales ningún otro candidato es al menos igual de bueno en *todas* las bandas simultáneamente — este es el conjunto de compensaciones genuinas, útil cuando podría estar dispuesto a sacrificar desempeño en una banda para ganarlo en otra.
4. Una interpretación en lenguaje simple del candidato ganador, incluyendo cualquier advertencia (p. ej., "la longitud del hilo puede necesitar ser mayor — cayó en el borde de la ventana de búsqueda").
5. Cuando hay datos de patrón disponibles, una tabla de **ganancia máxima y ganancia al ángulo de despegue objetivo (TOA)** por banda, además de advertencias para TOA alto.
6. Una tabla por banda con la impedancia del lado de antena (`R_ant`, `X_ant`) y del lado del transmisor (`R_tx`, `X_tx`), la ROE y el origen de los datos.
7. Si se usó `--converge` (la casilla "Reverificar convergencia"), una breve sección que reporta cuánto se movieron todavía R y X a 2× y 4× la densidad de segmentación.
8. El análisis del UnUn: relación seleccionada, barrido de relaciones estándar, óptimo continuo y mejores relaciones por banda.

El informe también puede incluir advertencias de límites de búsqueda, geometría, convergencia y calidad de los resultados.

### 13.2 El PNG de dispersión/gráfico (`optimizer_plot.png`)

Una representación de mapa de calor/dispersión de toda la cuadrícula de búsqueda (longitud de hilo × longitud de contrapeso), con código de colores según la puntuación agregada, más gráficos de barras de la ROE lograda en cada banda activa por el candidato ganador.

### 13.3 El CSV (`optimizer_best.csv`)

Resultados por banda legibles por máquina solo para el candidato *ganador*: las columnas típicamente incluyen nombre de banda, frecuencia (MHz), resistencia en el punto de alimentación (`R_wire_ohm`), reactancia en el punto de alimentación (`X_wire_ohm`), un indicador `active`, y la relación de UnUn usada durante la evaluación. **Este es el archivo que la pestaña UnUn/Transmatch lee automáticamente** para prepoblar su menú desplegable de banda y su tabla de derivaciones.

### 13.4 El archivo NEC2 (`best_antenna.nec`)

Un archivo de entrada NEC2 completo y listo para ejecutar que describe la geometría ganadora a la densidad de segmentación fina (calidad de publicación), incluyendo tarjetas de solicitud de patrón de radiación (RP) para cada banda activa. Puede cargar este archivo en cualquier herramienta compatible con NEC2 (no solo este script) para inspeccionar, modificar o analizar más a fondo el diseño.

### 13.5 Diagramas de radiación (`radiation_diagrams.png`)

Se generan **solo cuando la ejecución final utiliza NEC2 y hay un binario NEC2 disponible**. Muestran los patrones calculados para las bandas activas. En modo empírico no se genera este archivo porque el modelo empírico no calcula un patrón de radiación NEC2.

Gráficos de patrón de radiación de elevación y/o azimut para la antena ganadora, uno por banda activa.

### 13.6 Plano de construcción (`antenna_construction.png`)

Un diagrama acotado destinado a usarse directamente como referencia de construcción: longitudes de hilo, altura del punto de alimentación, ángulos de inclinación, etc.

### 13.7 Folleto PDF (`antenna_brochure.pdf`)

El programa intenta generar este resumen de una página al finalizar una ejecución con un candidato válido. Requiere **`reportlab`**, no `matplotlib`. El PDF puede incluir el plano de construcción y, cuando se dispone de ellos, los diagramas de radiación NEC2. Si `reportlab` no está instalado, el programa informa del problema y omite el PDF; la ejecución y las demás salidas no dependen de `reportlab`.

Un resumen combinado de una sola página — cifras clave, la geometría ganadora, y el plano de construcción — adecuado para imprimir o archivar junto a las notas de su estación.

### 13.8 Limitaciones importantes de las salidas y del modelado

- `matplotlib` es necesario para el gráfico del espacio de búsqueda, el plano de construcción y los diagramas de radiación.
- Los diagramas de radiación son exclusivos de NEC2. El modo empírico puede producir resultados numéricos de optimización, pero no patrones de radiación físicamente simulados.
- El archivo NEC2 exportado es un modelo, no una garantía de construcción. Verifique la antena real con un analizador/VNA y tenga en cuenta las corrientes de modo común del coaxial, soportes, conductores cercanos, el suelo real y la geometría real de instalación.
- El retorno `ground-rod` en NEC2 se implementa como una conexión galvánica a **tierra perfecta (GN 1)**. No es un modelo de la impedancia de una jabalina real. El programa cambia el modelo de tierra a perfecta para ese caso y registra una advertencia.
- Las calculadoras de adaptación utilizan modelos de ingeniería y componentes idealizados. Sus valores son puntos de partida para construir y ajustar, no valores medidos ni sustituyen la verificación final en RF.


---

## 14. La interfaz de línea de comandos (CLI) — referencia completa

Esta tabla es la referencia autoritativa para los nombres exactos de los parámetros, tipos y valores por defecto, útil si desea ejecutar la herramienta desde scripts, tareas cron, o una terminal en lugar de la GUI.

| Parámetro | Tipo | Por defecto | Significado |
|---|---|---|---|
| `--bands NAMES` | cadena (lista separada por comas) | *(ninguno — obligatorio)* | Nombres de banda separados por comas. |
| `--freqs MHZ` | cadena (lista separada por comas) | *(ninguno)* | Frecuencias centrales en MHz, una por banda. Opcional para bandas reconocidas, obligatorio para nombres personalizados. |
| `--wire-len M` | flotante | *(ninguno — obligatorio)* | Longitud inicial del hilo en metros (centro de la ventana de búsqueda). |
| `--cp-len M` | flotante | *(ninguno — obligatorio salvo con `--no-counterpoise`)* | Longitud inicial del contrapeso en metros (centro de la ventana de búsqueda). |
| `--active-bands BANDS` | cadena (lista separada por comas) | todas las bandas | Qué bandas puntuar; omítalo para puntuar todas las de `--bands`. |
| `--mode {empirical,nec2,auto}` | selección | `auto` | Motor de evaluación. |
| `--nec2c PATH` | ruta | *(autodescubierto)* | Ruta explícita al binario `nec2c`. |
| `--margin M` | flotante | `2.0` | Radio de búsqueda (metros) alrededor de las longitudes iniciales. |
| `--wire-min M` | flotante | inicial − margen | Longitud mínima de hilo a buscar. |
| `--wire-max M` | flotante | inicial + margen | Longitud máxima de hilo a buscar. |
| `--wire-step M` | flotante | `0.25` | Incremento de longitud de hilo. |
| `--cp-min M` | flotante | inicial − margen | Longitud mínima de contrapeso a buscar. |
| `--cp-max M` | flotante | inicial + margen | Longitud máxima de contrapeso a buscar. |
| `--cp-step M` | flotante | `0.25` | Incremento de longitud de contrapeso. |
| `--height M` / `--antenna-height M` | flotante | `8.0` | Altura del punto de alimentación sobre el suelo (compartida por radiador y contrapeso). |
| `--wire-slope-end-height M` | flotante | *(sin establecer = horizontal)* | Altura del extremo lejano del radiador. `0.0` = toca el suelo. Fuerza el modo NEC2. |
| `--cp-end-height M` | flotante | *(sin establecer = al nivel de la altura de la antena)* | Altura del extremo lejano del contrapeso. |
| `--no-counterpoise` | bandera | desactivado | Modela la antena sin contrapeso. |
| `--no-cp-return {ground-rod,coax-stub,reject}` | selección | `ground-rod` | Modelo de trayectoria de retorno de RF cuando no hay contrapeso. |
| `--cp-stub-len M` | flotante | `2.0` | Longitud del cabo de trenza coaxial, usado solo con `--no-cp-return coax-stub`. |
| `--ground-model {sommerfeld,perfect}` | selección | `sommerfeld` | Modelo electromagnético de tierra. |
| `--ground-cond S/M` | flotante | `0.005` | Conductividad del suelo, S/m. |
| `--ground-diel EPS` | flotante | `13.0` | Permitividad relativa del suelo. |
| `--wire-diameter MM` | flotante | `2.0` mm | Diámetro del conductor en milímetros. |
| `--wire-material {...}` | selección | `copper` | Uno de: `copper`, `aluminium`, `aluminum`, `brass`, `silver`, `steel`, `perfect`. |
| `--wire-conductivity S/M` | flotante | *(del material)* | Anulación manual de la conductividad del conductor. |
| `--segs-per-half-wave N` | entero | *(45 barrido / 90 fina)* | Anula tanto las densidades de segmentación de barrido como las de la ejecución final. |
| `--fast` | bandera | desactivado | Barre a densidad gruesa (21 seg/media onda); el ganador de todos modos se recalcula fino. |
| `--converge` | bandera | desactivado | Vuelve a ejecutar el ganador a 2× y 4× la segmentación y reporta cuánto se mueven todavía R/X. |
| `--target-toa DEG` | flotante | `25.0` | Ángulo de elevación (grados) en el que se evalúa la bonificación de ganancia. |
| `--gain-weight W` | flotante | `0.20` | Peso de la puntuación por dB de ganancia en el ángulo de despegue objetivo. |
| `--rerank-top N` | entero | `6` | Número de mejores candidatos resimulados con un patrón de radiación completo para la reclasificación basada en ganancia. |
| `--top-n N` | entero | `20` | Número de candidatos mostrados en el reporte. |
| `--out-txt FILE` | ruta | `optimizer_report.txt` | Nombre del archivo del reporte de texto. |
| `--out-png FILE` | ruta | `optimizer_plot.png` | Nombre del archivo del gráfico de dispersión. |
| `--out-csv FILE` | ruta | `optimizer_best.csv` | Nombre del archivo CSV del mejor candidato. |
| `--out-nec FILE` | ruta | `best_antenna.nec` | Nombre del archivo NEC2 exportado. |
| `--out-radiation FILE` | ruta | `radiation_diagrams.png` | Nombre del archivo PNG del patrón de radiación. |
| `--out-construction FILE` | ruta | `antenna_construction.png` | Nombre del archivo PNG del plano de construcción. |
| `--out-pdf FILE` | ruta | `antenna_brochure.pdf` | Nombre del archivo del folleto PDF. |
| `--retry N` | entero | `0` | Vuelve a ejecutar automáticamente el barrido, desplazando la ventana, hasta N veces si el ganador queda en un borde de la ventana de búsqueda. |
| `--no-interactive` | bandera | desactivado | Falla ante entradas requeridas faltantes en lugar de preguntar interactivamente. |
| `--quiet` / `-q` | bandera | desactivado | Suprime la salida de consola detallada. |
| `--lang {en,es,it}` | selección | autodetectado desde la configuración regional del sistema | Idioma de la interfaz/reporte. |
| `--gui` | bandera | desactivado | Lanza la interfaz gráfica en lugar de ejecutarse desde la línea de comandos. |

### 14.1 Ejemplos de líneas de comandos

**Ejecución más simple posible** (bandas conocidas, valores por defecto para todo lo demás):
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
```

**Bandas personalizadas/desconocidas** (frecuencias obligatorias):
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \
    --wire-len 21.0 --cp-len 5.0
```

**Evaluar tres bandas pero puntuar solo dos de ellas:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \
    --active-bands 40m,20m --wire-len 21.0 --cp-len 5.0
```

**Antena sin contrapeso, usando un cabo coaxial como trayectoria de retorno:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m --wire-len 21.0 \
    --no-counterpoise --no-cp-return coax-stub --cp-stub-len 3.0
```

**Forzar simulación NEC2 completa con una ruta de binario explícita, y verificar convergencia:**
```bash
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0 \
    --mode nec2 --nec2c /usr/local/bin/nec2c --converge
```

---

## 15. Flujos de trabajo típicos, paso a paso

### 15.1 Diseño rápido de primera vez (GUI)

1. Inicie: `python src/Long_Wire_Antenna.py --gui`.
2. En **Banda / Fuente**: escriba sus bandas (p. ej. `40m,20m,15m`), deje Frecuencias en blanco (son bandas reconocidas), configure la Longitud de hilo y la Longitud de contrapeso con su mejor estimación aproximada.
3. En **Física**: deje el Modo de evaluación en `auto`. Si tiene `nec2c` instalado, haga clic en **Auto-detectar** para confirmar que se encuentra.
4. En **Rango de búsqueda**: deje el margen en su valor por defecto de `2.0` m para un primer pase.
5. En **Archivos de salida**: confirme o cambie el directorio de trabajo.
6. En **Ejecutar**: revise la vista previa del comando, haga clic en **Ejecutar**, y observe la consola.
7. Al finalizar, haga clic en **Mostrar reporte** para ver los resultados clasificados, y en **Mostrar patrón de radiación** para ver los gráficos del patrón.

### 15.2 Refinar un diseño que llegó a un límite de búsqueda

Si el reporte advierte que la longitud del hilo (o del contrapeso) "puede necesitar ser más larga/corta" porque el ganador quedó en el borde de la ventana de búsqueda:

- Ya sea que amplíe manualmente `wire-min`/`wire-max` (o `cp-min`/`cp-max`) en la pestaña **Rango de búsqueda** y vuelva a ejecutar, **o**
- Configure **Reintentos máximos** (Sección 7.8) en un número pequeño (p. ej. `2`) antes de la primera ejecución, y deje que el programa desplace la ventana automáticamente.

### 15.3 Obtener un diseño confiable, listo para construir

1. Ejecute una vez en modo `auto`/`empirical` con el ajuste de segmentación `fast` para una visión general rápida del panorama.
2. Una vez que tenga una región prometedora, cambie el **Modo de evaluación** a `nec2` y la **Segmentación** a `fine` (el valor por defecto), y vuelva a ejecutar con una ventana de búsqueda *más estrecha* centrada en la región prometedora — esto le da resultados de alta densidad y físicamente precisos sin pagar el costo total de un barrido fino de NEC2 sobre todo el rango original.
3. Active **Reverificar convergencia** y confirme que el reporte muestra que R se desvía muy por debajo del umbral de alerta de ~3% entre densidades de segmentación.
4. Use el archivo `best_antenna.nec` exportado y el PNG del plano de construcción como sus referencias reales de construcción.

### 15.4 Diseñar la red de adaptación para un diseño de antena terminado

1. Después de una ejecución exitosa, cambie a la pestaña **UnUn / Transmatch** — ya vendrá precargada con las impedancias por banda de la antena ganadora.
2. En la subpestaña **UnUn Toroide**, elija una banda del menú desplegable para inspeccionar una adaptación de banda única, o use la sección **Multibanda** (con **Auto** marcada) para que el programa busque el mejor diseño de UnUn en todas sus bandas a la vez.
3. Alternativamente (o adicionalmente), use la subpestaña **Transmatch** para diseñar una red de adaptación de bobina derivada en lugar de, o en combinación con, el UnUn.

---

## 16. Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| La GUI no inicia; mensaje sobre `tkinter` | Tkinter no está instalado | `sudo apt install python3-tk` (o el equivalente de su distribución), luego reintente. |
| Error sobre un valor `--freqs` faltante | Usó un nombre de banda personalizado/no reconocido sin una frecuencia correspondiente | Complete el campo Frecuencias con un valor en MHz por banda, en el mismo orden que su lista de Banda(s). |
| Los resultados parecen sospechosamente buenos / el signo de la reactancia parece incorrecto | Está en el ajuste de segmentación `fast` (21 seg/media onda) | Cambie a `fine` (por defecto) antes de confiar en cualquier cifra para una construcción real; `fast` es solo de calidad para patrón. |
| "Se solicitó modo NEC2 pero no se encontró binario" (o similar) | `nec2c` no está instalado, o no se puede descubrir automáticamente | Instale `nec2c`, o escriba su ruta completa en el campo **Binario NEC2** de la pestaña Física y/o haga clic en **Auto-detectar**. |
| Los campos relacionados con el contrapeso están en gris y no aceptan entrada | "Usar contrapeso" está desmarcada | Marque la casilla "Usar contrapeso" en la pestaña Rango de búsqueda si desea usar un contrapeso. |
| La sección "Trayectoria de retorno sin contrapeso" está en gris | "Usar contrapeso" está marcada | Esta sección solo aplica cuando *no* hay contrapeso; se activa automáticamente al desmarcar "Usar contrapeso". |
| La longitud de hilo/CP ganadora es igual al mínimo o máximo de la ventana de búsqueda | El verdadero óptimo puede estar fuera del rango buscado | Amplíe `wire-min`/`wire-max` (o `cp-min`/`cp-max`), o configure **Reintentos máximos** > 0 y vuelva a ejecutar. |
| La pestaña UnUn/Transmatch muestra "sin datos cargados" | Ninguna ejecución del optimizador ha producido aún un CSV, o está en una carpeta distinta a la esperada | Ejecute primero el optimizador, o haga clic en el botón **Recargar** en la subpestaña UnUn después de apuntar el directorio de trabajo de Archivos de salida a la carpeta que contiene `optimizer_best.csv`. |
| Una banda de UnUn muestra una ROE sospechosa que no parece corresponder con la reactancia real de la antena | El devanado puede estar operando por encima de su propia frecuencia de autorresonancia (SRF) | Verifique el panel de Resultados en busca de una advertencia de SRF; con **Auto** marcada, la herramienta ya acorta el devanado de referencia para mantener la SRF por encima de su banda más alta con margen, pero un devanado de referencia introducido manualmente aún puede ser demasiado largo. |
| No se producen salidas PNG | `matplotlib` (o, para los diagramas de radiación en particular, `numpy`) no está instalado | `pip install matplotlib numpy`, luego vuelva a ejecutar. |
| El PDF se genera pero una sección de diagrama dice "no disponible" | `Pillow` (`PIL`) no está instalado | `pip install pillow`, luego vuelva a ejecutar — esto no requiere repetir la búsqueda, ya que solo afecta la incrustación de imágenes en el PDF. |
| La vista previa del comando de la GUI muestra algo inesperado | Un campo quedó con texto obsoleto, o el estado de una casilla no coincide con lo que se pretendía | Todo lo que se muestra en el cuadro de vista previa del comando es exactamente lo que se ejecutará — inspecciónelo antes de ejecutar, y ajuste el campo correspondiente. |

---

## 17. Glosario

- **ROE (Relación de Onda Estacionaria) / VSWR:** una medida del desajuste entre la impedancia de la carga y la impedancia característica de la línea. El valor mínimo posible es **1.0** (adaptación ideal); los valores superiores a 1.0 indican mayor desadaptación. No existe un valor de ROE inferior a 1.0.
- **Impedancia en el punto de alimentación (R + jX):** la resistencia (R) y reactancia (X), en ohmios, que la antena presenta a su línea de alimentación en el punto donde se la alimenta.
- **Contrapeso:** un hilo (o conjunto de hilos) que actúa como la "otra mitad" del circuito de la antena en una configuración alimentada por un extremo / no balanceada, en lugar de un plano de tierra completo o un sistema de radiales.
- **NEC2 / `nec2c`:** el Numerical Electromagnetics Code versión 2, un estándar de simulación de antenas por método de momentos ampliamente usado; `nec2c` es una implementación común de código abierto en C del mismo.
- **Segmentación (segs/media onda):** con qué finura un modelo NEC2 subdivide cada hilo para el cálculo; más segmentos generalmente significa más precisión (hasta cierto punto) a costa de tiempo de cómputo.
- **Modelo de tierra de Sommerfeld-Norton:** un modelo de tierra físicamente realista en NEC2 que tiene en cuenta la conductividad y permitividad finitas del suelo, en lugar de asumir un conductor perfecto.
- **Conjunto óptimo de Pareto:** el subconjunto de candidatos para los cuales ningún otro candidato es al menos igual de bueno en todas las métricas puntuadas (aquí, cada banda activa) simultáneamente — el conjunto genuino de compensaciones disponibles.
- **UnUn:** un transformador "no balanceado a no balanceado", típicamente devanado sobre un toroide de ferrita/polvo de hierro, usado para transformar la impedancia del punto de alimentación de una antena hacia la impedancia característica del coaxial.
- **Transmatch:** una red de adaptación sintonizada manual o automáticamente (a menudo una bobina derivada con capacitores), usada entre la línea de alimentación y la antena (o el equipo de la estación) para presentar al transmisor una buena adaptación.
- **Núcleo toroidal:** un núcleo magnético en forma de anillo (ferrita o hierro en polvo) usado para devanar transformadores/chokes de RF; diferentes "mezclas" y tamaños intercambian rango de frecuencia, pérdidas y capacidad de manejo de potencia.
- **Ángulo de despegue (TOA):** en este programa, el ángulo de elevación sobre el horizonte en el que se **evalúa la ganancia**. No significa necesariamente que sea el ángulo de máxima radiación de la antena. Para la reclasificación, el programa toma la mayor ganancia sobre todos los azimuts a esa elevación. Los ángulos bajos suelen ser de interés para ciertos enlaces de larga distancia, pero el TOA óptimo depende de la propagación y del objetivo del enlace.

---

## 18. Apéndice: bandas de radioaficionado conocidas

Los siguientes nombres de banda se reconocen automáticamente, con su frecuencia central incorporada (MHz) — no necesita proporcionar `--freqs` / el campo Frecuencias para ninguna de estas:

| Banda | Frecuencia central (MHz) |
|---|---|
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

Cualquier nombre de banda que no esté en esta lista se trata como **personalizado**, y debe proporcionar su frecuencia central explícitamente.

---

## 19. Apéndice: base de datos de núcleos toroidales (pestaña UnUn)

Núcleos disponibles en el menú desplegable **Núcleo** de la subpestaña UnUn Toroide, con sus especificaciones clave (AL en nH por vuelta², diámetro externo/interno y altura en mm, área de sección transversal efectiva Ae en cm², y un techo aproximado recomendado de densidad de flujo de RF B_sat en mT):

| Núcleo | Material | AL (nH/N²) | DE (mm) | DI (mm) | H (mm) | Ae (cm²) | B_sat (mT, aprox.) |
|---|---|---|---|---|---|---|---|
| FT-114-43 | Ferrita Mezcla 43 | 510.0 | 29.0 | 19.0 | 7.5 | 0.38 | 200 |
| FT-140-43 | Ferrita Mezcla 43 | 885.0 | 35.6 | 22.9 | 12.7 | 0.63 | 200 |
| FT-240-43 | Ferrita Mezcla 43 | 1075.0 | 61.0 | 35.6 | 12.7 | 1.52 | 200 |
| FT-114-31 | Ferrita Mezcla 31 | 800.0 | 29.0 | 19.0 | 7.5 | 0.38 | 200 |
| FT-140-31 | Ferrita Mezcla 31 | 1390.0 | 35.6 | 22.9 | 12.7 | 0.63 | 200 |
| **FT-240-31** (por defecto) | Ferrita Mezcla 31 | 1800.0 | 61.0 | 35.6 | 12.7 | 1.52 | 200 |
| FT-114-52 | Ferrita Mezcla 52 | 175.0 | 29.0 | 19.0 | 7.5 | 0.38 | 200 |
| FT-140-52 | Ferrita Mezcla 52 | 225.0 | 35.6 | 22.9 | 12.7 | 0.63 | 200 |
| FT-240-52 | Ferrita Mezcla 52 | 300.0 | 61.0 | 35.6 | 12.7 | 1.52 | 200 |
| FT-114-61 | Ferrita Mezcla 61 | 79.3 | 29.0 | 19.0 | 7.5 | 0.38 | 236 |
| FT-140-61 | Ferrita Mezcla 61 | 140.0 | 35.6 | 22.9 | 12.7 | 0.63 | 236 |
| FT-240-61 | Ferrita Mezcla 61 | 170.0 | 61.0 | 35.6 | 12.7 | 1.52 | 236 |
| T-130-2 | Polvo de hierro Mezcla 2 | 11.0 | 33.0 | 19.8 | 11.1 | 0.85 | 300 |
| T-200-2 | Polvo de hierro Mezcla 2 | 12.0 | 50.8 | 31.8 | 14.0 | 1.58 | 300 |
| T-130-6 | Polvo de hierro Mezcla 6 | 9.6 | 33.0 | 19.8 | 11.1 | 0.85 | 300 |
| T-200-6 | Polvo de hierro Mezcla 6 | 11.6 | 50.8 | 31.8 | 14.0 | 1.58 | 300 |

> **Nota sobre el modelado de pérdidas del núcleo:** en HF, el límite práctico de potencia de un transformador de ferrita está establecido por el **calentamiento del núcleo**, no por la saturación magnética (el límite de saturación solo se vuelve relevante a frecuencias mucho más bajas para un número de vueltas dado). El modelo de pérdidas de la herramienta usa la permeabilidad compleja de cada material (µ′, µ″) a la frecuencia de trabajo para estimar una resistencia de pérdidas en paralelo, y a partir de ella un límite de potencia continua basado en el área de superficie del núcleo y un aumento de temperatura admisible asumido. Estas cifras son aproximaciones de ingeniería (buenas a aproximadamente un factor de 1.5), no cifras de calidad de hoja de datos — trate las estimaciones de manejo de potencia de la pestaña UnUn como una verificación de coherencia, no como una clasificación certificada.

---

*Fin del manual.*
