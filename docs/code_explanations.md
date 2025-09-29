# Arquitectura para Simulaciones de Monte Carlo Distribuidas

Este documento explica la lógica y las decisiones de diseño detrás de la arquitectura para ejecutar simulaciones de Monte Carlo de forma distribuida, garantizando la validez científica de los resultados.

## La Idea Clave: ¿Por qué el Orquestador?

La arquitectura distribuida de este proyecto se basa en un principio fundamental para garantizar la validez científica de los resultados. La pregunta central es: **¿Por qué el orquestador debe generar todos los datos (errores) en lugar de que cada worker genere los suyos?**

La respuesta se basa en dos puntos críticos:

1.  **Comparación Justa (Validez Científica):** El objetivo de una simulación de Monte Carlo es comparar el rendimiento de diferentes decodificadores. Para que la comparación sea científicamente válida, todos los decodificadores deben enfrentarse **exactamente al mismo conjunto de errores aleatorios**. Si cada worker generara sus propios errores, sería imposible saber si un mejor resultado se debe a un decodificador superior o a un conjunto de errores más "fácil". El orquestador asegura que todos los workers trabajen sobre un "desafío" común.

2.  **Limitación Técnica de `stim`:** La librería `stim`, utilizada para generar los errores, tiene una característica crucial: la función `sample()` no es divisible. Una única llamada a `sample(shots=1000)` **no produce el mismo resultado** que diez llamadas a `sample(shots=100)`, incluso con la misma semilla. Esto significa que no podemos simplemente pedir a cada worker que genere una porción de los datos. Si lo hiciéramos, todos generarían las mismas muestras una y otra vez, invalidando la simulación.

Por estas razones, la única arquitectura correcta es:

-   El **Orquestador** realiza una única llamada masiva a `sample()` para crear el dataset completo.
-   Los **Workers** reciben una porción de este dataset pre-generado para procesarla con su decodificador.

Esta separación de roles es la piedra angular del diseño.

## El Flujo de Trabajo Detallado

Como hemos visto, la generación de datos debe ser centralizada. El flujo de trabajo se divide en dos fases claras: la del Orquestador y la de los Workers.

### Fase 1: El Orquestador (Generación de Datos)

El Orquestador es el responsable de crear el "desafío" común para todos los workers siguiendo estos pasos:

1.  **Compilación del Sampler:** Se compila el circuito de `stim`. Opcionalmente, se puede proporcionar una semilla (`seed`) para que la simulación sea reproducible. Si no se especifica una semilla, cada ejecución del orquestador generará un conjunto de errores completamente nuevo y no determinista. La reproducibilidad es útil para la depuración, pero no es estrictamente necesaria para una simulación final.

2.  **Generación Única y Masiva:** Se realiza **una única llamada** a `sampler.sample(shots=N)`, donde `N` es el número total de iteraciones de Monte Carlo (e.g., 10^6). Este es el paso más crítico. Como se explica en la documentación de `stim`:

    > CAUTION: simulation results *MAY NOT* be consistent if you vary how many shots are taken. For example, taking 10 shots and then 90 shots will give different results from taking 100 shots in one call.

    Esta llamada única es la única forma de generar un conjunto de datos coherente y científicamente válido debido a las optimizaciones internas de `stim`.

3.  **Almacenamiento Centralizado:** Los datos generados (`detectors` y `observables`) se guardan en un único fichero (por ejemplo, un `.npz` de NumPy) en una ubicación compartida.

### Fase 2: Los Workers (Procesamiento Distribuido)

Una vez que los datos están listos, el Orquestador invoca a los Workers:

1.  **Invocación:** El Orquestador divide el trabajo en lotes. A cada Worker se le asigna un rango de índices del fichero de datos (e.g., "procesa las muestras 1000 a 1999").

2.  **Cómputo Determinista:** El Worker ejecuta las siguientes acciones:
    *   **Nunca** llama a `.sample()`. Su trabajo no es generar datos.
    *   Descarga el fichero de datos.
    *   Carga los arrays `detectors` y `observables` en memoria.
    *   Aplica el algoritmo de decodificación **únicamente** sobre la porción de los arrays que le fue asignada.
    *   Calcula sus resultados parciales (e.g., número de errores lógicos) y los reporta para su posterior agregación.

Esta arquitectura asegura que la simulación sea a la vez científicamente rigurosa, reproducible y computacionalmente eficiente.

## Funciones de STIM

```python
# stim.Circuit.compile_detector_sampler

# (in class stim.Circuit)
def compile_detector_sampler(
    self,
    *,
    seed: object = None,
) -> stim.CompiledDetectorSampler:
    """Returns an object that can batch sample detection events from the circuit.

    Args:
        seed: PARTIALLY determines simulation results by deterministically seeding
            the random number generator.

            Must be None or an integer in range(2**64).

            Defaults to None. When None, the prng is seeded from system entropy.

            When set to an integer, making the exact same series calls on the exact
            same machine with the exact same version of Stim will produce the exact
            same simulation results.

            CAUTION: simulation results *WILL NOT* be consistent between versions of
            Stim. This restriction is present to make it possible to have future
            optimizations to the random sampling, and is enforced by introducing
            intentional differences in the seeding strategy from version to version.

            CAUTION: simulation results *MAY NOT* be consistent across machines that
            differ in the width of supported SIMD instructions. For example, using
            the same seed on a machine that supports AVX instructions and one that
            only supports SSE instructions may produce different simulation results.

            CAUTION: simulation results *MAY NOT* be consistent if you vary how many
            shots are taken. For example, taking 10 shots and then 90 shots will
            give different results from taking 100 shots in one call.

    Examples:
        >>> import stim
        >>> c = stim.Circuit('''
        ...    H 0
        ...    CNOT 0 1
        ...    M 0 1
        ...    DETECTOR rec[-1] rec[-2]
        ... ''')
        >>> s = c.compile_detector_sampler()
        >>> s.sample(shots=1)
        array([[False]])
    """

# stim.CompiledDetectorSampler.sample

# (in class stim.CompiledDetectorSampler)
def sample(
    self,
    shots: int,
    *,
    prepend_observables: bool = False,
    append_observables: bool = False,
    separate_observables: bool = False,
    bit_packed: bool = False,
    dets_out: Optional[np.ndarray] = None,
    obs_out: Optional[np.ndarray] = None,
) -> Union[np.ndarray, Tuple[np.ndarray, np.ndarray]]:
    """Returns a numpy array containing a batch of detector samples from the circuit.

    The circuit must define the detectors using DETECTOR instructions. Observables
    defined by OBSERVABLE_INCLUDE instructions can also be included in the results
    as honorary detectors.

    Args:
        shots: The number of times to sample every detector in the circuit.
        separate_observables: Defaults to False. When set to True, the return value
            is a (detection_events, observable_flips) tuple instead of a flat
            detection_events array.
        prepend_observables: Defaults to false. When set, observables are included
            with the detectors and are placed at the start of the results.
        append_observables: Defaults to false. When set, observables are included
            with the detectors and are placed at the end of the results.
        bit_packed: Returns a uint8 numpy array with 8 bits per byte, instead of
            a bool_ numpy array with 1 bit per byte. Uses little endian packing.
        dets_out: Defaults to None. Specifies a pre-allocated numpy array to write
            the detection event data into. This array must have the correct shape
            and dtype.
        obs_out: Defaults to None. Specifies a pre-allocated numpy array to write
            the observable flip data into. This array must have the correct shape
            and dtype.

    Returns:
        A numpy array or tuple of numpy arrays containing the samples.

        if separate_observables=False and bit_packed=False:
            A single numpy array.
            dtype=bool_
            shape=(
                shots,
                num_detectors + num_observables * (
                    append_observables + prepend_observables),
            )
            The bit for detection event `m` in shot `s` is at
                result[s, m]

        if separate_observables=False and bit_packed=True:
            A single numpy array.
            dtype=uint8
            shape=(
                shots,
                math.ceil((num_detectors + num_observables * (
                    append_observables + prepend_observables)) / 8),
            )
            The bit for detection event `m` in shot `s` is at
                (result[s, m // 8] >> (m % 8)) & 1

        if separate_observables=True and bit_packed=False:
            A (dets, obs) tuple.
            dets.dtype=bool_
            dets.shape=(shots, num_detectors)
            obs.dtype=bool_
            obs.shape=(shots, num_observables)
            The bit for detection event `m` in shot `s` is at
                dets[s, m]
            The bit for observable `m` in shot `s` is at
                obs[s, m]

        if separate_observables=True and bit_packed=True:
            A (dets, obs) tuple.
            dets.dtype=uint8
            dets.shape=(shots, math.ceil(num_detectors / 8))
            obs.dtype=uint8
            obs.shape=(shots, math.ceil(num_observables / 8))
            The bit for detection event `m` in shot `s` is at
                (dets[s, m // 8] >> (m % 8)) & 1
            The bit for observable `m` in shot `s` is at
                (obs[s, m // 8] >> (m % 8)) & 1

    Examples:
        >>> import stim
        >>> c = stim.Circuit('''
        ...    H 0
        ...    CNOT 0 1
        ...    X_ERROR(1.0) 0
        ...    M 0 1
        ...    DETECTOR rec[-1] rec[-2]
        ... ''')
        >>> s = c.compile_detector_sampler()
        >>> s.sample(shots=1)
        array([[ True]])
    """
```