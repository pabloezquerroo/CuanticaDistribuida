
""" 
Lambda que realiza las siguientes funciones:
1. Recibe el numero de combinaciones de argumentos que hay en DynamoDB (args_size).
2. Lee de S3 la configuración (código, p, NMCs, NMC_batch_size, args_batch_size).
3. Genera los arrays de detectores y observables. Cada vez que se completa un lote (NMC_batch_size), se realizan los siguientes pasos:
    - Guarda en S3 los arrays en un JSON 
    - Guarda en samples_dynamodb información referente al JSON. (s3_data_path, workers_completed)
    - Se invoca un nmc_worker pasando id_nmc_batch y args_size.
"""
import boto3
import os
import json
from IBM_STIM import create_bivariate_bicycle_codes, build_circuit, select_configuration


import logging
logging.basicConfig(level=logging.INFO)

import dotenv # TODO: Cambiar por variables de entorno en AWS Lambda
dotenv.load_dotenv()

#region S3 Functions
def get_connection_s3(): # ? endpoint_url, aws_access_key_id, aws_secret_access_key son configuración necesaria para Backblaze. En AWS se configuran automáticamente.
    return boto3.client(
        's3',
        endpoint_url=os.getenv('S3_ENDPOINT_URL'),
        region_name=os.getenv('AWS_DEFAULT_REGION'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
    )

def get_config_from_s3():
    try:
        s3 = get_connection_s3()
        response = s3.get_object(Bucket=os.getenv('S3_BUCKET_NAME'), Key=f"{os.getenv('S3_CONFIG_FILE_PATH')}")
        dict_config = json.loads(response['Body'].read().decode('utf-8'))
        logging.info("Configuration loaded from S3.")
        return dict_config
    except Exception as e:
        logging.error(f"Error loading configuration from S3: {e}")
        return None

def upload_samples_to_s3(json_data, s3_path):
    try:
        s3 = get_connection_s3()
        s3.put_object(
            Bucket=os.getenv('S3_BUCKET_NAME'),
            Key=s3_path,
            Body=json.dumps(json_data).encode('utf-8'),
            ContentType='application/json'
        )
        logging.info("Data uploaded to S3.")
    except Exception as e:
        logging.error(f"Error uploading data to S3: {e}")
#endregion

#region DynamoDB Functions
def get_connection_dynamodb():
    return boto3.resource(
        'dynamodb',
        region_name=os.getenv('AWS_DEFAULT_REGION'),  # obligatoria aunque no se use realmente
        endpoint_url=os.getenv('DYNAMODB_ENDPOINT_URL')  # importante para local
    )

def create_table_if_not_exists(table_name):
    try:
        logging.info(f"Checking if table '{table_name}' exists...")
        dynamodb = get_connection_dynamodb()
        table = dynamodb.Table(table_name)
        table.load()
        logging.info(f"Table '{table_name}' already exists.")
    except dynamodb.meta.client.exceptions.ResourceNotFoundException:
        logging.info(f"Table '{table_name}' does not exist. Creating...")
        table = dynamodb.create_table(
            TableName=table_name,
            KeySchema=[
                {'AttributeName': 'id_nmc_batch', 'KeyType': 'HASH'}
            ],
            AttributeDefinitions=[
                {'AttributeName': 'id_nmc_batch', 'AttributeType': 'S'}
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 5,
                'WriteCapacityUnits': 5
            }
        )
        table.wait_until_exists()
        logging.info(f"Table '{table_name}' created successfully.")
    return table

def upload_samples_info_to_dynamodb(id_nmc_batch, s3_path):
    try:
        table = create_table_if_not_exists(os.getenv('DYNAMODB_SAMPLES_TABLE_NAME'))

        table.put_item(
            Item={
                'id_nmc_batch': id_nmc_batch,
                's3_data_path': s3_path,
                'workers_completed': 0,
            }
        )
        logging.info("Data uploaded to DynamoDB.")
    except Exception as e:
        logging.error(f"Error uploading data to DynamoDB: {e}")
#endregion

def lambda_handler(event, context):
    simulation_config = get_config_from_s3()
    if not simulation_config:
        logging.error("No configuration found in S3. Exiting.")
        return

    # Validate list lengths
    if len(simulation_config["NMCs"]) != len(simulation_config["p"]):
        logging.error("Error: The length of NMCs and p does not match.")
        return

    for code_val in simulation_config["codeConfig"]:
        for p_val_index, p_val in enumerate(simulation_config["p"]):
            logging.info(f"--- Processing codeConfig={code_val}, p={p_val} ---")
            # Build quantum code
            config = select_configuration(code_val)
            ell, m = config["ell"], config["m"]
            a1, a2, a3 = config["a"]
            b1, b2, b3 = config["b"]
            d = config["d"]
            A_x_pows, A_y_pows = [a1], [a2, a3] 
            B_x_pows, B_y_pows = [b2, b3], [b1]
            code, A_list, B_list = create_bivariate_bicycle_codes(ell, m, A_x_pows, A_y_pows, B_x_pows, B_y_pows)
            
            # Build circuit
            circuit = build_circuit(code, A_list, B_list, p=p_val, num_repeat=d, z_basis=False, use_both=False)

            # Initialize lists for storing results
            batch_detectors = []
            batch_observables = []

            total_nmcs = simulation_config["NMCs"][p_val_index]
            size_batch = simulation_config["NMCs_batch_size"]

            for i in range(1, total_nmcs + 1):
                logging.info(f"Simulating {i} of {total_nmcs}...")
                sampler = circuit.compile_detector_sampler()
                detectors, observables = sampler.sample(1, separate_observables=True)                    
               
                batch_detectors.append(detectors[0].tolist())
                batch_observables.append(observables[0].tolist())
                
                if i % size_batch == 0:
                    batch_counter = i // size_batch

                    if batch_counter != 1 and batch_counter != 2: # ! Para pruebas locales. Eliminar si se quieren ejecutar todos los lotes.
                        continue
                    
                    logging.info(f"Saving batch {batch_counter}...")

                    # Save samples of the batch.
                    results_for_batch = {
                        "detectors": batch_detectors,
                        "observables": batch_observables
                    }

                    p_str = f"{p_val}".replace(".", "c")
                    id_nmc_batch = f"nmc_{code_val}_{p_str}_{batch_counter}" # Example: nmc_72_0c001_1
                    s3_path = os.path.join(f"{os.getenv('S3_DETECTORS_OBSERVABLES_PATH')}", f"code_{code_val}/p_{p_str}/batch_{batch_counter}.json")
                    upload_samples_to_s3(results_for_batch, s3_path)
                    logging.info(f"Batch {batch_counter} results saved to S3 at {s3_path}")
                    
                    # Save batch info in DynamoDB samples_dynamodb.
                    upload_samples_info_to_dynamodb(id_nmc_batch, s3_path)

                    # TODO: Invocar a la lambda nmc_worker con el id_nmc_batch y args_size

                    batch_detectors = []
                    batch_observables = []

# Simular lambda con payload args_size = 100
if __name__ == "__main__":
    args_size = 100
    lambda_handler({"args_size": args_size}, None)
