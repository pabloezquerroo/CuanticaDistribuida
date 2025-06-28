import stim
import numpy as np
import boto3
import json
import os

# Asumimos que las funciones necesarias están en IBM_STIM.py
from IBM_STIM import select_configuration, create_bivariate_bicycle_codes, build_circuit

def get_config_from_s3(bucket_name, file_key):
    # --- Inicio: Bloque para pruebas locales ---
    print("ADVERTENCIA: Usando configuración local. Para producción, conectar a S3.")
    config = {
        "codeConfig": [72, 90],  # Posibles codigos: 72, 90, 108, 144, 288, 784
        "p": [0.001, 0.002],  # Posibles tasas de error fisicas: 0.001, 0.002, 0.003, 0.004, 0.005
        "NMCs": [10, 10],
        "NMCs_batch": 10,  # Numero de iteraciones por lote
    }
    return config
    # --- Fin: Bloque para pruebas locales ---

    # --- Inicio: Bloque para S3 (descomentar para producción) ---
    # try:
    #     s3 = boto3.client('s3')
    #     response = s3.get_object(Bucket=bucket_name, Key=file_key)
    #     content = response['Body'].read().decode('utf-8')
    #     config = json.loads(content)
    #     return config
    # except Exception as e:
    #     print(f"Error al leer de S3: {e}")
    #     return None
    # --- Fin: Bloque para S3 ---

def main():
    # Parámetros para leer la configuración (actualmente no usados)
    s3_bucket = "CuanticaDistribuida-Bucket"
    s3_file = "config/config.json"

    config_data = get_config_from_s3(s3_bucket, s3_file)

    if not config_data:
        print("No se pudo obtener la configuración. Saliendo.")
        return

    
    # Crear el directorio para los resultados si no existe
    results_dir = "samplers_dir"
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)
        print(f"Directorio '{results_dir}' creado.")

    # Iteramos sobre las configuraciones de código y tasas de error
    for code_config_val in config_data["codeConfig"]:
        for p_val_index, p_val in enumerate(config_data["p"]):
            print(f"--- Procesando codeConfig={code_config_val}, p={p_val} ---")

            # 1. Construir el código cuántico
            config = select_configuration(code_config_val)
            ell, m = config["ell"], config["m"]
            a1, a2, a3 = config["a"]
            b1, b2, b3 = config["b"]
            d = config["d"]

            A_x_pows, A_y_pows = [a1], [a2, a3]
            B_x_pows, B_y_pows = [b2, b3], [b1]
            code, A_list, B_list = create_bivariate_bicycle_codes(ell, m, A_x_pows, A_y_pows, B_x_pows, B_y_pows)

            # 2. Construir el circuito y el modelo de error del detector
            circuit = build_circuit(code, A_list, B_list, p=p_val, num_repeat=d, z_basis=False, use_both=False)
            
            for i in range(config_data["NMCs"][p_val_index]):
                print(f"Realizando simulación {i+1} de {config_data["NMCs"][p_val_index]}...")
                # 3. Compilar el sampler del detector
                sampler = circuit.compile_detector_sampler()
            
                # 4. Obtener una muestra
                # El primer argumento de sample() es el número de "shots"
                detectors, observables = sampler.sample(1, separate_observables=True)
                print("Detectors:", detectors[0])
                print("Observables:", observables[0])

                # Guardar las muestras
                p_str = f"{p_val}".replace(".", "comma")
                detector_filename = os.path.join(results_dir, f"detectors_{code_config_val}_{p_str}_{i}.npy")   
                observable_filename = os.path.join(results_dir, f"observables_{code_config_val}_{p_str}_{i}.npy")
                
                np.save(detector_filename, detectors[0])
                np.save(observable_filename, observables[0])

        print(f"{config_data['NMCs'][p_val_index]} muestras guardadas para codeConfig={code_config_val}, p={p_str} en '{results_dir}'\n")

if __name__ == "__main__":
    main()
