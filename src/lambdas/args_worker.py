""" 
Lambda que realiza las siguientes funciones:
1. Recibe number_of_args_combinations_batches, id_nmc_batch e id_batch_arguments.
2. Lee de samples_dynamodb la ruta a S3 y lee de S3 los arrays de detectores y observables.
3. Lee de args_dynamodb los argumentos de su lote (id_batch_arguments).
4. Para cada argumento:
   - Lee de S3 el automorfismo correspondiente (PCM, priors, row_perm).
   - Realiza la simulación completa con el automorfismo aplicado.
   - Guarda los resultados en DynamoDB (id_nmc_batch, id_arguments, id_automorphism, error_rate, codeConfig, decoder_type, corrected_patterns, Pl, time_max, time_av, arguments).
5. Actualiza el campo workers_completed + 1.
   Si workers_completed >= number_of_args_combinations_batches:
      - Se elimina el objeto de S3 al que hace referencia id_nmc_batch.
      - Se elimina la entrada id_nmc_batch de samples_dynamodb.
"""

import os
import json
import numpy as np  
import time  
import io
import pickle

from ldpc import BpDecoder  
from ldpc.bplsd_decoder import BpLsdDecoder
from ldpc import BpOsdDecoder  
from src.libs.dem_to_matrices import detector_error_model_to_check_matrices
from src.libs.IBM_STIM import create_bivariate_bicycle_codes, build_circuit, select_configuration

import boto3
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Key
import decimal

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

def get_automorphism_from_s3(auto_id, error_rate):
    """
    Download a specific automorphism from S3
    """
    s3 = get_connection_s3()
    error_rate_str = f"{error_rate:.6f}".rstrip('0').rstrip('.')
    
    automorphism_path = os.getenv('S3_AUTOMORPHISMS_PATH')
    s3_path = f"{automorphism_path}{error_rate_str}/auto_{auto_id}/data.pkl"
    logging.info(f"Downloading automorphism from S3: {s3_path}")
    buffer = io.BytesIO()
    try:
        s3.download_fileobj(
            os.getenv('S3_BUCKET_NAME'),
            s3_path,
            buffer
        )
        buffer.seek(0)
        data = pickle.load(buffer)

        # ! DEBUG: Pintar tipos de datos
        # logging.info(f"Type of data['ensemble']: {type(data['ensemble'])}, length: {len(data['ensemble'])}")
        # logging.info(f"Type of data['priors']: {type(data['priors'])}, length: {len(data['priors'])}")
        # logging.info(f"Type of data['row_perm']: {type(data['row_perm'])}, length: {len(data['row_perm'])}")
        # logging.info(f"PCM (ensemble) shape: {data['ensemble'].shape}")
        # logging.info(f"Priors shape: {data['priors'].shape}")
        # logging.info(f"Row_perm shape: {data['row_perm'].shape}")

        return data['ensemble'], data['priors'], data['row_perm']
    except ClientError as e:
        logging.error(f"Error downloading automorphism {auto_id}: {str(e)}")
        return None, None, None
    
def get_samples_from_s3(bucket_name, s3_data_path):
    """Retrieve a set of samples from an S3 bucket.

    Args:
        bucket_name (str): The name of the S3 bucket.
        s3_data_path (str): The path to the samples file within the bucket.

    Returns:
        dict: A dictionary with the samples, or None if an error occurs.
              For example:
              {
                  "detectors": [...],
                  "observables": [...]
              }
    """
    try:
        s3 = get_connection_s3()
        response = s3.get_object(Bucket=bucket_name, Key=s3_data_path)
        dict_samples = json.loads(response['Body'].read().decode('utf-8'))
        logging.info("Samples loaded from S3.")
        dict_samples["detectors"] = np.array(dict_samples["detectors"])
        dict_samples["observables"] = np.array(dict_samples["observables"])

        return dict_samples
    except ClientError as e:
        logging.error(f"Error loading samples from S3: {e}")
        raise RuntimeError("Error loading samples from S3") from e

def delete_samples_from_s3(bucket_name, s3_data_path):
    """Delete a set of samples from an S3 bucket.

    Args:
        bucket_name (str): The name of the S3 bucket.
        s3_data_path (str): The path to the samples file within the bucket.

    Returns:
        bool: True if the samples were deleted successfully, False otherwise.
    """
    try:
        s3 = get_connection_s3()
        s3.delete_object(Bucket=bucket_name, Key=s3_data_path)
        logging.info("Samples deleted from S3.")
        return True
    except ClientError as e:
        logging.error(f"Error deleting samples from S3: {e}")
        raise RuntimeError("Error deleting samples from S3") from e
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

def get_samples_info_from_dynamodb(id_nmc_batch):
    """Get information about a batch of NMC samples from DynamoDB.

    This includes the S3 path to the samples file.

    Args:
        id_nmc_batch (str): The ID of the NMC batch.

    Returns:
        dict: The item from DynamoDB containing sample information, or None if an error occurs or the item is not found.
            For example:
            {
                "id_nmc_batch": "nmc_batch_1",
                "s3_data_path": "s3://bucket/nmc_batch_1.json",
                "workers_completed": 0
            }
    """
    try:
        dynamodb = get_connection_dynamodb()
        table = dynamodb.Table(os.getenv('DYNAMODB_SAMPLES_TABLE_NAME'))
        response = table.get_item(
            Key={
                'id_nmc_batch': id_nmc_batch,
            }
        )
        return response.get('Item')
    except ClientError as e:
        logging.error(f"Error loading samples info from DynamoDB: {e}")
        raise RuntimeError("Error loading samples info from DynamoDB") from e    

def replace_decimals(obj):
    """Convert decimal.Decimal instances to int or float."""
    if isinstance(obj, list):
        for i in range(len(obj)):
            obj[i] = replace_decimals(obj[i])
        return obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = replace_decimals(v)
        return obj
    elif isinstance(obj, decimal.Decimal):
        if obj % 1 == 0:
            return int(obj)
        else:
            return float(obj)
    else:
        return obj
    
def convert_to_dynamodb_format(obj):
    """Convert data types to DynamoDB compatible format when saving."""
    if isinstance(obj, list):
        return [convert_to_dynamodb_format(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: convert_to_dynamodb_format(v) for k, v in obj.items()}
    elif isinstance(obj, (int, float)):
        return decimal.Decimal(str(obj))
    elif isinstance(obj, np.integer):
        return decimal.Decimal(str(int(obj)))
    elif isinstance(obj, np.floating):
        return decimal.Decimal(str(float(obj)))
    else:
        return obj

def get_args_list_from_dynamodb(id_batch_arguments):
    """Retrieve a set of arguments from the DynamoDB arguments table.

    Args:
        id_batch_arguments (int): The ID of the arguments batch.

    Returns:
        list: A list of argument items from the DynamoDB arguments table, or an empty list if none are found.
    """
    try:
        dynamodb = get_connection_dynamodb()
        table = dynamodb.Table(os.getenv('DYNAMODB_ARGS_TABLE_NAME'))
        
        # Query the table for all items with the given id_batch_arguments 
        response = table.query(
            KeyConditionExpression=Key('id_batch_arguments').eq(id_batch_arguments)
        )
        items = response.get('Items', [])
        if not items:
            logging.warning(f"No arguments found for id_batch_arguments: {id_batch_arguments}")
        else:
            for item in items:
                item["arguments"] = replace_decimals(item["arguments"])    
            logging.info(f"Successfully retrieved {len(items)} arguments for id_batch_arguments: {id_batch_arguments}")
        return items
    except ClientError as e:
        logging.error(f"Error getting arguments from DynamoDB: {e}")
        raise RuntimeError("Error getting arguments from DynamoDB") from e

def add_workers_completed_to_dynamodb(dynamodb, id_nmc_batch):
    """Increment the 'workers_completed' counter for an NMC batch in DynamoDB.

    This is called when an args_worker finishes its job.

    Args:
        id_nmc_batch (str): The ID of the NMC batch to update.

    Returns:
        dict: The response from the update_item call, or None if an error occurs.
            For example:
            {
                "id_nmc_batch": "nmc_batch_1",
                "s3_data_path": "s3://bucket/nmc_batch_1.json",
                "workers_completed": 1
            }
    """
    try:
        table = dynamodb.Table(os.getenv('DYNAMODB_SAMPLES_TABLE_NAME'))
        response = table.update_item(
            Key={
                'id_nmc_batch': id_nmc_batch,
            },
            UpdateExpression='SET workers_completed = workers_completed + :val',
            ExpressionAttributeValues={
                ':val': 1
            },
            ReturnValues='UPDATED_NEW'
        )
        return response["Attributes"]["workers_completed"]
    except ClientError as e:
        logging.error(f"Error adding workers completed to DynamoDB: {e}")
        raise RuntimeError("Error adding workers completed to DynamoDB") from e

def create_results_table_if_not_exists(dynamodb, table_name):
    """Create a DynamoDB table for storing results if it does not exist.
    Args:
        table_name (str): The name of the DynamoDB table to create.
    Returns:
        table: The created or existing table.
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
                        {'AttributeName': 'id_nmc_batch', 'KeyType': 'HASH'},
                        {'AttributeName': 'id_arguments', 'KeyType': 'RANGE'}
                    ],
                    AttributeDefinitions=[
                        {'AttributeName': 'id_nmc_batch', 'AttributeType': 'S'},
                        {'AttributeName': 'id_arguments', 'AttributeType': 'S'}
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

#endregion

    
# def do_simulation(arguments, codeConfig, p, id_nmc_batch, detectors, observables, pcm, observable_mat, error_channel):
# AUTOMORFISMOS
def do_simulation(arguments, codeConfig, p, id_nmc_batch, row_perm, detectors, observables, pcm, observable_mat, error_channel):
    # * Initialize decoders
    if arguments["decoder_type"] == "BP":
        logging.info(f"BP decoder initialized")
        _decoder = BpDecoder(pcm, error_rate=float(p), error_channel=error_channel, **arguments["arguments"])
    elif arguments["decoder_type"] == "BPLSD":
        logging.info(f"BPLSD decoder initialized")
        _decoder = BpLsdDecoder(pcm, error_rate=float(p), error_channel=error_channel, **arguments["arguments"])
    elif arguments["decoder_type"] == "BPOSD":
        logging.info(f"BPOSD decoder initialized")
        _decoder = BpOsdDecoder(pcm, error_rate=float(p), error_channel=error_channel, **arguments["arguments"])
    else:
        raise ValueError(f"Decoder type {arguments["decoder_type"]} not supported")

    # * Initialize results
    Pl = 0
    time_av = 0
    time_max = 0
    corrected_patterns = []
    
    # * Run Monte Carlo trials
    NMCs_size = len(detectors)
    logging.info(f"Running {NMCs_size} Monte Carlo trials")

    # ! DEBUG: Pintar shapes de matrices
    # logging.info(f"PCM shape: {pcm.shape}")
    # logging.info(f"observable_mat shape: {observable_mat.shape}")
    # logging.info(f"Detector shape: {detectors[0].shape}")

    for i in range(NMCs_size):
        a = time.time()
        # predicted_error = _decoder.decode(detectors[i])
        # AUTOMORFISMOS
        predicted_error = _decoder.decode(row_perm @ detectors[i] % 2)
        b = time.time()
        time_av += (b - a) / NMCs_size
        time_max = max(time_max, (b - a))

        # # ! DEBUG: Pintar tipos de datos
        # print("observable_mat type, shape:", type(observable_mat), observable_mat.shape)
        # print("predicted_error type, shape:", type(predicted_error), predicted_error.shape)
        # print("observables type2, shape:", type(np.atleast_2d(observables[i])), np.atleast_2d(observables[i]).shape)
        # print("observable_mat:\n", observable_mat)
        # print("predicted_error:\n", predicted_error)
        # print("observables[i]:\n", observables[i])

        logical_error = (observable_mat @ predicted_error + np.atleast_2d(observables[i])) % 2
       
        # ! DEBUG
        # logging.info(f"Patron {i}:")
        # logging.info(f"  predicted_error: {predicted_error}")
        # logging.info(f"  observables[i]: {observables[i]}")
        # logging.info(f"  logical_error: {logical_error}")
        # logging.info(f"  logical_error shape: {logical_error.shape}")
        # syndrome = row_perm @ detectors[i] % 2
        # logging.info(f"Syndrome: {syndrome}")
        # logging.info(f"Syndrome shape: {syndrome.shape}")
        # logging.info(f"Syndrome sum (should not be 0): {np.sum(syndrome)}")
        
        if np.any(logical_error == 1):
            Pl += 1 / NMCs_size
            corrected_patterns.append(i)
            logging.info(f"  Error lógico corregido en patrón {i}")
    
    # * Results
    results = {
        "id_nmc_batch": id_nmc_batch, # ID of the NMC batch: nmc_{code}_{p(0c001)}_{nmc_batch_counter}
        "id_arguments": arguments["id_arguments"], # ID of the arguments used: Decoder_{id_automorphism}
        "id_automorphism": arguments["id_automorphism"], # ID of the automorphism used: {id_automorphism}
        "codeConfig": codeConfig, # Possible codes: 72, 90, 108, 144, 288, 784
        "error_rate": p, # Error probability
        "decoder_type": arguments["decoder_type"], # Type of decoder
        "arguments": arguments, # Arguments for the decoder
        "Pl": Pl, # Logical error detection probability in the batch
        "time_av": time_av, # Average decoding time in the batch
        "time_max": time_max, # Maximum decoding time in the batch
        "corrected_patterns": corrected_patterns # Patterns where the decoder successfully corrected the error
    }
    return results

def lambda_handler(event, context=None):
    try:
        logging.info(f"Event received in args_worker lambda_handler")

        # * Input variables
        # Event variables received from nmc_worker
        if "body" in event: # if the event comes from http (Local testing)
            received_event = json.loads(event["body"])
        else:               # if the event comes from AWS Lambda
            received_event = event

        id_nmc_batch = received_event.get("id_nmc_batch")
        number_of_args_combinations_batches = received_event.get("number_of_args_combinations_batches")
        id_batch_arguments = received_event.get("id_batch_arguments")

        # Simulation variables extracted from id_nmc_batch
        codeConfig = int(id_nmc_batch.split("_")[1])
        p = float(id_nmc_batch.split("_")[2].replace("c", "."))

        logging.info(f"codeConfig: {codeConfig}, p: {p}")

        # * Build quantum code
        # Parameters for simulation
        config = select_configuration(codeConfig)
        ell, m = config["ell"], config["m"]
        a1, a2, a3 = config["a"]
        b1, b2, b3 = config["b"]
        d = config["d"]
        logging.info(f"Config with codeConfig {codeConfig} loaded")
        # Construct the polynomials A and B for the code
        A_x_pows, A_y_pows = [a1], [a2, a3] 
        B_x_pows, B_y_pows = [b2, b3], [b1]
        code, A_list, B_list = create_bivariate_bicycle_codes(ell, m, A_x_pows, A_y_pows, B_x_pows, B_y_pows)
        logging.info(f"Bivariate bicycle code created")
        # ! ¿Por qué se calcula pcm aquí si luego se calcula de nuevo?
        # pcm = sparse.csc_matrix(code.hx, dtype=np.uint8)

        # * Build circuit and detector error model
        circuit = build_circuit(code, A_list, B_list, p=p, num_repeat=d, z_basis=True, use_both=False)
        logging.info(f"Circuit built")
        dem = circuit.detector_error_model()
        logging.info(f"Detector error model built")
        
        # * Convert detector error model to check matrices
        matrices = detector_error_model_to_check_matrices(dem, allow_undecomposed_hyperedges=True)
        logging.info(f"Detector error model converted to check matrices")
        pcm = matrices.check_matrix                     # Parity check matrix
        observable_mat = matrices.observables_matrix    # Logical observables matrix
        error_channel = matrices.priors

        # Args variables loaded from DynamoDB
        args_list = get_args_list_from_dynamodb(id_batch_arguments)
        logging.info(f"Args variables loaded from DynamoDB")

        # Detector and observable arrays loaded from S3
        samples_info = get_samples_info_from_dynamodb(id_nmc_batch)
        detectors, observables = get_samples_from_s3(os.getenv('S3_BUCKET_NAME'), samples_info["s3_data_path"]).values()

        for arguments in args_list:
            # Leer esta informacion de S3
            
            # results = do_simulation(arguments, codeConfig, p, id_nmc_batch, detectors, observables, pcm, observable_mat, error_channel)
            # AUTOMORFISMOS
            pcm, error_channel, row_perm = get_automorphism_from_s3(arguments["id_automorphism"], error_rate=p)
            results = do_simulation(arguments, codeConfig, p, id_nmc_batch, row_perm, detectors, observables, pcm, observable_mat, error_channel)


            results = convert_to_dynamodb_format(results)
            
            results = convert_to_dynamodb_format(results)

            # * Save results to DynamoDB
            if os.getenv('DYNAMODB_RESULTS_TABLE_NAME') is None:
                raise ValueError("DYNAMODB_RESULTS_TABLE_NAME is not defined in environment variables")
            logging.info(f"Saving results to DynamoDB for id_nmc_batch: {id_nmc_batch}, id_arguments: {arguments['id_arguments']}")
            
            dynamodb = get_connection_dynamodb()

            # ! SOLO PARA PRUEBAS LOCALES - Comprobación de que la tabla existe o se crea si no existe.
            table = create_results_table_if_not_exists(dynamodb, os.getenv('DYNAMODB_RESULTS_TABLE_NAME')) 
            
            # ! EN PRODUCCIÓN - Se asume que la tabla ya existe.
            # table = dynamodb.Table(os.getenv('DYNAMODB_RESULTS_TABLE_NAME'))

            try:
                table.put_item(Item=results)
                logging.info(f"Results saved to DynamoDB for id_nmc_batch: {results['id_nmc_batch']}")
            except ClientError as e:
                logging.error(f"Error saving results to DynamoDB: {e}")
                raise RuntimeError("Error saving results to DynamoDB") from e

        # * Update workers_completed in samples_dynamodb
        if add_workers_completed_to_dynamodb(dynamodb, id_nmc_batch) >= number_of_args_combinations_batches:
            delete_samples_from_s3(os.getenv('S3_BUCKET_NAME'), samples_info["s3_data_path"])

        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Error in args_worker lambda_handler: {e}")
        return {"status": "failed"}
