# CuanticaDistribuida

Repositorio de Trabajo de Fin de Máster sobre corrección de errores cuánticos en arquitectura cloud distribuida.

---

## Índice

- [Documentación y Recursos](#documentación-y-recursos)
- [Estructura del Código](#estructura-del-código)

---

## Documentación y Recursos

- **Introducción a QEC:**  
  https://arxiv.org/abs/2304.08678

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

---

## Estructura del Código

- **test_v2.py**  
  Script para pruebas locales con la versión 2 de la librería QEC.
- **IBM_STIM.py, dem_to_matrices.py, utils.py**  
  Utilidades para generación de ruido, construcción de circuitos cuánticos.  
  *No necesarios para la decodificación.*

---

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
predicted_observables = _bp.decode(detectors[0])
predicted_observables_lsd = _bplsd.decode(detectors[0])
predicted_observables_osd = _bposd.decode(detectors[0])
```

Y la comprobación de los errores lógicos es:

```python
logical_error = (observable_mat @ predicted_observables + observables) % 2
logical_error_lsd = (observable_mat @ predicted_observables_lsd + observables) % 2
logical_error_osd = (observable_mat @ predicted_observables_osd + observables) % 2
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
