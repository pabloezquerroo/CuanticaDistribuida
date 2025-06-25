# Argumentos de los Decoders

En este archivo se describen los diferentes valores que pueden tomar los argumentos de los decoders: **BP**, **BPOSD** y **BPLSD**.

---

## Argumentos Comunes

Estos argumentos están presentes en los tres decoders:

- `pcm` (Union[np.ndarray, spmatrix]) – Matriz de comprobación de paridad del código.
- `error_rate` (Optional[float], optional) – Tasa de error inicial, por defecto None.
- `error_channel` (Optional[List[float]], optional) – Probabilidades de error por bit, por defecto None.
- `max_iter` (Optional[int], optional) – Número máximo de iteraciones, por defecto 0 (adaptativo).
- `bp_method` (Optional[str], optional) – Método de belief propagation: ‘product_sum’ o ‘minimum_sum’, por defecto ‘minimum_sum’.
- `ms_scaling_factor` (Optional[float], optional) – Factor de escala para el método minimum sum, por defecto 1.0.
- `schedule` (Optional[str], optional) – Método de scheduling: ‘parallel’, ‘serial’ o ‘serial_relative’(no usar), por defecto ‘parallel’.
- `omp_thread_count` (Optional[int], optional) – Número de hilos OpenMP, por defecto 1.
- `serial_schedule_order` (Optional[List[int]], optional) – Orden personalizado para scheduling serial, por defecto None.

---

## Argumentos Específicos

### BP (Belief Propagation)
- `random_schedule_seed` (Optional[int], optional) – Semilla para el orden serial aleatorio, por defecto 0.
- `input_vector_type` (str, optional) – Tipo de vector de entrada: ‘syndrome’, ‘received_vector’ o ‘auto’. Solo necesario si la matriz de paridad es cuadrada.

### BPOSD (Belief Propagation Ordered Statistics Decoding)
- `random_serial_schedule` (Optional[int], optional) – Usar orden serial aleatorio, por defecto False.
- `osd_method` (int, optional) – Método OSD: ‘OSD_0’, ‘OSD_E’ o ‘OSD_CS’.
- `osd_order` (int, optional) – Orden OSD, por defecto 0. (Si osd_method= OSD_CS -> osd_order < 20)

### BPLSD (Belief Propagation List Decoding)
- `random_schedule_seed` (Optional[int], optional) – Semilla para el orden serial aleatorio, por defecto 0.
- `bits_per_step` (int, optional) – Número de bits añadidos por paso en LSD. Si no se especifica, se usa la longitud del bloque.
- `lsd_method` (str, optional) – Método LSD: ‘LSD_0’, ‘LSD_E’ o ‘LSD_CS’, por defecto ‘LSD_0’.
- `lsd_order` (int, optional) – Orden del algoritmo LSD, debe ser ≥ 0, por defecto 0. (Si lsd_method= LSD_CS -> lsd_order < 20)

---