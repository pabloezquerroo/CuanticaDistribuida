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

La arquitectura del proyecto está diseñada para ejecutar simulaciones de corrección de errores cuánticos de forma masivamente paralela, utilizando un sistema de Lambdas y servicios de AWS. El diseño se basa en un fan-out de dos niveles para distribuir la carga de trabajo: el **orquestador** genera los datos de simulación, un **dispatcher (`nmc_worker`)** distribuye las tareas, y múltiples **workers (`args_worker`)** ejecutan los cálculos finales.

Los componentes se comunican de forma asíncrona a través de S3 para el almacenamiento de datos de las simulaciones y DynamoDB para el almacenamiento de los argumentos, la coordinación y el estado.

### Componentes del Sistema

-   **`args_mixer.py` (Lambda 1)**
    -   **Disparador**: Subida de un archivo `config.json` a un bucket de S3.
    -   **Función**: Lee la configuración, genera todas las combinaciones de parámetros de simulación y las agrupa en lotes. Cada lote se guarda como un ítem en la tabla `args_dynamodb`.
    -   **Salida**: Invoca al `orchestrator.py`.

-   **`orchestrator.py` (Lambda 2)**
    -   **Función**: Prepara los datos para la simulación. Genera los arrays de detectores y observables en lotes de tamaño `NMC_batch_size`.
    -   Por cada lote de datos, realiza dos acciones:
        1.  Guarda los arrays en un archivo JSON en S3.
        2.  Crea una entrada en la tabla `samples_dynamodb` con el ID del lote (`id_nmc_batch`), la ruta al JSON en S3 (`s3_data_path`) y un contador (`workers_completed`).
    -   **Salida**: Invoca a `nmc_worker.py` por cada lote de datos generado.

-   **`nmc_worker.py` (Lambda 3)**
    -   **Función**: Actúa como un dispatcher de segundo nivel. Su objetivo es distribuir las combinaciones de argumentos contra un lote de datos de simulación.
    -   Recibe un `id_nmc_batch`.
    -   Invoca una instancia de `args_worker.py` por cada lote de argumentos que deba procesarse, pasando el `id_nmc_batch` y el `id_batch_arguments` correspondiente.

-   **`args_worker.py` (Lambda 4)**
    -   **Función**: Es el worker principal que ejecuta la simulación.
    -   Recibe `id_nmc_batch` y `id_batch_arguments`.
    -   Lee los datos de simulación (detectores/observables) desde S3 (usando la ruta de `samples_dynamodb`) y el lote de argumentos desde `args_dynamodb`.
    -   Ejecuta el cálculo de QEC para cada argumento del lote.
    -   Guarda el resultado final en una base de datos de resultados (DB).
    -   **Coordina la limpieza**: Incrementa el contador `workers_completed` en `samples_dynamodb`. Si es el último worker para ese `id_nmc_batch`, borra el archivo de datos temporales de S3 y la entrada correspondiente en `samples_dynamodb`.

### Servicios AWS
-   **Lambda**: Ejecucion de las diferentes funciones que conforman la arquitectura distribuida.
-   **S3**: Almacenamineto de las variables de configuración iniciales (`config.json`) y los datos temporales de simulación (detectores/observables).
-   **DynamoDB**: Almacenamiento de combinaciones de argumentos para los decoders (`args_dynamodb`), información referente a los datos temporales de la simulación (`samples_dynamodb`).
-   **DB de Resultados**: Base de datos final para almacenar los resultados de las simulaciones. _Temporalmente se usa DynamoDB(`results_dynamoDB`)_

### Flujo de Ejecución
1.  **Inicio**: Un usuario sube el archivo `config.json` a S3, lo que dispara `args_mixer`.
2.  **`args_mixer`**: Genera las combinaciones de argumentos y las guarda en `args_dynamodb`. Invoca al `orchestrator`.
3.  **`orchestrator`**: Genera un lote de datos de simulación (ej. 1000 NMCs), lo guarda en S3 y crea una entrada de seguimiento en `samples_dynamodb`. Invoca a `nmc_worker` con el ID del lote de datos (`id_nmc_batch`).
4.  **`nmc_worker`**: Recibe el `id_nmc_batch`. Invoca a N instancias de `args_worker`, una por cada lote de argumentos (`id_batch_arguments`) que se debe probar contra ese lote de datos.
5.  **`args_worker`**: Cada instancia lee sus argumentos (`args_dynamodb`) y los datos de simulación (S3), ejecuta los cálculos y guarda el resultado en la BD final.
6.  **Limpieza**: El último `args_worker` de un lote de datos limpia los datos temporales de S3 y `samples_dynamodb`.
7.  El proceso se repite desde el paso 3 para todos los lotes de datos que el orquestador necesite generar.

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

5. **Ejecutar pipeline:**
    -   Utilizamos el framework [serverless](https://www.serverless.com/).

    -  Instalamos plugins:
        - Plugin [serverless offline](https://www.serverless.com/plugins/serverless-offline).
        ```bash
        npm install serverless-offline --save-dev
        ```
        - Plugin [serverless-s3-local](https://www.serverless.com/plugins/serverless-s3-local) .
        ```bash
        npm install serverless-s3-local --save-dev
        ```

    - Lanzamos entorno virtual generado por [uv](https://docs.astral.sh/uv/) (`source .venv/bin/activate`).
    ```bash
    serverless offline start
    ```

    - Cargamos archivo `config.json` desde la carpeta `/Descargas` a S3-local con el script `/resources/manage_resources.py`.
    ```bash
    uv run manage_resources.py
    ```

    -   Invocamos a la función Lambda que da inicio al pipeline.
    ```bash
    curl -X POST http://localhost:3000/dev/args_mixer
    ```

#### Resultados
Los resultados del pipeline son guardados en una tabla de DynamoDB Local llamada `results_dynamodb`.

En el directorio `resources/results_process/` se maneja todo lo relacionado con la analítica de los resultados. Para poder extraer los datos de la tabla a parquet ejecutamos el siguiente script:
```bash 
sh results.sh
```
> Esto generará los archivos `results.json` y `results.parquet` con los datos extraidos de la DynamoDB.
---

