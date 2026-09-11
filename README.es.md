<p align="center">
  <img src="https://github.com/hiperiondev/Long_Wire_Antenna/raw/main/images/logo.png" width="150">
</p>

<div align="center">

# Optimizador de Longitud de Antena NEC2

**Encuentra la longitud de hilo (y de contrapeso) que da el menor ROE en todas las bandas de radioaficionado que te interesen — respaldado por simulación real NEC-2 de método de momentos, no por conjeturas.**

Autor: **LU3VEA** · Licencia: **CC0 1.0** (dominio público, aplica solo al script y a la documentación — ver [Nota sobre licencias de terceros](#nota-sobre-licencias-de-terceros)) · Plataforma: instalador para Windows, AppImage para Linux, o script Python multiplataforma

</div>

---

## Qué hace

Si estás armando una antena de hilo multibanda alimentada por el extremo o inclinada, la eterna pregunta es: *¿qué largo tiene que tener el hilo?* Esta herramienta responde esa pregunta de forma empírica en lugar de a ojo.

Recorre una grilla de combinaciones candidatas de **largo del radiador** y **largo del contrapeso** *(el contrapeso es el hilo secundario o la referencia de tierra que provee el camino de retorno de RF en una antena alimentada por el extremo — ver [Glosario](#glosario))*, y para cada combinación:

1. Genera un archivo de entrada NEC-2 `.nec` (radiador inclinado + contrapeso inclinado, con modelado de tierra y de material del hilo).
2. Ejecuta [`nec2c`](https://www.nec2.org/) para simular la antena en la frecuencia central de cada una de tus bandas objetivo.
3. Analiza los resultados de impedancia y calcula un **puntaje de ROE agregado** en todas las bandas activas, con penalizaciones para las bandas que se alejan del ángulo de radiación objetivo o de la ganancia deseada.
4. Rastrea los candidatos **Pareto-óptimos** (los mejores compromisos entre bandas, en lugar de que una sola banda gane a costa de las demás).

Al final obtenés un reporte ordenado, un gráfico de dispersión de todo el espacio de búsqueda, un CSV con los mejores candidatos, un archivo `.nec` listo para simular con el ganador, diagramas de patrón de radiación, un diagrama de construcción y opcionalmente un PDF de una página tipo "folleto de antena" que resume la construcción.

También puede recomendar la mejor **relación de transformación de UnUn** estándar (p. ej. 9:1, 4:1, 1:1 — un UnUn es un transformador de adaptación de impedancia "no balanceado a no balanceado"; ver [Glosario](#glosario)) para tu línea de alimentación, y advertirte cuando ninguna relación elimina el desacople de impedancia de forma limpia en una banda determinada.

---

## Lo más destacado

- 🎯 **Optimización multibanda** — optimizá para cualquier combinación de bandas simultáneamente (p. ej. `40m,20m,17m,15m,10m`), no solo una.
- 📡 **Física NEC-2 real** — usa simulación de método de momentos (`nec2c`) en lugar de aproximaciones de fórmula cerrada, incluyendo modelos de tierra realistas (Sommerfeld/Norton o tierra perfecta).
- ⚡ **Modo empírico rápido** — un modo de respaldo `--mode empirical` con fórmulas de forma cerrada cuando no tenés `nec2c` instalado o solo querés una estimación rápida; `--mode auto` elige la mejor opción disponible.
- 🌍 **CLI multilingüe** — interfaz completa en inglés, español e italiano, detectada automáticamente según la configuración regional del sistema (o forzada con `--lang`).
- 🖥️ **Modo GUI** — una interfaz gráfica en Tkinter (`--gui`) para quienes prefieran no usar la terminal.
- 🔧 **Modelado físicamente realista** — diámetro y material de hilo configurables (cobre, aluminio, latón, plata, acero, o "perfecto" sin pérdidas), geometría de hilo inclinada u horizontal, altura y parámetros de tierra reales.
- 🔌 **Asesor de relación de UnUn** — evalúa relaciones de transformación estándar contra la impedancia cruda de la antena y te dice cuál te acerca más a un acople limpio en cada banda.
- 📊 **Salida rica** — reporte de texto ordenado, gráfico de dispersión (PNG), CSV con los mejores candidatos, archivo `.nec` del mejor candidato, diagramas de patrón de radiación, diagrama de construcción y folleto en PDF.
- 🪟 **Instalador para Windows en un clic** — incluye Python, `nec2c` y todas las dependencias para que cualquier radioaficionado, sin conocimientos técnicos, pueda empezar sin tocar un gestor de paquetes.
- 🐧 **AppImage para Linux en un clic** — la misma idea para Linux, sin necesidad de `pip install` ni gestor de paquetes.

Actualmente **no existe un instalador empaquetado para macOS**. Los usuarios de macOS deben usar la [Opción C](#opción-c--ejecutar-el-script-python-directamente-windowsmacoslinux) más abajo.

---

## Contenido del repositorio

| Archivo / carpeta                                              | Descripción                                                                                                                                                                     |
| ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/Long_Wire_Antenna.py`                                    | El optimizador en sí — un script Python autocontenido (CLI + GUI opcional). Es el archivo que ejecutás directamente para la [Opción C](#opción-c--ejecutar-el-script-python-directamente-windowsmacoslinux). |
| `Setup_Long_Wire_Antenna.exe`                                 | Instalador de Windows precompilado y autocontenido (incluye `Long_Wire_Antenna.py`, `nec2c.exe`, el lanzador y el script de posinstalación — no necesita ningún otro archivo al lado). |
| `Long_Wire_Antenna-x86_64.AppImage`                            | AppImage de Linux precompilado — el equivalente en un clic del instalador de Windows, para Linux x86\_64.                                                                       |
| `documentation/Long_Wire_Antenna_Manual_EN.md`                 | Manual de usuario extendido en inglés.                                                                                                                                          |
| `documentation/Long_Wire_Antenna_Manual_ES.md`                 | Manual de usuario extendido en español.                                                                                                                                         |
| `documentation/Long_Wire_Antenna_Manual_IT.md`                 | Manual de usuario extendido en italiano.                                                                                                                                        |
| `images/logo.png`, `images/icon.png`                           | Logo del proyecto (el de arriba de este README) e ícono de la aplicación (usado por el instalador/accesos directos de Windows y por el AppImage de Linux).                     |
| `others/build_windows_installer.sh`                            | Script de compilación que genera `Setup_Long_Wire_Antenna.exe` a partir de las fuentes en `others/windows_installer/` usando NSIS (`makensis`). Se ejecuta en Fedora/RHEL o Debian/Ubuntu; instala `nsis` e `imagemagick` automáticamente si faltan. |
| `others/windows_installer/long_wire_antenna_installer.nsi`     | Script [NSIS](https://nsis.sourceforge.io/) que define el instalador de Windows, compilado por `build_windows_installer.sh`.                                                    |
| `others/windows_installer/nec2c.exe`                           | Binario precompilado para Windows del [motor de método de momentos NEC-2](https://www.nec2.org/), que queda embebido en `Setup_Long_Wire_Antenna.exe`. Binario de terceros — ver [nota de licencias](#nota-sobre-licencias-de-terceros). No pensado para usarse por separado — ver la [Opción C](#opción-c--ejecutar-el-script-python-directamente-windowsmacoslinux) si necesitás un binario `nec2c` para una instalación manual/no-Windows. |
| `others/windows_installer/payload/run_gui.bat`                 | Archivo `.bat` lanzador que se instala junto al script; es lo que realmente ejecuta el acceso directo del Escritorio. Configura la codificación UTF-8 de consola/Python, apunta la variable de entorno `NEC2C` al motor incluido y luego ejecuta `Long_Wire_Antenna.py --gui`. |
| `others/windows_installer/payload/post_install_setup.py`       | Se ejecuta una sola vez, automáticamente, al final de la instalación (con el intérprete de Python recién instalado) para instalar con `pip` los paquetes necesarios y terminar de configurar el motor NEC2. Ver la nota sobre el [instalador de Windows](#opción-a--windows-la-más-fácil) más abajo. |
| `others/build_appimage.sh`                                     | Script de compilación que genera el AppImage de Linux portátil y autocontenido (incluye Python + Tk + `nec2c` compilado estáticamente, sin dependencias del sistema anfitrión). |
| `LICENSE`                                                       | CC0 1.0 Universal (dedicación al dominio público) — aplica al script y a la documentación propios del proyecto, no a los binarios de terceros incluidos.                       |

> **Nota sobre archivos binarios en este repositorio:** el instalador de Windows (`Setup_Long_Wire_Antenna.exe`), el `nec2c.exe` que incluye, y el AppImage de Linux (`Long_Wire_Antenna-x86_64.AppImage`) se suben directamente a este repositorio git en lugar de publicarse como GitHub Releases separadas. Esto es cómodo para la descarga directa, pero implica que el historial del repositorio incluye archivos binarios grandes. Actualmente no se publican checksums SHA-256 de estos archivos en este README; si necesitás verificar la integridad, calculá el hash vos mismo tras la descarga (`sha256sum <archivo>` en Linux/macOS, `certutil -hashfile <archivo> SHA256` en Windows) y compará contra un checksum obtenido por un canal de confianza, ya que todavía no se publica ninguno acá.

---

## Instalación

### Opción A — Windows (la más fácil)

Descargá y ejecutá **`Setup_Long_Wire_Antenna.exe`**. Es totalmente autocontenido — no necesita ningún otro archivo al lado. El instalador va a:

1. Verificar si hay un intérprete de Python 3 y, si falta, instalar silenciosamente Python 3.12.7 (64 bits) desde python.org (con pip, el lanzador `py` y PATH configurados).
2. Instalar `Long_Wire_Antenna.py`, el lanzador `run_gui.bat`, `post_install_setup.py`, el ícono de la aplicación y el texto de la licencia en el directorio de instalación elegido (`C:\Program Files\LongWireAntenna` por defecto).
3. Instalar el `nec2c.exe` incluido en `%INSTDIR%\nec2c\`, y además copiarlo a `C:\Program Files\OpenNEC\` y a `C:\Program Files (x86)\OpenNEC\`.
4. Ejecutar `post_install_setup.py`, que instala con `pip` los paquetes de Python (`numpy`, `matplotlib`, `tabulate`, `colorama`, `reportlab`) y después revisa el motor NEC2 — ver la nota de abajo.
5. Crear un acceso directo en el Escritorio que ejecuta `run_gui.bat`, el cual a su vez lanza `Long_Wire_Antenna.py --gui`.
6. Registrar un desinstalador estándar de Windows.

> ⚠️ **Nota sobre una dependencia extra:** el paso 4 también instala con `pip` un quinto paquete, **`tabulate`**, además de los cuatro que el script realmente necesita. `Long_Wire_Antenna.py` **no** importa ni usa `tabulate` en ningún lado — es un resabio sin usar en la lista de dependencias del instalador, no un requisito real. Solo cuesta unos segundos extra de instalación y algo de espacio en disco, y no lo necesitás si configurás el script a mano ([Opción C](#opción-c--ejecutar-el-script-python-directamente-windowsmacoslinux)).

> ⚠️ **Particularidad conocida del instalador (paso de auto-actualización del motor):** como parte del paso 4, `post_install_setup.py` intenta opcionalmente descargar una versión más nueva del motor NEC2 desde un proyecto externo de GitHub y, si la encuentra, verifica que arranque correctamente antes de usarla — volviendo al "motor incluido" si la descarga falla o la versión descargada no arranca. Sin embargo, su lógica de respaldo busca un archivo incluido llamado `onec.exe` / `onec_bundled.exe`, mientras que el instalador solo llega a incluir un archivo llamado `nec2c.exe`. En la práctica esto solo significa que el paso opcional de actualización en línea no encuentra ese archivo de respaldo, así que no hace nada salvo que la descarga por red tenga éxito. Esto **no** rompe una instalación normal: `run_gui.bat` busca por su cuenta (y encuentra) `nec2c\nec2c.exe` y apunta la variable de entorno `NEC2C` directamente a él, así que el motor incluido se usa correctamente de todas formas. Vale la pena saberlo si estás revisando registros de instalación que mencionan `onec.exe`.

### Opción B — Linux (AppImage, la más simple para la mayoría de las distros)

Descargá **`Long_Wire_Antenna-x86_64.AppImage`**, dale permisos de ejecución y ejecutalo:

```
chmod +x Long_Wire_Antenna-x86_64.AppImage
./Long_Wire_Antenna-x86_64.AppImage
```

El AppImage incluye su propio intérprete Python 3.11 (con Tkinter), `numpy`, `matplotlib`, `colorama`, `reportlab`, `pillow`, y un binario `nec2c` compilado estáticamente — no hace falta instalar nada más en el sistema anfitrión, ni ejecutar ningún `pip install`.

> ⚠️ **El AppImage siempre abre directamente la GUI**, sin importar qué argumentos de línea de comandos le pases — el modo GUI se fuerza sin excepción. Esto es igual a cómo se comporta `--gui` al pasarlo al script Python directamente (ver la [advertencia sobre `--gui` en Uso](#abrir-la-gui) más abajo): la GUI se abre con sus propios valores por defecto, y actualmente **no hay forma de precargarla desde la línea de comandos**. Para usar la CLI, usá la [Opción C](#opción-c--ejecutar-el-script-python-directamente-windowsmacoslinux).

Podés recompilarlo vos mismo desde el código fuente con `others/build_appimage.sh` (se recomienda ejecutarlo sobre una base antigua como Ubuntu 20.04, o la imagen Docker oficial del constructor de AppImage, para mantener bajo el requisito de glibc).

### Opción C — Ejecutar el script Python directamente (Windows/macOS/Linux)

Esta es también la **única vía soportada para macOS**, ya que no existe un instalador empaquetado para ese sistema.

**Requisitos:**

- Python 3.8 o superior
- [`nec2c`](https://www.nec2.org/) en tu `PATH` (o indicá la ruta con `--nec2c`) — opcional si solo pensás usar `--mode empirical`
- Paquetes de Python:

```
pip install numpy matplotlib colorama reportlab
```

`colorama`, `matplotlib`, `numpy` y `reportlab` son todos opcionales — el script se degrada de forma controlada (sin color, sin gráfico ni PDF) si no están instalados. `numpy` solo hace falta para los diagramas de patrón de radiación, y normalmente se instala solo como dependencia de `matplotlib`, así que rara vez hay que instalarlo aparte.

**Orden de búsqueda del binario NEC2C:**

1. `--nec2c /ruta/a/nec2c` (flag explícito)
2. Variable de entorno `$NEC2C`
3. `PATH` (`nec2c`, `nec2c-mpich`, `onec`)
4. Rutas de instalación comunes (`/usr/bin`, `/usr/local/bin`, `/opt/nec2c/bin`, etc.)
5. Consulta interactiva (a menos que se use `--no-interactive`)

Si no se encuentra `nec2c` por ninguna de estas vías y `--no-interactive` está activado (o rechazás la consulta), el script pasa a `--mode empirical` si estaba en `--mode auto`, o termina con un error si pediste explícitamente `--mode nec2`.

---

## Uso

### Básico — bandas conocidas

```
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --wire-len 21.0 --cp-len 5.0
```

Las frecuencias centrales de las bandas conocidas se resuelven automáticamente, así que `--freqs` es opcional en este caso.

### Bandas personalizadas / desconocidas

```
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \
    --wire-len 21.0 --cp-len 5.0
```

### Restringir qué bandas realmente definen el puntaje

```
python src/Long_Wire_Antenna.py --bands 40m,20m,15m --freqs 7.1,14.2,21.2 \
    --active-bands 40m,20m --wire-len 21.0 --cp-len 5.0
```

### Abrir la GUI

```
python src/Long_Wire_Antenna.py --gui
```

> ⚠️ **`--gui` tiene prioridad absoluta sobre todo lo demás.** Se evalúa *antes* de analizar el resto de la línea de comandos, así que si lo combinás con otros flags (p. ej. `python src/Long_Wire_Antenna.py --gui --bands 40m,20m`), **esos otros flags se ignoran silenciosamente** — no se muestra ninguna advertencia ni error, y la GUI simplemente se abre con sus propios valores predeterminados. Actualmente no hay forma de precargar los campos de la GUI desde argumentos de la CLI. Una vez abierta, usá sus propios campos para configurar todo.

### Ayuda completa

```
python src/Long_Wire_Antenna.py --help
```

Las bandas predefinidas abarcan desde LF hasta UHF: `2200m, 630m, 160m, 80m, 60m, 40m, 30m, 20m, 17m, 15m, 12m, 10m, 6m, 4m, 2m, 70cm, 23cm`.

---

## Opciones principales

| Flag                                                                                                     | Propósito                                                                                                                                                                                                |
| ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--bands` / `--freqs`                                                                                    | Bandas a modelar, y sus frecuencias (MHz) si no están en la tabla de bandas conocidas.                                                                                                                   |
| `--active-bands`                                                                                         | Subconjunto de `--bands` que realmente aporta al puntaje de optimización.                                                                                                                                |
| `--wire-len`, `--cp-len`                                                                                 | Largo inicial/central del radiador y del contrapeso (m).                                                                                                                                                 |
| `--wire-min/max/step`, `--cp-min/max/step`                                                               | Definen la grilla de búsqueda alrededor de los largos iniciales.                                                                                                                                         |
| `--mode {empirical,nec2,auto}`                                                                           | Usar fórmulas de forma cerrada, simulación NEC-2 completa, o selección automática.                                                                                                                       |
| `--height`                                                                                               | Altura de la antena sobre el suelo (m).                                                                                                                                                                  |
| `--wire-slope-end-height`, `--cp-end-height`                                                             | Modelan un hilo/contrapeso inclinado fijando la altura del extremo lejano (0 = extremo a nivel del suelo).                                                                                               |
| `--no-counterpoise`                                                                                      | Modela una antena alimentada por el extremo sin contrapeso. En modo NEC2, el camino de retorno de RF usa `ground-rod` por defecto; usá `--no-cp-return` para elegir `coax-stub` en su lugar, o para `reject` (rechazar) la configuración. |
| `--no-cp-return {ground-rod,coax-stub,reject}`                                                           | Cómo se modela el camino de retorno de RF cuando no hay contrapeso.                                                                                                                                      |
| `--ground-model {sommerfeld,perfect}`                                                                    | Modelo de tierra usado por NEC-2.                                                                                                                                                                        |
| `--ground-cond`, `--ground-diel`                                                                         | Conductividad del suelo (S/m) y constante dieléctrica.                                                                                                                                                   |
| `--wire-diameter`, `--wire-material`                                                                     | Diámetro físico del hilo (mm) y material (`copper`, `aluminium`/`aluminum`, `brass`, `silver`, `steel`, `perfect`).                                                                                      |
| `--target-toa`                                                                                           | Ángulo de radiación (take-off) objetivo (grados) usado en el puntaje.                                                                                                                                    |
| `--gain-weight`                                                                                          | Peso de la ganancia frente al ROE en el puntaje agregado.                                                                                                                                                |
| `--top-n`                                                                                                | Cantidad de candidatos ordenados a reportar.                                                                                                                                                             |
| `--out-txt`, `--out-png`, `--out-csv`, `--out-nec`, `--out-radiation`, `--out-construction`, `--out-pdf` | Rutas de salida para cada archivo del reporte.                                                                                                                                                           |
| `--lang {en,es,it}`                                                                                      | Forzar idioma de la interfaz (si no, se detecta automáticamente según la configuración regional).                                                                                                        |
| `--gui`                                                                                                  | Abre la GUI de Tkinter en lugar de la CLI. **Ignora silenciosamente todos los demás flags** — ver la [advertencia anterior](#abrir-la-gui).                                                              |
| `--quiet` / `-q`                                                                                         | Suprime salida de consola no esencial.                                                                                                                                                                   |

Ejecutá `--help` para ver la lista completa y actualizada — el script tiene muchas más opciones de ajuste fino (segmentos por media onda, modos rápido/convergencia, cantidad de reintentos, etc.).

---

## Salida

Una ejecución típica produce:

- **`optimizer_report.txt`** — reporte de texto ordenado con los mejores candidatos y su ROE por banda.
- **`optimizer_plot.png`** — gráfico de dispersión de todo el espacio de búsqueda con el frente de Pareto resaltado.
- **`optimizer_best.csv`** — mejores candidatos en formato CSV, listos para importar en otra herramienta.
- **`best_antenna.nec`** — el archivo NEC-2 de la geometría ganadora, listo para volver a simular o ajustar.
- **`radiation_diagrams.png`** — gráficos del patrón de radiación de la antena ganadora.
- **`antenna_construction.png`** — un diagrama de construcción/armado.
- **`antenna_brochure.pdf`** — un resumen en PDF de una página (requiere `reportlab`).

---

## Cómo funciona el puntaje

Para cada candidato `(wire_len, cp_len)`, el script calcula un ROE por banda a partir de la impedancia del punto de alimentación simulada (o estimada empíricamente), y luego agrega esos valores en un único puntaje penalizado que también tiene en cuenta:

- La desviación respecto del ángulo de radiación deseado (ponderada por `--gain-weight`).
- Qué tan lejos está el largo del contrapeso de una relación "ideal" de cuarto de onda para cada banda.
- Los candidatos que no están dominados en el sentido de Pareto se marcan para que puedas ver compromisos multibanda genuinos en lugar de un único mejor número.

Luego la herramienta compara por separado las relaciones de transformador UnUn estándar (1:1, 4:1, 9:1, etc.) contra la impedancia cruda de la antena ganadora y reporta cuál relación acerca más el ROE a 1:1 en cada banda — marcando además las bandas en las que ninguna relación estándar resuelve el desacople, porque a veces es físicamente imposible que un único diseño de línea de alimentación cubra bien muchas bandas sin relación entre sí.

---

## Glosario

- **Contrapeso (counterpoise)** — un hilo (o conjunto de hilos) conectado al lado de retorno de RF / tierra del punto de alimentación de una antena alimentada por el extremo, usado en lugar de (o además de) una tierra real para proveer el camino de retorno de la corriente de RF.
- **ROE (Relación de Onda Estacionaria, VSWR en inglés)** — una medida de qué tan bien está acoplada la impedancia de la antena a la línea de alimentación; 1:1 es un acople perfecto, valores más altos indican más potencia reflejada.
- **UnUn (transformador no balanceado a no balanceado)** — un transformador de RF que cambia la impedancia (p. ej. 9:1, 4:1) entre una línea de alimentación no balanceada (coaxil) y una antena no balanceada como un hilo alimentado por el extremo, usado para acercar la impedancia cruda de la antena a la impedancia característica de la línea (típicamente 50 Ω).
- **Ángulo de radiación (take-off angle, TOA)** — el ángulo vertical sobre el horizonte en el que una antena irradia su señal de campo lejano máxima; ángulos más bajos generalmente favorecen la propagación a larga distancia (DX).
- **Candidato Pareto-óptimo** — un par candidato `(wire_len, cp_len)` para el cual ningún otro candidato es simultáneamente al menos igual de bueno en todas las bandas activas y estrictamente mejor en al menos una; es decir, un compromiso multibanda genuino en lugar de una opción dominada (estrictamente peor).

---

## Solución de problemas

<!-- TODO(mantenedor): Esta sección es un marcador de posición. El README/manuales originales
     no incluían una sección de solución de problemas o preguntas frecuentes, y no fue posible
     obtener los mensajes de error reales del script ni su comportamiento de códigos de salida
     al momento de corregir este documento. Por favor reemplazar los puntos siguientes con
     información verificada y fiel al script, por ejemplo:
     - ¿Qué ocurre si no se encuentra nec2c y está activado --no-interactive?
     - ¿Qué significa en la práctica la advertencia "ninguna relación estándar resuelve el
       desacople", y qué debería hacer el usuario al respecto?
     - Causas comunes de fallas de convergencia/reintentos de NEC-2 y cómo las maneja --mode auto.
     - Qué hacer si faltan matplotlib/reportlab pero se pidió un gráfico o PDF. -->

## Nota sobre licencias de terceros

El código fuente propio de este proyecto (`src/Long_Wire_Antenna.py`), los scripts de compilación y la documentación se publican bajo **CC0 1.0 Universal** (dominio público) — ver [`LICENSE`](https://github.com/hiperiondev/Long_Wire_Antenna/blob/main/LICENSE).

El `nec2c.exe` incluido (Windows) y el binario `nec2c` compilado estáticamente dentro del AppImage de Linux son **software de terceros** — la traducción a C de NEC-2 [`nec2c`](https://www.nec2.org/) hecha por Neoklis Kyriazis (5B4AZ), a su vez derivada del código original NEC-2 desarrollado en el Lawrence Livermore National Laboratory. Estos binarios **no** están cubiertos por la dedicación CC0 de este proyecto; conservan sus propios términos de licencia originales.

<!-- TODO(mantenedor): Indicar la licencia exacta de origen (p. ej. variante BSD específica o
     estado de dominio público) que aplica al binario nec2c incluido, y confirmar que los
     términos de redistribución se cumplen al distribuir el binario compilado en este repositorio. -->

Si redistribuís este proyecto (incluyendo el instalador, el AppImage, o `nec2c.exe`), asegurate de que tu redistribución también cumpla con los términos de licencia propios de `nec2c`, no solo con la dedicación CC0 de este proyecto.

---

## Licencia

El código y la documentación propios de este proyecto se publican bajo **CC0 1.0 Universal** — dominio público. Hacé lo que quieras con él, no se requiere atribución. Ver [`LICENSE`](https://github.com/hiperiondev/Long_Wire_Antenna/blob/main/LICENSE) para el texto legal completo. Los binarios de terceros incluidos quedan excluidos — ver [Nota sobre licencias de terceros](#nota-sobre-licencias-de-terceros) más arriba.

## Agradecimientos

- [NEC-2](https://www.nec2.org/) (Numerical Electromagnetics Code) — el motor de simulación de antenas subyacente.
- Desarrollado por **LU3VEA** para la comunidad de radioaficionados.

---

*73! Si esta herramienta te ayudó a construir una mejor antena, considerá compartir tus resultados con la comunidad.*
