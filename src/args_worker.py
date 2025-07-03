
""" 
Lambda que realiza las siguientes funciones:
1. Recibe number_args_batches, args_range_ini, args_range_end, id_args_batch, e id_nmc_batch.
2. Lee de S3 la configuración de simulación (código, p, NMCs, NMC_batch_size, args_batch_size).
3. Lee de samples_dynamodb la ruta a S3 y lee de S3 los arrays de detectores y observables.
4. Actualiza el campo workers_completed + 1.
    Si workers_completed >= number_args_batches => 
        - Se elimina el objeto de S3 al que hace referencia id_nmc_batch.
        - Se elimina la entrada id_nmc_batch de samples_dynamodb
5. Lee de args_dynamodb los argumentos de su lote (args_range_ini, args_range_end)
6. Realiza la ejecución completa con a partir de la información recibida.
7. Guarda en una BD los resultados con id_args_batch e id_nmc_batch.
"""