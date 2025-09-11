""" 
Lambda que realiza las siguientes funciones:
1. Recibe el número de lotes de combinaciones de argumentos guardados en DynamoDB (number_of_args_combinations_batches).
2. Lee de S3 el archivo de S3 (código, p, NMCs, NMC_batch_size, args_batch_size).
3. Genera los arrays de detectores y observables. Cada vez que se completa un lote (NMC_batch_size), se realizan los siguientes pasos:
    - Guarda en S3 los arrays en un JSON 
    - Guarda en samples_dynamodb información referente al JSON. (s3_data_path, workers_completed)
    - Se invoca un nmc_worker pasando id_nmc_batch y number_of_args_combinations_batches.
"""

import os
import json
import boto3
from botocore.exceptions import ClientError
import requests

from src.libs.IBM_STIM import create_bivariate_bicycle_codes, build_circuit, select_configuration

import logging
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)
logging.basicConfig(level=logging.INFO)

import dotenv
# dotenv.load_dotenv()

#region S3 Functions
def get_connection_s3():
    """Create and return a Boto3 S3 client.

    The configuration (endpoint_url, aws_access_key_id, aws_secret_access_key)
    is loaded from environment variables. These are necessary for providers like
    Backblaze. For AWS, many of these are configured automatically when running
    in an AWS environment.

    Returns:
        boto3.Client: An S3 client object.
    """
    return boto3.client(
        's3',
        endpoint_url=os.getenv('S3_ENDPOINT_URL'),
        region_name=os.getenv('AWS_DEFAULT_REGION'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
    )

def get_config_from_s3(bucket_name, config_file_path):
    """Retrieve a configuration file from an S3 bucket.

    Args:
        bucket_name (str): The name of the S3 bucket.
        config_file_path (str): The path to the configuration file within the bucket.

    Returns:
        dict: A dictionary with the configuration, or None if an error occurs.
              For example:
              {
                  "codeConfig": [72, 90],      # Possible codes: 72, 90, 108, 144, 288, 784
                  "p": [0.001, 0.002],         
                  "NMCs": [100, 100],
                  "NMCs_batch_size": 10,       # Size of the NMCs batch
                  "args_batch_size": 10        # Size of the args batch
              }
    """
    try:
        s3 = get_connection_s3()
        response = s3.get_object(Bucket=bucket_name, Key=config_file_path)
        dict_config = json.loads(response['Body'].read().decode('utf-8'))
        logging.info("Configuration loaded from S3.")
        return dict_config
    except ClientError as e:
        logging.error(f"Error loading configuration from S3: {e}")
        raise RuntimeError("Error loading configuration from S3") from e

def upload_samples_to_s3(batch_data, s3_path):
    """Upload a batch of samples to an S3 bucket.

    Args:
        batch_data (dict): The arrays of observables and detectors to upload.
        s3_path (str): The path to the S3 bucket where the arrays will be uploaded.

    Returns:
        None
    """
    try:
        s3 = get_connection_s3()
        s3.put_object(
            Bucket=os.getenv('S3_BUCKET_NAME'),
            Key=s3_path,
            Body=json.dumps(batch_data).encode('utf-8'),
            ContentType='application/json'
        )
        logging.info("Data uploaded to S3.")
    except ClientError as e:
        logging.error(f"Error uploading data to S3: {e}")
        raise RuntimeError("Error uploading data to S3") from e
#endregion

#region DynamoDB Functions
def get_connection_dynamodb():
    return boto3.resource(
        'dynamodb',
        region_name=os.getenv('AWS_DEFAULT_REGION'),
        endpoint_url=os.getenv('DYNAMODB_ENDPOINT_URL'),
        aws_access_key_id='dummy',
        aws_secret_access_key='dummy'
    )

def create_table_samples_dynamodb_if_not_exists(dynamodb, table_name):
    """Create a DynamoDB table samples_dynamodb if it does not exist.
    Args:
        table_name (str): The name of the DynamoDB table to create.
    Returns:
        table: The created table.
    """
    try:
        logging.info(f"Checking if table '{table_name}' exists...")
        table = dynamodb.Table(table_name)
        table.load()
        logging.info(f"Table '{table_name}' already exists.")
        return table
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            logging.warning(f"Table '{table_name}' does not exist. Creating...")
            try:
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
            except ClientError as e2:
                logging.error(f"Error creating table '{table_name}': {e2}")
                raise RuntimeError("Error creating table") from e2
        else:
            logging.error(f"Unexpected error when checking table '{table_name}': {e}")
            raise RuntimeError("Error checking table existence") from e

def upload_samples_info_to_dynamodb(id_nmc_batch, s3_path):
    """Upload information for accessing a batch of NMC samples to DynamoDB.

    Args:
        id_nmc_batch (str): The ID of the NMC batch.
        s3_path (str): The path to the S3 bucket where the samples are stored.

    Returns:
        None
    """
    try:
        if os.getenv('DYNAMODB_SAMPLES_TABLE_NAME') is None:
            raise ValueError("DYNAMODB_SAMPLES_TABLE_NAME is not defined in environment variables")
        
        dynamodb = get_connection_dynamodb()
       
        # ! SOLO PARA PRUEBAS LOCALES - Comprobación de que la tabla existe o se crea si no existe.
        table = create_table_samples_dynamodb_if_not_exists(dynamodb, os.getenv('DYNAMODB_SAMPLES_TABLE_NAME')) 
        
        # ! EN PRODUCCIÓN - Se asume que la tabla ya existe.
        # table = dynamodb.Table(os.getenv('DYNAMODB_SAMPLES_TABLE_NAME'))

        item = {
            'id_nmc_batch': id_nmc_batch,
            's3_data_path': s3_path,
            'workers_completed': 0,
        }
        table.put_item(Item=item)
        logging.info("Data uploaded to DynamoDB.")
    except ClientError as e:
        logging.error(f"Error uploading data to DynamoDB: {e}")
        raise RuntimeError("Error uploading data to DynamoDB") from e
#endregion

#region Lambda Functions
# def get_connection_lambda():
#     return boto3.client('lambda',
#         region_name=os.getenv('AWS_DEFAULT_REGION'),
#         endpoint_url=os.getenv('LAMBDA_ENDPOINT_URL'),
#         aws_access_key_id='dummy',
#         aws_secret_access_key='dummy'
#     )

def invoke_lambda(payload, lambda_name):
    """
    Invoke a Lambda function either locally or in AWS.

    Args:
        payload (dict): The payload to send to the Lambda function.
        lambda_name (str): The name of the Lambda function to invoke.
    Returns:
        dict: The response from the Lambda function.
    """
    is_offline = os.getenv("IS_OFFLINE", "false").lower() == "true"

    if is_offline:
        url = f"{os.getenv('LAMBDA_ENDPOINT_URL')}{lambda_name}"
        try:
            logging.info(f"[OFFLINE] Invoking lambda '{lambda_name}' at {url} with payload: {payload}")
            response = requests.post(url, json=payload)
            logging.info(f"[OFFLINE] Lambda invoked successfully. HTTP code: {response.status_code}")
            return {"status": "invoked"}
        except requests.RequestException as e:
            logging.error(f"[OFFLINE] Error invoking lambda via HTTP: {e}")
            raise RuntimeError("Error invoking lambda locally") from e
    else:
        try:
            logging.info(f"[AWS] Invoking lambda '{lambda_name}' via boto3 with payload: {payload}")
            lambda_client = boto3.client("lambda")
            response = lambda_client.invoke(
                FunctionName=lambda_name,
                InvocationType='Event',
                Payload=json.dumps(payload)
            )
            logging.info(f"[AWS] Lambda invoked. Status code: {response['StatusCode']}")
            return response
        except ClientError as e:
            logging.error(f"[AWS] Error invoking lambda via boto3: {e}")
            raise RuntimeError("Error invoking lambda on AWS") from e
    
#endregion

def lambda_handler(event, context):
    try:
        logging.info(f"Event received in orchestrator lambda_handler")

        # Set seed for reproducibility if SEED_MODE is enabled
        seed = None
        if os.getenv('SEED_MODE', '').lower() == 'true':
            seed = int(os.getenv('SEED'))
            logging.info(f"SEED_MODE is enabled. Initial seed: {seed}")           

        if "body" in event: # if the event comes from http (Local testing)
            received_event = json.loads(event["body"])
        else:               # if the event comes from AWS Lambda
            received_event = event
        number_of_args_combinations_batches = received_event.get("number_of_args_combinations_batches")
        if number_of_args_combinations_batches < 1:
            logging.error("No args combinations batches to process. Exiting.")
            return {"status": "failed"}

        simulation_config = get_config_from_s3(os.getenv('S3_BUCKET_NAME'), os.getenv('S3_CONFIG_FILE_PATH'))
        if not simulation_config:
            logging.error("No configuration found in S3. Exiting.")
            return {"status": "failed"}

        # Validate list lengths
        if len(simulation_config["NMCs"]) != len(simulation_config["p"]):
            logging.error("Error: The length of NMCs and p does not match.")
            return {"status": "failed"}

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
                    # logging.info(f"Simulating {i} of {total_nmcs}...")
                    sampler = circuit.compile_detector_sampler(seed=seed+i) # Increment seed for each simulation if seed is set
                    detectors, observables = sampler.sample(1, separate_observables=True)                    
                
                    batch_detectors.append(detectors[0].tolist())
                    batch_observables.append(observables[0].tolist())
                    
                    if i % size_batch == 0:     

                        batch_counter = i // size_batch

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

                        if not os.getenv('LAMBDA_NMC_WORKER_NAME'):
                            raise ValueError("LAMBDA_NMC_WORKER_NAME no está definida en las variables de entorno")
                        
                        event = {
                            'id_nmc_batch': id_nmc_batch,
                            'number_of_args_combinations_batches': number_of_args_combinations_batches
                            }
                        response = invoke_lambda(event, os.getenv('LAMBDA_NMC_WORKER_NAME'))
                        logging.info(f"nmc_worker invoked with response: {response}")
                    
                        batch_detectors = []
                        batch_observables = []
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Error in orchestrator lambda_handler: {e}") 
        return {"status": "failed"}

# if __name__ == "__main__":
#     number_of_args_combinations_batches = 1 # ! Para pruebas sin eventos
#     try:
#         logging.info(f"Executing orchestrator.py locally...")
#         lambda_handler({"number_of_args_combinations_batches": number_of_args_combinations_batches}, None)
#         logging.info("Local execution finished.")
#     except Exception as e:
#         logging.error(f"Error in orchestrator.py: {e}")
#         raise RuntimeError("Error in orchestrator.py") from e
