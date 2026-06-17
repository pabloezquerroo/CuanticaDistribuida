# CuanticaDistribuida

Repositorio de Trabajo de Fin de Máster sobre corrección de errores cuánticos en arquitectura cloud distribuida.

---

## Índice

- [Documentación y Recursos](#documentación-y-recursos)
- [Código de referencia el cual se busca hacer distribuido](#código-de-referencia-el-cual-se-busca-distribuir)
- [Arquitectura Distribuida](#arquitectura-distribuida)
- [Ejecución y pruebas](#ejecución-y-pruebas)

---

## Documentación y Recursos

- **Introducción a QEC:**  
  - https://arxiv.org/abs/2304.08678

- **Artículos recientes sobre decodificadores modernos:**  
  - https://arxiv.org/abs/2502.16408  
  - https://arxiv.org/abs/2503.10988  
  - https://arxiv.org/abs/2503.01738  
  - https://arxiv.org/abs/2504.01164v1  
  - https://arxiv.org/abs/2506.01779v1

- **Herramientas:**
  - [Stim (generación de ruido)](https://github.com/quantumlib/Stim)
  - [LDPC decoders](https://software.roffe.eu/ldpc/)
  - [LDPC GitHub](https://github.com/quantumgizmos/ldpc?tab=readme-ov-file)
  - [AutDEC](https://github.com/hsayginel/autdec)

---

## Código de referencia el cual se busca distribuir

- **test_v2.py**  
  Script para pruebas locales con la versión 2 de la librería QEC.
- **IBM_STIM.py, dem_to_matrices.py, utils.py**  
  Utilidades para generación de ruido, construcción de circuitos cuánticos.  
  *No necesarios para la decodificación.*

### Sobre el código

El primer bucle recorre los diferentes códigos de IBM (`for codeConfig in codesConfig`) En principio supongo que nos centraríamos en un primer código para arrancar y podríamos eliminar este bucle. El de tamaño 144 sería el mejor, ya que es el código más pequeño en el que se verá el beneficio de usar la nube para aumentar la precisión.

El siguiente bucle recorre las diferentes probabilidades de error físico (`for index, p in enumerate(ps)`). De nuevo, me imagino que lanzaríamos cada probabilidad por separado. Cuanto menos ruido, menos tardarán los decodificadores, pero más simulaciones son necesarias para que el resultado sea significativo. Cuanto más ruido más iteraciones son necesarias, pero se ejecutan menos simulaciones.

Ahora mismo, estaría integrada la librería más nueva para que no dé problemas con el resto. Lo he verificado con BP+LSD que no estaba en la anterior librería. Así que los constructores que se ejecutan estos:

```python
if ldpc_v2 is True:
    # https://software.roffe.eu/ldpc/quantum_decoder.html
    _bp = BpDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", channel_probs=matrices.priors)
    _bplsd = BpLsdDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", osd_method='lsd_cs', osd_order=2)
    _bposd = BpOsdDecoder(pcm, max_iter=100, error_rate=float(p), bp_method="product_sum", schedule='parallel', osd_method="osd_0")
```

Las decodificaciones son:

```python
predicted_error = _bp.decode(detectors[0])
predicted_error_lsd = _bplsd.decode(detectors[0])
predicted_error_osd = _bposd.decode(detectors[0])
```

Y la comprobación de los errores lógicos es:

```python
logical_error = (observable_mat @ predicted_error + observables) % 2
logical_error_lsd = (observable_mat @ predicted_error_lsd + observables) % 2
logical_error_osd = (observable_mat @ predicted_error_osd + observables) % 2
```

Cuando se produce un error es interesante saber si el algoritmo ha convergido o no para saber si erróneamente el decodificador piensa que ha sido capaz de eliminar el ruido.  
  
También es interesante seguir la cuenta de errores lógicos y errores físicos. Los primeros ya los contamos, pero los segundos se obtendrían comparando los observables predichos con los observables reales.  

Almacenar el número de iteraciones medio, si el algoritmo es iterativo, y la predicción de salida, también podría ser útil para medir la velocidad o saber si los algoritmos oscilan o no.  

Para todo lo anterior hay métodos ya creados como los siguientes:

```python
convergence = _bp.converge
iteration_stop = _bp.iter
soft_decisions_llr = _bp.log_prob_ratios
```

---

## Arquitectura Distribuida

La arquitectura del proyecto está diseñada para ejecutar simulaciones de corrección de errores cuánticos de forma masivamente paralela, utilizando un sistema de Lambdas y servicios de AWS. El diseño se basa en un fan-out de dos niveles para distribuir la carga de trabajo: el **dispatcher (`args_mixer`)** distribuye las combinaciones de argumentos, el **orquestador (`orchestrator`)** genera los datos de simulación, un segundo **dispatcher (`nmc_worker`)** coordina la distribución de tareas, y múltiples **workers (`args_worker`)** ejecutan los cálculos finales aplicando automorfismos.

Los componentes se comunican de forma asíncrona a través de S3 para el almacenamiento de configuraciones, automorfismos y datos temporales de simulación, y DynamoDB para la coordinación, estado y resultados finales.

### Componentes del Sistema

-   **`args_mixer.py` (Lambda 1 - Dispatcher)**
    -   **Disparador**: Subida de un archivo `config.json` a un bucket de S3.
    -   **Función**: Lee la configuración del JSON que contiene:
        -   `codeConfig`: Configuración del código cuántico (ej. 144).
        -   `NMCs`: Lista de números de simulaciones Monte Carlo a ejecutar.
        -   `p`: Lista de probabilidades de error físico.
        -   `number_of_automorphisms`: Número de automorfismos disponibles.
        -   `args_batch_size`: Tamaño del lote de argumentos.
    -   Genera todas las combinaciones de parámetros de decodificadores y las agrupa en lotes de tamaño `args_batch_size`.
    -   Cada lote se guarda como un ítem en la tabla `args_dynamodb` con identificador `id_batch_arguments`.
    -   **Salida**: Invoca al `orchestrator.py` con el número total de lotes de combinaciones de argumentos (`number_of_args_combinations_batches`).

-   **`orchestrator.py` (Lambda 2 - Orquestador)**
    -   **Función**: Prepara los datos para la simulación. Lee la configuración de S3 y genera los arrays de detectores y observables en lotes de tamaño `NMC_batch_size`.
    -   Por cada lote de datos, realiza tres acciones:
        1.  Genera los arrays de detectores y observables mediante simulación cuántica.
        2.  Guarda los arrays en un archivo JSON en S3 con ruta estructurada: `bucket/automorphisms/<code>_<p>/detectors_observables/batch_X.json`.
        3.  Crea una entrada en la tabla `samples_dynamodb` con:
            -   `id_nmc_batch`: Identificador único del lote (formato: `nmc_<code>_<p>_<batch_counter>`).
            -   `s3_data_path`: Ruta al JSON en S3.
            -   `workers_completed`: Contador inicializado a 0.
    -   **Salida**: Invoca a `nmc_worker.py` por cada lote de datos generado, pasando `id_nmc_batch` y `number_of_args_combinations_batches`.

-   **`nmc_worker.py` (Lambda 3 - Dispatcher de segundo nivel)**
    -   **Función**: Actúa como un dispatcher de segundo nivel. Su objetivo es distribuir las combinaciones de argumentos contra un lote de datos de simulación.
    -   Recibe:
        -   `id_nmc_batch`: Identificador del lote de datos.
        -   `number_of_args_combinations_batches`: Número total de lotes de argumentos.
    -   Invoca una instancia de `args_worker.py` por cada lote de argumentos (`id_batch_arguments`), pasando:
        -   `id_nmc_batch`
        -   `id_batch_arguments` (distinto en cada invocación)
        -   `number_of_args_combinations_batches`

-   **`args_worker.py` (Lambda 4 - Worker Principal)**
    -   **Función**: Es el worker principal que ejecuta la simulación con automorfismos.
    -   Recibe:
        -   `id_nmc_batch`: Identifica el lote de datos de simulación.
        -   `id_batch_arguments`: Identifica el lote de argumentos a procesar.
        -   `number_of_args_combinations_batches`: Número total de lotes para coordinar limpieza.
    -   Proceso:
        1.  Lee los datos de simulación (detectores/observables) desde S3 usando la ruta almacenada en `samples_dynamodb`.
        2.  Lee el lote de argumentos desde `args_dynamodb` (id_batch_arguments).
        3.  Para cada argumento en el lote:
            -   Lee de S3 el automorfismo correspondiente (`id_automorphism`): PCM, priors, row_perm desde `bucket/automorphisms/<error_rate>/auto_<id>/data.pkl`.
            -   Aplica el automorfismo a los detectores mediante `row_perm @ detectors[i] % 2`.
            -   Ejecuta la decodificación con el PCM y priors del automorfismo.
            -   Calcula métricas: error_rate, Pl (probabilidad de error lógico), time_av, time_max, corrected_patterns.
        4.  Guarda los resultados en `results_dynamodb` con estructura:
            ```
            {
                "id_nmc_batch": "<nmc_batch_id>",
                "id_arguments": "<decoder>_<id_automorphism>",
                "id_automorphism": <id>,
                "codeConfig": <code>,
                "error_rate": <p>,
                "decoder_type": "<BP|BPLSD|BPOSD>",
                "arguments": {...},
                "Pl": <float>,
                "time_av": <float>,
                "time_max": <float>,
                "corrected_patterns": [...]
            }
            ```
    -   **Coordina la limpieza**: Incrementa el contador `workers_completed` en `samples_dynamodb`. Si es el último worker (`workers_completed >= number_of_args_combinations_batches`), borra el archivo de datos temporales de S3 y la entrada correspondiente en `samples_dynamodb`.

### Servicios AWS
-   **Lambda**: Ejecución de las diferentes funciones que conforman la arquitectura distribuida.
-   **S3**: Almacenamiento de:
    -   Variables de configuración iniciales (`config.json`).
    -   Automorfismos precalculados por código y probabilidad de error.
    -   Datos temporales de simulación (detectores/observables).
-   **DynamoDB**: 
    -   `args_dynamodb`: Combinaciones de argumentos para los decodificadores.
    -   `samples_dynamodb`: Información referente a los datos temporales de simulación y coordinación de workers.
    -   `results_dynamodb`: Resultados finales de las simulaciones con automorfismos.

### Flujo de Ejecución
1.  **Inicio**: Un usuario sube el archivo `config.json` a S3, lo que dispara `args_mixer`.
2.  **`args_mixer`**: Genera las combinaciones de argumentos (decodificadores × automorfismos) y las guarda en lotes en `args_dynamodb`. Invoca al `orchestrator` con el número total de lotes de argumentos.
3.  **`orchestrator`**: Genera un lote de datos de simulación (ej. 1000 NMCs), lo guarda en S3 y crea una entrada de seguimiento en `samples_dynamodb`. Invoca a `nmc_worker` con el ID del lote de datos (`id_nmc_batch`) y el número de lotes de argumentos.
4.  **`nmc_worker`**: Recibe el `id_nmc_batch` y `number_of_args_combinations_batches`. Invoca a N instancias de `args_worker`, una por cada lote de argumentos (`id_batch_arguments`) que se debe probar contra ese lote de datos.
5.  **`args_worker`**: Cada instancia:
    -   Lee sus argumentos de `args_dynamodb`.
    -   Lee los datos de simulación de S3.
    -   Para cada argumento, lee el automorfismo correspondiente de S3.
    -   Ejecuta la decodificación aplicando el automorfismo.
    -   Guarda los resultados en `results_dynamodb`.
6.  **Limpieza**: El último `args_worker` de un lote de datos limpia los datos temporales de S3 y `samples_dynamodb`.
7.  El proceso se repite desde el paso 3 para todos los lotes de datos que el orquestador necesite generar.

### Estructura de Datos en S3

```
bucket/
├── config.json
└── automorphisms/
    ├── <error_rate_1>/
    │   ├── auto_0/
    │   │   └── data.pkl (PCM, priors, row_perm)
    │   ├── auto_1/
    │   │   └── data.pkl
    │   └── detectors_observables/
    │       ├── batch_0.json
    │       └── batch_1.json
    └── <error_rate_2>/
        └── ...
```

---

## Ejecución y pruebas

### Local
Herramientas y pasos a seguir para la prueba del proyecto en un entorno local.

1.  **En este caso se ha usado el gestor de paquetes y entornos virtuales [uv](https://docs.astral.sh/uv/):**
    -   Instala con script:
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```
    -   Instala con Homebrew (MacOS):
    ```bash
    brew install uv
    ```
    -   Instala las dependencias definidas en `pyproject.toml` y `uv.lock`.
    ```bash
    uv sync
    ```

2.  **Configuración del Entorno:**
    -   Crea un archivo `.env` en la raíz del proyecto con las variables de entorno necesarias. Consulta el archivo `.env.example` para ver las variables requeridas.

3.  **Iniciar DynamoDB local:**
    -   Usa el archivo `resources/docker-compose.yaml` para levantar un contenedor con DynamoDB local.
    ```bash
    cd resources
    docker-compose up
    ```

4. **Iniciar S3 local:**
    
    Se hace uso del framework [serverless](https://www.serverless.com/) con los plugins `serverless-s3-local` y `serverless-offline` para simular S3 localmente. 
    
    -   Asegúrate de tener Node.js instalado. En macOS, lo habitual es instalar Node.js con Homebrew, lo que incluye `npm`:
    ```bash
    brew install node
    ```

    -  Instala las dependencias Node del proyecto. Esto ya incluye los plugins de Serverless declarados en `package.json`:
    ```bash
    npm install
    ```


    El bucket se crea automáticamente al iniciar el entorno con `serverless offline`.

4.  **Preparar Automorfismos:**
    
    Los automorfismo se calculan y guardan mediante el script `reference_code/automorphisms/Pablo_automorph.ipynb`. Asegúrate de ejecutar este jupiterNB para generar los automorfismos necesarios antes de lanzar el pipeline. El script guardará los automorfismos en S3 siguiendo la estructura esperada.

    -   Asegúrate de que los automorfismos precalculados estén disponibles en S3 en la estructura esperada:
    ```
    bucket/automorphisms/<error_rate>/auto_<id>/data.pkl
    ```

5. **Ejecutar pipeline:**

    - Lanzamos el entorno virtual generado por [uv](https://docs.astral.sh/uv/) (`source .venv/bin/activate`) o, de forma más robusta, ejecutamos el arranque con `uv run` para que `serverless-offline` herede el Python del entorno virtual.
    ```bash
    uv run npm exec serverless offline start
    ```

    -   Si prefieres `npx`, también funciona:
    ```bash
    uv run npx serverless offline start
    ```

    - Cargamos archivo `config.json` ubicado en la carpeta `/resources` a S3-local con el script `/resources/manage_resources.py`.
    ```bash
    uv run manage_resources.py
    ```

    -   Invocamos a la función Lambda que da inicio al pipeline.
    ```bash
    curl -X POST http://localhost:3000/dev/args_mixer
    ```

#### Resultados

Los resultados del pipeline son guardados en una tabla de DynamoDB Local llamada `results_dynamodb`.

En el directorio `resources/results_process/` se maneja todo lo relacionado con la analítica de los resultados. 

Para poder extraer los datos de la tabla de dynamoDB instalamos `awscli` con el siguiente comando para macOS:
```bash
brew install awscli
```

`awscli` requiere configuración, la cual en nuestro caso será dummy, ya que no se conecta a AWS real. Ejecutamos el siguiente comando para configurar `awscli`:
```bash
aws configure
```
- AWS Access Key ID: S3RVER
- AWS Secret Access Key: S3RVER
- Default region name: us-east-1

Posteriormente, para extraer los datos de DynamoDB y guardarlos en un formato legible como JSON, CSV o Parquet ejecutamos el script `results.sh` ubicado en el mismo directorio:
```bash 
sh results.sh
```
> Esto generará los archivos `results.json`, `results.parquet` y `results.csv` con los datos extraidos de la DynamoDB, incluyendo las métricas de cada combinación de decodificador y automorfismo.
---

