# Optimizador de Longitud de Antena NEC2

> **Autor:** LU3VEA &nbsp;·&nbsp; **Licencia:** CC0 1.0 Universal (dominio público)

Herramienta de línea de comandos que busca la **longitud de hilo** y la **longitud de contrapeso** óptimas de una antena de hilo largo alimentada por el extremo, minimizando el ROS agregado en todas las bandas de radioaficionado activas. Controla directamente el simulador electromagnético de código abierto `nec2c`, o recurre a fórmulas empíricas rápidas cuando `nec2c` no está disponible.

---

## Tabla de Contenidos

1. [Teoría](#1-teoría)
   - 1.1 [Antenas de Hilo Largo Alimentadas por el Extremo](#11-antenas-de-hilo-largo-alimentadas-por-el-extremo)
   - 1.2 [El Transformador de Impedancia UnUn](#12-el-transformador-de-impedancia-unun)
   - 1.3 [El Contrapeso](#13-el-contrapeso)
   - 1.4 [Evitación de Resonancias](#14-evitación-de-resonancias)
   - 1.5 [Función de Puntuación](#15-función-de-puntuación)
   - 1.6 [Optimalidad de Pareto](#16-optimalidad-de-pareto)
   - 1.7 [Modo NEC2 vs. Empírico](#17-modo-nec2-vs-empírico)
   - 1.8 [El Mecanismo de Reintento](#18-el-mecanismo-de-reintento)
2. [Requisitos e Instalación](#2-requisitos-e-instalación)
   - 2.1 [Dependencias de Python](#21-dependencias-de-python)
   - 2.2 [Instalación de nec2c](#22-instalación-de-nec2c)
3. [Inicio Rápido](#3-inicio-rápido)
4. [Entrada: El CSV de Bandas](#4-entrada-el-csv-de-bandas)
   - 4.1 [Columnas Obligatorias](#41-columnas-obligatorias)
   - 4.2 [Columnas Opcionales](#42-columnas-opcionales)
   - 4.3 [Ejemplo de CSV](#43-ejemplo-de-csv)
   - 4.4 [CSVs con Localización Europea](#44-csvs-con-localización-europea)
5. [Todas las Opciones de Línea de Comandos](#5-todas-las-opciones-de-línea-de-comandos)
   - 5.1 [Fuente de Banda / Frecuencia](#51-fuente-de-banda--frecuencia)
   - 5.2 [Ventana de Búsqueda](#52-ventana-de-búsqueda)
   - 5.3 [Geometría](#53-geometría)
   - 5.4 [Control de Simulación](#54-control-de-simulación)
   - 5.5 [Reintento y Expansión de Límites](#55-reintento-y-expansión-de-límites)
   - 5.6 [Archivos de Salida](#56-archivos-de-salida)
   - 5.7 [Miscelánea](#57-miscelánea)
6. [Ejemplos de Uso](#6-ejemplos-de-uso)
   - 6.1 [Mínimo: bandas conocidas, sin CSV](#61-mínimo-bandas-conocidas-sin-csv)
   - 6.2 [Con un CSV de bandas](#62-con-un-csv-de-bandas)
   - 6.3 [Anulación de bandas activas](#63-anulación-de-bandas-activas)
   - 6.4 [Bandas personalizadas / desconocidas](#64-bandas-personalizadas--desconocidas)
   - 6.5 [Ajuste fino alrededor de una longitud conocida](#65-ajuste-fino-alrededor-de-una-longitud-conocida)
   - 6.6 [Modo empírico puro (sin nec2c)](#66-modo-empírico-puro-sin-nec2c)
   - 6.7 [Forzar modo NEC2 con binario explícito](#67-forzar-modo-nec2-con-binario-explícito)
   - 6.8 [Expansión automática de límites con --retry](#68-expansión-automática-de-límites-con---retry)
   - 6.9 [Uso no interactivo / con scripts](#69-uso-no-interactivo--con-scripts)
   - 6.10 [Interfaz en español](#610-interfaz-en-español)
7. [Archivos de Salida](#7-archivos-de-salida)
   - 7.1 [optimizer\_report.txt](#71-optimizer_reporttxt)
   - 7.2 [optimizer\_plot.png](#72-optimizer_plotpng)
   - 7.3 [optimizer\_best.csv](#73-optimizer_bestcsv)
   - 7.4 [best\_antenna.nec](#74-best_antennanec)
   - 7.5 [radiation\_diagrams.png](#75-radiation_diagramspng)
8. [Interpretación de la Salida en Consola](#8-interpretación-de-la-salida-en-consola)
   - 8.1 [Advertencias de Límite](#81-advertencias-de-límite)
   - 8.2 [Mensajes de Reintento](#82-mensajes-de-reintento)
   - 8.3 [Tabla de Impedancia](#83-tabla-de-impedancia)
   - 8.4 [Análisis del UnUn](#84-análisis-del-unun)
9. [Geometría de la Antena en NEC2](#9-geometría-de-la-antena-en-nec2)
10. [Tabla de Frecuencias de Bandas Conocidas](#10-tabla-de-frecuencias-de-bandas-conocidas)
11. [Recomendaciones de Flujo de Trabajo](#11-recomendaciones-de-flujo-de-trabajo)
12. [Solución de Problemas](#12-solución-de-problemas)
13. [Licencia](#13-licencia)

---

## 1. Teoría

### 1.1 Antenas de Hilo Largo Alimentadas por el Extremo

Una antena de hilo largo alimentada por el extremo (EFLW, del inglés *end-fed long-wire*) es un conductor único excitado en uno de sus extremos. Su impedancia en el punto de alimentación varía fuertemente con la frecuencia porque la longitud eléctrica relativa a la longitud de onda de operación (λ) cambia. Las resonancias — puntos donde la impedancia es muy baja (máximo de corriente, múltiplos impares de λ/4) o muy alta (máximo de tensión, múltiplos pares de λ/4) — hacen que la impedancia sea difícil de predecir analíticamente.

La impedancia en el punto de alimentación de un hilo largo sobre suelo real es aproximadamente:

```
R ≈ 50 · 80^cos²(π·L/λ½)     (empírica, Ω)
X ≈ 1500 · sin(2π·L/λ½)       (empírica, Ω)
```

donde `L` es la longitud del hilo en metros y `λ½ = c / (2f)` es la semilongitud de onda. Estas fórmulas son el camino rápido de reserva; la simulación real usa NEC2 con un modelo de suelo Sommerfeld-Norton.

### 1.2 El Transformador de Impedancia UnUn

Dado que las antenas alimentadas por el extremo son no balanceadas y su impedancia en el punto de alimentación raramente se acerca a 50 Ω, se inserta entre la línea de alimentación y la antena un transformador llamado **UnUn** (no balanceado a no balanceado, del inglés *unbalanced-to-unbalanced*). Una relación de devanado n:1 transforma la impedancia del lado de la antena `Z_ant = R_ant + jX_ant` al lado del transmisor de la siguiente manera:

```
Z_tx = Z_ant / n     →     R_tx = R_ant/n,  X_tx = X_ant/n
```

Tanto la parte resistiva como la reactiva se dividen por el mismo factor `n`. El ROS resultante respecto a una línea coaxial de 50 Ω es:

```
Γ = |Z_tx - 50| / |Z_tx + 50|
ROS = (1 + Γ) / (1 - Γ)
```

El optimizador recorre todas las relaciones estándar de UnUn (1:1, 1.5:1, 2:1, 3:1, 4:1, 6:1, 9:1, 12:1, 16:1, 25:1, 27:1, 36:1, 49:1, 64:1) más una búsqueda continua por sección áurea entre 1 y 100, para encontrar el transformador que minimice el ROS agregado una vez fijadas las longitudes del hilo y el contrapeso.

Las relaciones prácticas más comunes en radioafición son **4:1** (paso de impedancia moderado), **9:1** (la más popular — adecuada para cargas de ~450 Ω) y **16:1** (adecuada para cargas de ~800 Ω).

### 1.3 El Contrapeso

Un contrapeso (CP) es un hilo corto conectado al lado de tierra del punto de alimentación. Actúa como la mitad faltante del sistema de dipolo y proporciona un camino de retorno de corriente que de otro modo fluiría por la malla del cable coaxial, causando RF en la chaqueta del coaxial y un comportamiento impredecible.

El optimizador admite dos orientaciones de CP:

| Orientación | Descripción |
|---|---|
| `horizontal` | El CP discurre horizontalmente a `--cp-height` metros sobre el suelo, alejándose de la antena en la dirección −x. Un corto hilo vertical de bajada lo conecta al punto de alimentación si es necesario. |
| `vertical` | El CP desciende verticalmente desde el punto de alimentación. Si es más largo que la bajada vertical disponible (altura del hilo − altura del CP), el resto se dobla horizontalmente, formando una forma de L. |
| `both` (por defecto) | Ambas orientaciones se simulan para cada par candidato; se conserva la que da la puntuación combinada más baja. |

Una longitud de CP cercana a un **múltiplo impar de λ/4** (1×, 3×, 5× …) presenta una impedancia baja en el punto de alimentación, lo cual es ideal. Los múltiplos pares (λ/2, λ, …) presentan alta impedancia y se evitan. El optimizador asigna un pequeño bono de resonancia de CP para recompensar los múltiplos impares, pero este bono no puede anular un ROS deficiente.

### 1.4 Evitación de Resonancias

En una antena multibanda, una resonancia en cualquier banda individual provoca que la impedancia suba o baje bruscamente y que el ROS se dispare. La **puntuación de evitación** mide cuán lejos se encuentra la longitud del hilo de la resonancia de λ/4 más cercana en cada banda:

```
λ/4_n  =  n × c / (4f),  n = 1, 2, 3, …

evitación(banda) = min(frac, 1 − frac)  donde frac = (L / λ/4) mod 1
                   limitado a [0, 0.25]
```

Un valor de **0.25** (el máximo posible) significa que el hilo está exactamente a mitad de camino entre dos resonancias de λ/4 adyacentes en esa banda — ideal. Valores por debajo de **0.06** indican riesgo de resonancia. El optimizador calcula esto sobre **todas** las bandas del CSV (incluidas las inactivas) para que incluso las bandas no puntuadas por ROS influyan en el término de evitación.

| Puntuación | Calificación |
|---|---|
| ≥ 0.20 | ★★★ EXCELENTE |
| ≥ 0.12 | ★★  BUENO |
| ≥ 0.06 | ★   MARGINAL |
| < 0.06 | ✗   RIESGO DE RESONANCIA |

### 1.5 Función de Puntuación

Cada par candidato `(longitud_hilo, longitud_cp)` recibe una **puntuación combinada** (menor = mejor):

```
puntuación_combinada = penalización_ros_media
                     + 1.5 × penalización_ros_peor
                     − 0.5 × evitación_media_activa
                     − 0.1 × bono_cuarto_lambda_cp_medio
```

La penalización de ROS para una sola banda es una función lineal por tramos / logarítmica:

```
penalización_ros(v) =
    0                         si v ≤ 1.5   (excelente)
    (v − 1.5) / 1.5           si 1.5 < v ≤ 3.0  (rampa lineal)
    1 + (v − 3.0) / 1.5       si 3.0 < v ≤ 6.0  (rampa más pronunciada)
    3 + log10(v/6) × 5        si v > 6.0   (logarítmica)
```

El término `1.5 × penalización_ros_peor` penaliza los candidatos que son perfectos en todas las bandas excepto en una — fomentando un rendimiento equilibrado. Los términos de evitación y bono de CP son intencionalmente pequeños (0.5× y 0.1×) para que solo desempaten entre candidatos igualmente similares en lugar de anular una adaptación de ROS genuinamente deficiente.

### 1.6 Optimalidad de Pareto

Dado que hay dos objetivos en juego — minimizar la penalización de ROS (`score_vswr_raw`) y maximizar la evitación de resonancias (`score_avoidance_active`) — puede no existir un único punto óptimo. Un candidato A **domina** al candidato B si A es al menos igual de bueno que B en ambos objetivos y estrictamente mejor en al menos uno. El **frente de Pareto** es el conjunto de candidatos no dominados por ningún otro.

El informe muestra tanto el ranking por puntuación combinada (para una recomendación única definitiva) como el frente de Pareto completo (para usuarios que deseen sacrificar ligeramente el ROS a favor de una mejor evitación de resonancias, o viceversa).

### 1.7 Modo NEC2 vs. Empírico

| Característica | Modo NEC2 | Modo empírico |
|---|---|---|
| **Precisión** | Simulación electromagnética completa mediante suelo Sommerfeld-Norton | Fórmulas de forma cerrada (± 20–40% cerca de resonancias) |
| **Velocidad** | ~0.5–5 s por candidato × tamaño de la cuadrícula | < 1 ms por candidato |
| **Modelo de suelo** | Conductividad + permitividad (configurable) | Ninguno |
| **Diagrama de radiación** | Barrido RP completo, diagramas de elevación y azimut | No disponible |
| **Tipo de CP** | Ambas orientaciones simuladas, se selecciona la mejor | Orientación única fija |
| **Requisito** | Binario `nec2c` | Ninguno |

La herramienta selecciona automáticamente el modo NEC2 si se encuentra `nec2c`, y recurre al modo empírico en caso contrario (modo `auto`). Use `--mode nec2` para requerir NEC2 y abortar si falta el binario; use `--mode empirical` para forzar el modo empírico incluso cuando `nec2c` está presente.

**Referencia de fórmulas empíricas:**
```
R = 50 × 80^cos²(π × L/λ½)
X = 1500 × sin(2π × L/λ½)
```

### 1.8 El Mecanismo de Reintento

Cuando el mejor candidato se sitúa en el borde de la ventana de búsqueda, el verdadero óptimo probablemente se encuentra fuera de ella. El optimizador detecta esto automáticamente y, si se ha establecido `--retry N`, vuelve a ejecutar el barrido hasta N veces:

- **Mejor en el máximo** → la ventana se desplaza **hacia arriba**: nuevo rango = `[mejor, mejor + margen]`
- **Mejor en el mínimo** → la ventana se desplaza **hacia abajo**: nuevo rango = `[mejor − margen, mejor]`

Los límites del hilo y el contrapeso se comprueban y desplazan de forma independiente en el mismo reintento. El bucle se detiene antes si:
- Ningún límite es alcanzado (convergencia), o
- El nuevo barrido no produce ninguna mejora sobre el mejor actual.

---

## 2. Requisitos e Instalación

### 2.1 Dependencias de Python

Se requiere Python 3.8+. El script usa únicamente la biblioteca estándar para su función principal. Los paquetes opcionales habilitan una salida más rica:

```bash
pip install colorama tabulate matplotlib
```

| Paquete | Efecto si falta |
|---|---|
| `colorama` | La salida de consola no tiene color (funciona en todas las plataformas) |
| `tabulate` | La tabla del informe usa ASCII simple en lugar de caracteres de dibujo Unicode |
| `matplotlib` | No se generan gráficos PNG |

Instalar todo de una vez:
```bash
pip install colorama tabulate matplotlib
```

O instale solo los paquetes que necesite. El script se degrada elegantemente en todos los casos.

### 2.2 Instalación de nec2c

`nec2c` es el puerto en C del código Fortran original NEC-2.

**Debian / Ubuntu:**
```bash
sudo apt update && sudo apt install nec2c
```

**macOS (Homebrew):**
```bash
brew install nec2c
```

**Desde el código fuente:**
```bash
git clone https://github.com/KJ4IPS/nec2c.git
cd nec2c && ./configure && make && sudo make install
```

**Verificación:**
```bash
nec2c --version
# o simplemente:
which nec2c
```

**Orden de descubrimiento del binario** (el script los prueba en esta secuencia):
1. Flag de CLI `--nec2c /ruta/explícita`
2. Variable de entorno `$NEC2C`
3. `nec2c` y `nec2c-mpich` en `$PATH`
4. Rutas predefinidas: `/usr/bin/nec2c`, `/usr/local/bin/nec2c`, `/opt/nec2c/bin/nec2c`, `/opt/homebrew/bin/nec2c`, etc.
5. Solicitud interactiva (a menos que se use `--no-interactive`)

Si ninguno de los anteriores tiene éxito, el script recurre al modo empírico (o termina si se especificó `--mode nec2`).

---

## 3. Inicio Rápido

```bash
# Clonar o descargar
git clone https://example.com/nec2_length_optimizer.git
cd nec2_length_optimizer

# Instalar dependencias opcionales
pip install colorama tabulate matplotlib

# Ejecutar con bandas de radioaficionado conocidas, sin CSV
python nec2_length_optimizer.py \
    --bands 40m,20m,15m,10m \
    --wire-len 21.0 \
    --cp-len 5.0 \
    --unun 9

# Ejecutar con un CSV de bandas para control total
python nec2_length_optimizer.py --csv mis_bandas.csv
```

En segundos (empírico) o minutos (NEC2, según el tamaño de la cuadrícula), verá:

```
★ MEJOR CANDIDATO:  wire = 21.250 m   cp = 5.500 m   (horizontal)
    Puntuación comb.= 0.4821
    Penalización ROS= 0.3104
    Evitación media = 0.1823

  Impedancia — lado antena y lado transmisor (UnUn 9:1):
      Banda     MHz    R_ant    X_ant   |Z_ant|    R_tx    X_tx   |Z_tx|    ROS       Src
      ────────────────────────────────────────────────────────────────────────────────────
        40m   7.100    312.4   +154.8    349.1   34.71  +17.20   38.79   1.64   NEC2-H
        20m  14.175    891.2   −230.5    921.5   99.02  −25.61  102.27   2.14   NEC2-H
        15m  21.225    124.8   −315.6    339.3   13.87  −35.07   37.72   3.87   NEC2-H
        10m  28.500   2145.3   +890.2   2322.1  238.37  +98.91  258.05   5.41   NEC2-H
```

Se escriben cuatro archivos de salida: `optimizer_report.txt`, `optimizer_plot.png`, `optimizer_best.csv`, `best_antenna.nec`.

---

## 4. Entrada: El CSV de Bandas

El CSV es el método de entrada más potente. Permite definir cada banda con su frecuencia central exacta, si está activa para la puntuación de ROS, las longitudes iniciales del hilo y el CP, las alturas de la antena y la relación UnUn — todo en un solo lugar.

### 4.1 Columnas Obligatorias

| Columna | Tipo | Descripción |
|---|---|---|
| `band` | cadena | Nombre de la banda, p. ej. `40m`, `20m`, `custom1` |
| `freq_mhz` | flotante | Frecuencia central en MHz |
| `active` | SÍ/NO | ¿Incluir en la puntuación de ROS? (`YES`, `Y`, `TRUE`, `1`, `ACTIVE` se aceptan) |
| `lambda_half_m` | flotante | Semilongitud de onda en metros (`c / (2f)`) |
| `wire_len_m` | flotante | Longitud inicial del hilo (establece el centro de la ventana de búsqueda) |
| `r_wire_ohm` | flotante | Resistencia en el punto de alimentación (empírica o medida). Poner 0 para que el script la calcule. |
| `x_wire_ohm` | flotante | Reactancia en el punto de alimentación (empírica o medida). Poner 0 para que el script la calcule. |
| `vswr_no_cp` | flotante | ROS sin contrapeso (poner 0 para que se calcule automáticamente) |

### 4.2 Columnas Opcionales

| Columna | Tipo | Descripción |
|---|---|---|
| `lambda_qtr_m` | flotante | Cuarto de longitud de onda en metros |
| `L_over_lhalf` | flotante | Relación longitud de hilo / λ½ |
| `vswr_with_cp` | flotante | ROS con contrapeso (solo referencia) |
| `Z_eff_ohm` | flotante | Magnitud de la impedancia efectiva en el punto de alimentación (referencia) |
| `Zcp_ohm` | flotante | Impedancia serie del contrapeso (referencia) |
| `unun_ratio` | flotante | Relación UnUn para esta fila de banda (se usa un único valor para todas) |
| `avoidance_score` | flotante | Puntuación de evitación precalculada (anula el valor calculado si es distinto de cero) |
| `quality_rating` | cadena | Etiqueta de calidad precalculada (solo referencia) |
| `cp_len_m` | flotante | Longitud inicial del contrapeso (establece el centro de la ventana de búsqueda del CP) |
| `cp_height_m` | flotante | Altura del contrapeso sobre el suelo en metros |
| `wire_height_m` | flotante | Altura del hilo de antena sobre el suelo en metros |
| `num_radials` | entero | Número de radiales de contrapeso (solo referencia; la simulación usa 1) |

Los nombres de columna se reconocen **sin distinción de mayúsculas/minúsculas** y se ignoran los espacios iniciales y finales.

### 4.3 Ejemplo de CSV

```csv
band,freq_mhz,active,lambda_half_m,wire_len_m,r_wire_ohm,x_wire_ohm,vswr_no_cp,unun_ratio,cp_len_m,cp_height_m,wire_height_m
160m,1.850,NO,81.025,21.0,0,0,0,9,5.0,0.5,8.0
80m,3.650,YES,41.067,21.0,0,0,0,9,5.0,0.5,8.0
40m,7.100,YES,21.112,21.0,0,0,0,9,5.0,0.5,8.0
30m,10.125,NO,14.793,21.0,0,0,0,9,5.0,0.5,8.0
20m,14.175,YES,10.567,21.0,0,0,0,9,5.0,0.5,8.0
17m,18.118,NO,8.276,21.0,0,0,0,9,5.0,0.5,8.0
15m,21.225,YES,7.066,21.0,0,0,0,9,5.0,0.5,8.0
12m,24.940,NO,6.011,21.0,0,0,0,9,5.0,0.5,8.0
10m,28.500,YES,5.260,21.0,0,0,0,9,5.0,0.5,8.0
6m,50.200,NO,2.985,21.0,0,0,0,9,5.0,0.5,8.0
```

> **Nota:** Establecer `r_wire_ohm`, `x_wire_ohm` y `vswr_no_cp` en `0` indica al script que los calcule con las fórmulas empíricas. Si dispone de valores medidos o derivados de NEC2, proporciónelos — el script no sobreescribirá entradas distintas de cero.

### 4.4 CSVs con Localización Europea

Si su CSV usa punto y coma como separador y coma como separador decimal (habitual en Excel cuando la configuración regional del sistema está en español, alemán, francés, etc.), el script lo detecta automáticamente y normaliza el archivo antes de procesarlo:

```
  Formato CSV   : Localización europea (sep ';', dec ',') — normalizado
```

No se necesita ninguna conversión manual.

---

## 5. Todas las Opciones de Línea de Comandos

Ejecute `python nec2_length_optimizer.py --help` para ver la lista completa. A continuación se presenta una referencia estructurada.

### 5.1 Fuente de Banda / Frecuencia

| Flag | Por defecto | Descripción |
|---|---|---|
| `--csv ARCHIVO` | — | Archivo CSV de bandas. Si se proporciona, todos los datos de banda/frecuencia/altura/UnUn se leen de él. |
| `--bands NOMBRES` | — | Nombres de bandas separados por comas cuando no se usa CSV. Ej.: `40m,20m,15m`. |
| `--freqs MHZ` | auto | Frecuencias centrales en MHz separadas por comas, una por entrada de `--bands`. Opcional cuando todos los nombres están en la tabla de frecuencias integrada. Obligatorio para nombres no reconocidos. |
| `--active-bands BANDAS` | todas | Anula qué bandas se puntúan para ROS. Ej.: `40m,20m` para puntuar solo esas dos independientemente de la columna `active` del CSV. |
| `--unun RELACION` | del CSV | Relación UnUn, p. ej. `9` para 9:1. Se lee del CSV si está presente; de lo contrario se solicita interactivamente. |

### 5.2 Ventana de Búsqueda

| Flag | Por defecto | Descripción |
|---|---|---|
| `--wire-len M` | del CSV | Longitud inicial del hilo en metros. Establece el centro de la ventana de búsqueda cuando no se dan `--wire-min`/`--wire-max`. |
| `--cp-len M` | del CSV | Longitud inicial del CP en metros. Establece el centro de la ventana de búsqueda. |
| `--margin M` | `2.0` | Radio de búsqueda (metros) sumado/restado a las longitudes iniciales para formar la ventana predeterminada. Se ignora cuando se dan `--wire-min`/`--wire-max` explícitos. |
| `--wire-min M` | auto | Longitud mínima absoluta del hilo a buscar. Anula `--margin` para el límite inferior. |
| `--wire-max M` | auto | Longitud máxima absoluta del hilo a buscar. Anula `--margin` para el límite superior. |
| `--wire-step M` | `0.25` | Tamaño del paso de la cuadrícula para la longitud del hilo (metros). |
| `--cp-min M` | auto | Longitud mínima absoluta del CP a buscar. |
| `--cp-max M` | auto | Longitud máxima absoluta del CP a buscar. |
| `--cp-step M` | `0.25` | Tamaño del paso de la cuadrícula para la longitud del CP (metros). |

**Cómo se construye la ventana de búsqueda:**

```
wire_min = max(1.0, wire_ref − margen)
wire_max = wire_ref + margen
```

donde `wire_ref` proviene de `--wire-len`, o de la media de la columna `wire_len_m` del CSV. La misma lógica se aplica al CP.

### 5.3 Geometría

| Flag | Por defecto | Descripción |
|---|---|---|
| `--wire-height M` | del CSV o `8.0` | Altura del hilo de antena sobre el suelo en metros. |
| `--cp-height M` | del CSV o `0.5` | Altura del contrapeso sobre el suelo en metros. |
| `--cp-type` | `both` | Orientación del contrapeso: `horizontal`, `vertical` o `both`. |
| `--ground-cond S/M` | `0.005` | Conductividad del suelo en S/m. Valores típicos: muy pobre = 0.001, medio = 0.005, bueno = 0.01, agua de mar = 4.0. |
| `--ground-diel EPS` | `13.0` | Permitividad relativa del suelo. Valores típicos: arena seca = 3, medio = 13, suelo rico = 20. |

### 5.4 Control de Simulación

| Flag | Por defecto | Descripción |
|---|---|---|
| `--mode MODO` | `auto` | `auto` (usa NEC2 si está disponible, si no empírico), `nec2` (requiere NEC2), `empirical` (fuerza empírico). |
| `--nec2c RUTA` | auto | Ruta explícita al binario `nec2c`. Anula el descubrimiento automático. |

### 5.5 Reintento y Expansión de Límites

| Flag | Por defecto | Descripción |
|---|---|---|
| `--retry N` | `0` | Si el mejor candidato está en un límite de búsqueda, vuelve a ejecutar el barrido hasta N veces, desplazando la ventana en la dirección indicada por la advertencia. `0` deshabilita el reintento automático. |

### 5.6 Archivos de Salida

| Flag | Por defecto | Descripción |
|---|---|---|
| `--out-txt ARCHIVO` | `optimizer_report.txt` | Informe de texto completo con ranking. |
| `--out-png ARCHIVO` | `optimizer_plot.png` | Mapa de calor de puntuación + gráficos de barras de ROS por banda. |
| `--out-csv ARCHIVO` | `optimizer_best.csv` | Mejor candidato en el mismo formato CSV que la entrada, listo para usar de nuevo con `--csv`. |
| `--out-nec ARCHIVO` | `best_antenna.nec` | Deck de entrada NEC2 listo para usar para la mejor geometría, con tarjetas de diagrama de radiación para todas las bandas activas. |
| `--out-radiation ARCHIVO` | `radiation_diagrams.png` | Diagramas de radiación en elevación y azimut por banda (solo modo NEC2). |
| `--top-n N` | `20` | Número de candidatos principales a mostrar en el informe. |

### 5.7 Miscelánea

| Flag | Por defecto | Descripción |
|---|---|---|
| `--lang IDIOMA` | auto | Idioma de la interfaz: `en` (inglés) o `es` (español). Se detecta automáticamente desde la configuración regional del sistema si no se establece. |
| `--no-interactive` | desactivado | No solicitar entradas faltantes; salir con error en su lugar. Adecuado para uso automatizado con scripts. |
| `--quiet` / `-q` | desactivado | Suprimir la salida de progreso durante el barrido. |

---

## 6. Ejemplos de Uso

### 6.1 Mínimo: bandas conocidas, sin CSV

La invocación más simple. Las frecuencias de las bandas se resuelven automáticamente desde la tabla integrada. Se construye una ventana de búsqueda de ±2 m alrededor de las longitudes de hilo y CP proporcionadas.

```bash
python nec2_length_optimizer.py \
    --bands 80m,40m,20m,15m,10m \
    --wire-len 21.0 \
    --cp-len 5.0 \
    --unun 9
```

Salida de consola esperada (resumida):
```
  Frecuencias   : resueltas automáticamente de los nombres de banda
      80m → 3.65 MHz
      40m → 7.1 MHz
      20m → 14.175 MHz
      15m → 21.225 MHz
      10m → 28.5 MHz
  Margen búsqueda: ±2.0 m alrededor del hilo --wire-len de 21.000 m
  --wire-min    : 19.0 m
  --wire-max    : 23.0 m
  Tamaño grilla : 289 candidatos
```

### 6.2 Con un CSV de bandas

```bash
python nec2_length_optimizer.py --csv mis_bandas.csv
```

Todos los datos de bandas, la relación UnUn y las longitudes iniciales se leen del CSV. La columna `active` controla qué bandas entran en el objetivo de ROS.

### 6.3 Anulación de bandas activas

Puntuar solo 40 m y 20 m aunque el CSV también tenga definidas 80 m, 15 m y 10 m:

```bash
python nec2_length_optimizer.py \
    --csv mis_bandas.csv \
    --active-bands 40m,20m
```

Las bandas no incluidas en `--active-bands` siguen apareciendo en el cálculo de evitación pero no afectan al término de ROS.

### 6.4 Bandas personalizadas / desconocidas

Si no trabaja en las bandas de radioaficionado, debe proporcionar `--freqs`:

```bash
python nec2_length_optimizer.py \
    --bands CB,Marina,Aviacion \
    --freqs 27.185,156.800,121.500 \
    --wire-len 5.5 \
    --cp-len 2.0 \
    --unun 4 \
    --mode empirical
```

### 6.5 Ajuste fino alrededor de una longitud conocida

Después de que una primera ejecución encuentre el mejor resultado en 21.25 m / 5.50 m, refine con una cuadrícula más fina sobre una ventana más estrecha:

```bash
python nec2_length_optimizer.py \
    --csv mis_bandas.csv \
    --wire-min 20.5 \
    --wire-max 22.0 \
    --wire-step 0.05 \
    --cp-min 5.0 \
    --cp-max 6.0 \
    --cp-step 0.05 \
    --out-txt informe_refinado.txt \
    --out-png grafico_refinado.png
```

El paso más pequeño (0.05 m frente al predeterminado de 0.25 m) genera 30×30 = 900 candidatos, evaluando el vecindario con resolución de 5 cm.

### 6.6 Modo empírico puro (sin nec2c)

Útil para un primer paso rápido o cuando `nec2c` no está instalado:

```bash
python nec2_length_optimizer.py \
    --bands 40m,20m,15m \
    --wire-len 21.0 \
    --cp-len 5.0 \
    --unun 9 \
    --mode empirical \
    --wire-step 0.1 \
    --cp-step 0.1
```

Con pasos de 0.1 m sobre una ventana de ±2 m, se evalúan 41 × 41 = 1681 candidatos en menos de un segundo.

### 6.7 Forzar modo NEC2 con binario explícito

```bash
python nec2_length_optimizer.py \
    --csv mis_bandas.csv \
    --mode nec2 \
    --nec2c /opt/nec2c/bin/nec2c \
    --cp-type both \
    --wire-height 10.0 \
    --cp-height 1.0 \
    --ground-cond 0.010 \
    --ground-diel 20.0
```

Esto simula tanto el CP horizontal como el vertical para cada candidato sobre suelo rico (σ = 0.010 S/m, εᵣ = 20) con el hilo de antena a 10 m.

### 6.8 Expansión automática de límites con --retry

Si no conoce una buena longitud de partida y quiere que el optimizador explore hacia afuera automáticamente:

```bash
python nec2_length_optimizer.py \
    --bands 80m,40m,20m,15m,10m \
    --wire-len 20.0 \
    --cp-len 5.0 \
    --unun 9 \
    --margin 3.0 \
    --retry 4
```

Si el primer paso encuentra su mejor resultado en el límite de 23 m, el segundo paso busca entre 23 y 26 m; si ese mejor resultado está de nuevo en 26 m, el tercer paso busca entre 26 y 29 m, y así sucesivamente hasta 4 reintentos. Cada reintento estrecha la nueva ventana a `[mejor, mejor+margen]` (para "puede ser más largo") o `[mejor−margen, mejor]` (para "puede ser más corto") y se detiene en cuanto no se encuentra ninguna mejora.

Salida de consola durante el reintento:
```
  🔁  --retry: límite de hilo en máximo — expandiendo límite superior a 26.000 m (reintento 2/4)
  ✔  --retry: nuevo mejor tras reintento — hilo = 25.250 m   cp = 5.500 m   puntuación = 0.4102
  ✔  --retry: límite ya no alcanzado — convergido tras 2 reintento(s).
```

### 6.9 Uso no interactivo / con scripts

Para usar en scripts de shell, tareas cron o pipelines de CI donde no hay terminal para entrada interactiva:

```bash
python nec2_length_optimizer.py \
    --csv mis_bandas.csv \
    --no-interactive \
    --quiet \
    --out-txt /resultados/informe.txt \
    --out-csv /resultados/mejor.csv \
    --out-png /resultados/grafico.png
```

`--no-interactive` hace que el script salga con un código no cero en lugar de solicitar entrada si no se encuentra `nec2c`, falta el UnUn u otras entradas están ausentes. `--quiet` suprime el contador de progreso durante el barrido.

### 6.10 Interfaz en español

El idioma se detecta automáticamente desde la configuración regional del sistema. Para forzarlo explícitamente:

```bash
python nec2_length_optimizer.py --csv bandas.csv --lang es
```

Todos los mensajes de consola, encabezados del informe y etiquetas de los gráficos aparecerán en español.

---

## 7. Archivos de Salida

### 7.1 optimizer_report.txt

Archivo de texto plano (sin códigos de color ANSI) que contiene:

- **Parámetros de ejecución:** modo, relación UnUn, rangos de búsqueda de hilo y CP, bandas activas, total de candidatos evaluados.
- **Tabla de los N mejores candidatos:** longitud del hilo, longitud del CP, orientación del CP, puntuación combinada, penalización de ROS, puntuación de evitación y ROS por banda.
- **Frente Pareto-óptimo:** todos los candidatos no dominados en (penalización de ROS, evitación).
- **Desglose detallado del mejor candidato:** impedancia por banda tanto en el lado de la antena como en el lado del transmisor (post-UnUn), etiqueta de ROS, calificación de evitación.
- **Advertencias de límite** (si corresponde).
- **Análisis UnUn:** relación actual vs. mejor estándar vs. relación de óptimo continuo, UnUn óptimo por banda.
- **Notas teóricas** que explican la puntuación, la métrica de evitación, las fórmulas empíricas y los próximos pasos.

### 7.2 optimizer_plot.png

Figura PNG multipanel (requiere `matplotlib`):

- **Mapa de calor de puntuación:** cuadrícula 2D de todos los candidatos evaluados con colores según la puntuación combinada; frente de Pareto resaltado; mejor candidato marcado con una estrella.
- **Gráficos de barras de ROS por banda:** una barra por banda activa en el mejor candidato, con color verde (≤ 1.5), amarillo (≤ 3) o rojo (> 3).
- **Diagrama de dispersión del espacio de Pareto:** penalización de ROS vs. evitación, mostrando la frontera de compromiso.

### 7.3 optimizer_best.csv

El mejor candidato escrito en el mismo formato que el CSV de entrada, con la longitud óptima del hilo, la longitud del CP y la relación UnUn ya completadas. Puede usarse directamente como `--csv` para una búsqueda refinada o pasarlo a herramientas de análisis complementarias.

### 7.4 best_antenna.nec

Un deck de entrada NEC2 completo para la mejor geometría, listo para abrir en `xnec2c`, `4nec2` o cualquier interfaz gráfica NEC2. Incluye:

- Tarjetas de geometría `GW` para el hilo de antena y el contrapeso.
- Tarjeta de suelo `GN` con la conductividad y permitividad configuradas.
- Tarjeta de excitación `EX` en el punto de alimentación (segmento 1 del hilo 1).
- Tarjetas `FR` + `XQ` + `RP` para cada banda activa, generando tanto la salida de impedancia como la del diagrama de radiación.
- Tarjetas de comentario `CM` que registran la longitud del hilo, la longitud del CP, el tipo y las alturas.

### 7.5 radiation_diagrams.png

Disponible **solo en modo NEC2**. Para el mejor candidato, se ejecuta un barrido completo del diagrama de radiación (18 elevaciones × 72 acimuts por banda). La figura muestra una fila por banda activa:

- **Panel izquierdo:** Diagrama de elevación (de −90° a +90° en forma polar). Las líneas rojas discontinuas indican el ángulo de despegue.
- **Panel derecho:** Diagrama de azimut en la elevación de ganancia máxima.
- Los títulos incluyen la banda, la frecuencia, el ROS, la ganancia máxima (dBi) y el ángulo de despegue (TOA).

---

## 8. Interpretación de la Salida en Consola

### 8.1 Advertencias de Límite

Si el mejor candidato cae en el borde de la ventana de búsqueda, se imprime una advertencia en amarillo **y** se escribe en el informe:

```
  ⚠  LONGITUD DE HILO en el máximo de búsqueda (23.000 m).  3/5 mejores candidatos tocaron este límite.
     El óptimo real puede ser mayor. Re-ejecute con --wire-max mayor o aumente --margin.
```

La fracción `3/5` cuenta cuántos de los 5 candidatos mejor clasificados también alcanzan ese límite. Si los 5 lo alcanzan, el óptimo probablemente está fuera de la ventana. Si solo 1 lo alcanza, la advertencia es menos urgente.

Las cuatro advertencias posibles son:

| Advertencia | Significado | Acción |
|---|---|---|
| HILO en **máximo** de búsqueda | El óptimo real puede ser **más largo** | Aumentar `--wire-max` o `--margin`; usar `--retry` |
| HILO en **mínimo** de búsqueda | El óptimo real puede ser **más corto** | Reducir `--wire-min` o `--margin`; usar `--retry` |
| CP en **máximo** de búsqueda | El óptimo real puede ser **más largo** | Aumentar `--cp-max` o `--margin`; usar `--retry` |
| CP en **mínimo** de búsqueda | El óptimo real puede ser **más corto** | Reducir `--cp-min` o `--margin`; usar `--retry` |

### 8.2 Mensajes de Reintento

Cuando `--retry N` está activo, el bucle de reintento imprime el progreso en cian/amarillo/verde:

```
  🔁  --retry: límite de hilo en máximo — expandiendo límite superior a 26.000 m (reintento 1/3)
  ✔  --retry: nuevo mejor tras reintento — hilo = 25.250 m   cp = 5.500 m   puntuación = 0.4102
  🔁  --retry: límite de hilo en máximo — expandiendo límite superior a 28.000 m (reintento 2/3)
  ℹ  --retry: sin mejora encontrada — manteniendo mejor previo (hilo = 25.250 m, cp = 5.500 m).
```

El bucle se detiene en cuanto aparece `sin mejora encontrada` (la nueva ventana es peor o equivalente) o el límite ya no es alcanzado (`convergido`).

### 8.3 Tabla de Impedancia

```
  Impedancia — lado antena y lado transmisor (UnUn 9:1):
      Banda     MHz    R_ant    X_ant   |Z_ant|    R_tx    X_tx   |Z_tx|    ROS       Src
      ────────────────────────────────────────────────────────────────────────────────────
        40m   7.100    312.4   +154.8    349.1   34.71  +17.20   38.79   1.64   NEC2-H
        20m  14.175    891.2   −230.5    921.5   99.02  −25.61  102.27   2.14   NEC2-H
        15m  21.225    124.8   −315.6    339.3   13.87  −35.07   37.72   3.87   NEC2-H
        10m  28.500   2145.3   +890.2   2322.1  238.37  +98.91  258.05   5.41   NEC2-H
```

- **R_ant / X_ant:** Impedancia en el punto de alimentación del lado de la antena en Ω (de NEC2 o fórmula empírica).
- **|Z_ant|:** Magnitud de la impedancia de antena.
- **R_tx / X_tx:** Impedancia del lado del transmisor tras el UnUn (ambas divididas por la relación UnUn n).
- **|Z_tx|:** Magnitud de la impedancia del lado del transmisor.
- **ROS:** ROS referido a 50 Ω en el lado del transmisor. Verde (≤ 1.5), amarillo (≤ 3), rojo (> 3).
- **Src:** Origen de los datos de impedancia: `NEC2-H` (simulación con CP horizontal), `NEC2-V` (CP vertical) o `empirical` (empírico).

### 8.4 Análisis del UnUn

Tras identificar la mejor geometría, se realiza un barrido de UnUn:

```
  Análisis UnUn (mejor geometría: 21.250 m / 5.500 m):
    Relación actual  : 9:1  (penalización ROS agregada 1.3842)
    Mejor estándar   : 9:1  (penalización ROS agregada 1.3842)
    Óptimo continuo  : 8.73:1  (penalización ROS agregada 1.3719)
    → La relación actual 9:1 es óptima entre las estándar.
```

Si la relación estándar óptima difiere significativamente de la que está usando, se imprime una recomendación para cambiarla. También se tabulan las relaciones óptimas por banda.

---

## 9. Geometría de la Antena en NEC2

El deck NEC2 modela la siguiente geometría:

```
                          wire_height_m
                 ─────────────────────────────── Hilo 1 (antena)
                 punto de alimentación (0,0,wire_height_m)
                 |
                 | hilo de bajada (si cp_height < wire_height, solo CP horizontal)
                 |
  cp_height_m    ──────────── Hilo 2/3 (contrapeso, horizontal o en forma de L)
```

Para un contrapeso **horizontal**:
- Hilo 1: `(0,0,h) → (L,0,h)` — la antena, longitud `wire_len_m`, a la altura `wire_height_m`.
- Hilo 2 (bajada): `(0,0,h) → (0,0,cp_h)` — bajada vertical desde el punto de alimentación hasta la altura del CP (se omite si cp_height ≥ wire_height).
- Hilo 3 (CP): `(0,0,cp_h) → (−cp_len,0,cp_h)` — CP horizontal, yendo en la dirección −x.

Para un contrapeso **vertical**:
- Hilo 1: misma antena.
- Hilo 2: `(0,0,h) → (0,0,inferior)` — bajada vertical, donde `inferior = max(cp_height, wire_height − cp_len)`.
- Hilo 3 (si es necesario): resto horizontal en la parte inferior, yendo en la dirección −x.

La excitación (tarjeta `EX`) se coloca en el segmento 1 del hilo 1 — el primer segmento en el extremo del punto de alimentación `(0,0,wire_height_m)`.

El modelo de suelo usa `GN 2` (suelo real Sommerfeld-Norton) con la conductividad y permitividad configuradas.

---

## 10. Tabla de Frecuencias de Bandas Conocidas

Cuando se usa `--bands` sin `--freqs`, se emplean estas frecuencias centrales de la UIT:

| Banda | Frecuencia (MHz) | Banda | Frecuencia (MHz) |
|---|---|---|---|
| 2200m | 0.1365 | 17m | 18.118 |
| 630m | 0.475 | 15m | 21.225 |
| 160m | 1.850 | 12m | 24.940 |
| 80m | 3.650 | 10m | 28.500 |
| 60m | 5.350 | 6m | 50.200 |
| 40m | 7.100 | 4m | 70.200 |
| 30m | 10.125 | 2m | 144.200 |
| 20m | 14.175 | 70cm | 432.100 |
| | | 23cm | 1296.200 |

Los nombres de banda se reconocen sin distinción de mayúsculas/minúsculas y se aceptan con o sin la `m` final (por ejemplo, `40` y `40m` funcionan igual).

Para cualquier otra frecuencia, proporcione `--freqs` con valores explícitos:

```bash
--bands MiBanda1,MiBanda2 --freqs 27.185,50.000
```

---

## 11. Recomendaciones de Flujo de Trabajo

### Primera ejecución — exploración gruesa
```bash
python nec2_length_optimizer.py \
    --csv mis_bandas.csv \
    --margin 5.0 \
    --wire-step 0.5 \
    --cp-step 0.5 \
    --retry 3
```
Use un margen amplio (5 m) y un paso grueso (0.5 m) para mapear rápidamente el espacio de búsqueda. `--retry 3` deja que la ventana se desplace hasta encontrar la región óptima real.

### Segunda ejecución — ajuste fino
```bash
python nec2_length_optimizer.py \
    --csv mis_bandas.csv \
    --wire-min 20.0 \
    --wire-max 23.0 \
    --wire-step 0.05 \
    --cp-min 4.5 \
    --cp-max 6.5 \
    --cp-step 0.05
```
Estreche la ventana alrededor del mejor candidato grueso y refine con resolución de 5 cm.

### Validar el UnUn
Revise la sección **Análisis UnUn** del informe. Si el óptimo continuo `n` está lejos de su relación de transformador instalada, considere construir o comprar un núcleo diferente.

### Comparar orientaciones
Ejecute una vez con `--cp-type horizontal`, una vez con `--cp-type vertical` y compare las puntuaciones combinadas y el ROS por banda. En la práctica, los CPs verticales pueden superar a los horizontales a bajas alturas.

### Validar en el banco de pruebas
El optimizador le da la mejor geometría *sobre el papel*. Verifique siempre con un VNA o analizador de antenas antes de cortar el hilo definitivo. Las condiciones del suelo, las estructuras cercanas y el catenario real del hilo afectan el resultado en el mundo real.

### Parámetros típicos de suelo

| Tipo de suelo | σ (S/m) | εᵣ |
|---|---|---|
| Muy seco / arenoso | 0.001 | 3 |
| Medio / mixto | 0.005 | 13 |
| Bueno / suelo rico | 0.010 | 20 |
| Pantanoso / húmedo | 0.030 | 30 |
| Agua de mar | 4.000 | 80 |

---

## 12. Solución de Problemas

**`nec2c` no se encuentra automáticamente**

```
  El binario nec2c no se encontró automáticamente.
  Opciones:
    • Instalar: sudo apt install nec2c   (Debian/Ubuntu)
    •           brew install nec2c        (macOS / Homebrew)
    • Ejecutar con: --nec2c /ruta/completa/a/nec2c
    • Variable env: export NEC2C=/ruta/completa/a/nec2c
```

Instale `nec2c` o pase su ruta explícitamente con `--nec2c`. Si solo desea resultados rápidos sin él, agregue `--mode empirical`.

---

**No se encontraron bandas activas**

```
  No se encontraron bandas activas.  Establezca la columna 'active' en SÍ en el CSV,
  o use --active-bands, u omita --active-bands para activar todas las --bands.
```

Compruebe que la columna `active` de su CSV contenga `YES` (o `Y`, `TRUE`, `1`, `ACTIVE`) en al menos una fila. Si está usando `--bands` sin CSV, todas las bandas están activas por defecto.

---

**Error de discrepancia en `--freqs`**

```
  ERROR: --bands tiene 3 entradas pero --freqs tiene 2. Deben coincidir uno a uno.
```

Cuente los valores separados por comas en `--bands` y `--freqs` — deben ser iguales.

---

**La advertencia de límite persiste tras `--retry`**

Si `--retry N` agota todos los N reintentos y la advertencia de límite sigue presente, el óptimo real puede estar más allá de lo que es físicamente razonable. Considere:
- Si un hilo tan largo/corto es físicamente construible en su emplazamiento.
- Si la asignación de frecuencia o la relación UnUn está causando una adaptación inherentemente mala (pruebe `--unun 4` o `--unun 16`).
- Ejecutar con `--mode empirical` y un rango muy amplio para explorar el espacio completo de forma económica antes de comprometerse con una ejecución larga de NEC2.

---

**Todos los valores de ROS son muy altos**

Si todas las bandas muestran ROS > 6:
1. La relación UnUn puede ser incorrecta. Revise la sección `Análisis UnUn` — sugerirá una mejor relación.
2. La longitud del hilo puede estar en resonancia en la mayoría de las bandas simultáneamente (puntuación de evitación cercana a 0). Pruebe añadiendo o restando 1–2 m.
3. El modelo de suelo puede no coincidir con la realidad. Pruebe diferentes valores de `--ground-cond` / `--ground-diel`.
4. En modo empírico, los resultados cerca de resonancias pueden ser imprecisos. Pruebe `--mode nec2`.

---

**El archivo de gráfico no se genera**

`matplotlib` no está instalado. Instálelo:
```bash
pip install matplotlib
```

---

**Faltan los diagramas de radiación**

Los diagramas de radiación requieren el modo NEC2. Compruebe que:
1. `nec2c` está instalado y se encuentra.
2. `--mode` es `nec2` o `auto` (no `empirical`).
3. Hay al menos una banda activa.

---

## 13. Licencia

```
CC0 1.0 Universal (CC0 1.0) Dedicación al Dominio Público

En la medida de lo posible bajo la ley, el autor (LU3VEA) ha renunciado a
todos los derechos de autor y derechos conexos o afines sobre esta obra.
Puede copiar, modificar, distribuir y ejecutar la obra, incluso con fines
comerciales, sin necesidad de pedir permiso.

https://creativecommons.org/publicdomain/zero/1.0/deed.es
```
